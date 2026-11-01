"""sidekick.body.body — BodySession: the one place the rest of sidekick touches the robot

Overview
    `BodySession.shared` wraps a `BodyBackend` (Reachy or null) with the threads that make it
    usable from asyncio code: the motion owner, the audio pump, the paced player and a status
    monitor that mirrors wake/sleep state, caches the direction of arrival and the tracked face,
    and fires callbacks on touch and on state changes. Public verbs are body-agnostic:
    `look`, `look_at_doa`, `gesture`, `express` / `beat` / `hold_state` / `end_state` (Bobby's
    own expression library on the motion owner's three layers), `set_style` /
    `set_expressiveness` (how big motions are), `antennas`, `track_face`, `speak`, `duck`,
    `stop_speaking`, `subscribe_audio`, `subscribe_speaker`, `frame`, `doa` / `doa_between`,
    `face`, `status`,
    `telemetry` (one sample of commanded pose, measured pose / joints, audio levels and peak
    rings for the Live view and the recorder), `moving` / `moving_until` (the motion owner's
    window of self-motion, so the voice front end can discount motor noise) and `display_model`
    (the URDF reduced for 3D).
    A controller takes the motion owner over with `take_control()` and drives it with
    `manual_pose()` (head, height, body yaw, antennas) plus the `manual=True` variants of
    `gesture` / `express`; `release_control()` hands it back. There is no idle breathing any more
    (the owner retired it, block #80): an idle Bobby looks around instead (`interaction`).
Design
    Threads, not asyncio, because the SDK and GStreamer are blocking; consumers bridge events
    into their loop with `call_soon_threadsafe`. The **frame pump** is one more thread: the SDK
    hands each camera frame out once and blocks up to 20 ms per read, so with three readers
    (recorder, dashboard stream, face detector) each saw a third of the frames (2.3 fps on the
    Live card, 2026-10-27). The pump is the only caller of `backend.frame()`; `frame()` returns
    the latest cached frame to every consumer and `camera_fps` measures the real rate. The session never wakes or sleeps the robot
    (invariant 11) — it reads the state and gates motion on it: targets flow only while awake.
    Only the motion owner calls `set_target` (invariant 10). Expressions come from
    `expression_library.json` (block #50); a name resolves directly or through an entry's
    aliases, `gaze_held()` tells the face servo to wait while one turns the head, and the
    energy handed to the owner is `expressiveness` (the household's baseline, a config field)
    × the current reply's style (`STYLE_ENERGY`: calm / natural / lively). The factory `BodySession.make()`
    picks the backend from `ConfigBody`; `setup()` re-binds a changed body config before each
    start of the service (block #87). `start()` brings the robot up — the daemon spawned when
    this sidekick manages it (`body.manage_daemon`, never by hand) or its backend started when it
    was stopped, then the connection, then a few seconds' wait for the first telemetry, camera
    frame and microphone audio that `check()` reports — and `stop()` turns it off: disconnect,
    then the daemon sidekick spawned is stopped (it puts the robot to sleep and releases the
    camera and audio) or another daemon is asked to sleep (block #85). Each run gets its own stop
    event, so a thread that outlived its join is never revived by the next start. The monitor keeps the
    last 30 s of direction-of-arrival readings: one reading is ±50° noisy and the one taken when
    a sentence has just ended is mostly the room, so `doa_between(start, end)` gives a stretch
    of speech the median of its readings (the chip's speech-flagged ones when there are any)
    and the share that agree (block #80).
Depends on
    sidekick.log, sidekick.audio, numpy.

See Also
--------
    AGENTS.md "Body", PLAN.md block "[2026-10-26 #12]".

"""

from __future__ import annotations

import asyncio
import collections
import math
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt

from sidekick.audio import AudioClip
from sidekick.log import Log

from .daemon import BodyDaemon, BodyDaemonConfiguration
from .expression import ExpressionSpec, load_library
from .media import AudioPlayer, AudioPump
from .model import display_model, mesh_path
from .motion import MotionOwner
from .null import BodyNullBackend
from .reachy import BodyReachyBackend, BodyReachyConfiguration
from .schemas import (
    ANTENNA_LIMIT,
    BODY_YAW_LIMIT,
    INIT_ANTENNAS,
    LISTENING_ANTENNAS,
    PITCH_LIMIT,
    ROLL_LIMIT,
    STYLE_ENERGY,
    YAW_LIMIT,
    Z_LIMIT,
    BodyBackend,
    BodyDoA,
    BodyFace,
    BodyState,
    BodyStatus,
    BodyTelemetry,
    BodyTouch,
    FloatArray,
    Gesture,
    LookTarget,
    MotionPose,
    clamp,
    doa_to_yaw,
)
from .sway import SpeechSway, SwayConfiguration

TouchCallback = Callable[[BodyTouch], None]
StateCallback = Callable[[BodyStatus, BodyStatus], None]

DOA_HISTORY_S = 30.0  # direction readings kept for `doa_between`
DOA_AGREE_RAD = math.radians(15.0)  # a reading this close to the median agrees with it


class BodySession:
    """Façade over one body."""

    shared: ClassVar[BodySession]

    def __init__(self, backend: BodyBackend | None = None, poll_hz: float = 5.0) -> None:
        self.backend: BodyBackend = backend if backend is not None else BodyNullBackend()
        self.poll_period = 1.0 / poll_hz
        self.motion: MotionOwner | None = None
        self.pump: AudioPump | None = None
        self.player: AudioPlayer | None = None
        self._monitor: threading.Thread | None = None
        self._stop = threading.Event()
        self._status = BodyStatus(BodyState.DISCONNECTED)
        self._doa: BodyDoA | None = None
        self._doa_at = 0.0
        self._doa_history: collections.deque[tuple[float, BodyDoA]] = collections.deque(
            maxlen=max(16, int(DOA_HISTORY_S * poll_hz))
        )
        self._face = BodyFace(False)
        self._frame: npt.NDArray[np.uint8] | None = None
        self._frame_ts = 0.0
        self._frame_times: collections.deque[float] = collections.deque(maxlen=120)
        self._frame_lock = threading.Lock()
        self._frame_thread: threading.Thread | None = None
        self._fov: tuple[float, float] | None = None
        self._touch_callbacks: list[TouchCallback] = []
        self._state_callbacks: list[StateCallback] = []
        self._lock = threading.Lock()
        self.daemon: BodyDaemon | None = None
        self.mode = "reachy" if getattr(self.backend, "name", "null") == "reachy" else "null"
        self.manage_daemon = False
        self._flow: dict[str, bool] = {}  # what arrived after the last connect (`check()`)
        self.volume: int | None = None
        self.connected_at: float | None = None
        self.controller: str | None = None
        self.controlled_since: float | None = None
        self.sway_configuration = SwayConfiguration()
        self.sdk_wobble = False
        self.sway: SpeechSway | None = None
        self.library: dict[str, ExpressionSpec] = load_library()
        self._aliases = {
            alias.lower(): spec.name for spec in self.library.values() for alias in spec.aliases
        }
        self.expressiveness = 1.0
        self.style = "natural"
        self.last_touch: tuple[float, str] | None = None  # wall time, side (Live page)

    # ----------------------------------------------------------------- factory

    @classmethod
    def make(cls, body: Any, home: Path, robot_name: str = "reachy_mini") -> BodySession:
        """Build from a `ConfigBody`-shaped object (duck-typed to keep `body` below `config`)."""
        session = cls()
        session.setup(body, home, robot_name)
        return session

    def setup(self, body: Any, home: Path, robot_name: str = "reachy_mini") -> None:
        """Bind a `ConfigBody`-shaped config: backend, daemon and motion settings.

        The service calls it before each start, so a changed body setting applies at the next
        start; the backend is only replaced while disconnected.
        """
        mode = getattr(body, "mode", "null")
        if self.connected:
            Log.warning("body settings re-bound while connected; the backend stays until stop")
        else:
            self.mode = mode
            self.backend = (
                BodyReachyBackend(
                    BodyReachyConfiguration(
                        host=body.host, port=body.port, media_backend=body.media_backend
                    )
                )
                if mode == "reachy"
                else BodyNullBackend()
            )
        self.volume = getattr(body, "volume", None)
        self.sway_configuration = SwayConfiguration.from_config(getattr(body, "sway", None))
        self.sdk_wobble = bool(getattr(body, "sdk_wobble", False))
        self.expressiveness = float(getattr(body, "expressiveness", 1.0))
        self.daemon = BodyDaemon(
            BodyDaemonConfiguration(
                host=body.host,
                port=body.port,
                sim=body.sim,
                wake_on_start=body.wake_on_start,
                sleep_on_stop=body.sleep_on_stop,
                preload_datasets=body.preload_datasets,
                log_level=body.daemon_log_level,
                robot_name=robot_name,
                start_timeout_s=body.daemon_start_timeout_s,
            ),
            home,
        )
        self.manage_daemon = mode == "reachy" and bool(getattr(body, "manage_daemon", False))

    # --------------------------------------------------------------- lifecycle

    async def start(self) -> BodyStatus:
        """Bring the robot up: the daemon, the connection, then a look at what flows."""
        if self.mode == "reachy" and self.daemon is not None:
            daemon = await asyncio.to_thread(self.daemon.ensure_running, self.manage_daemon)
            if not daemon.running:
                Log.error(f"daemon not running: {daemon.line()}")
        status = await asyncio.to_thread(self.connect)
        if status.connected and self.mode == "reachy":
            await asyncio.to_thread(self._await_flow)
        elif not status.connected:
            Log.warning("running without a body connection; voice front end is idle")
        return status

    async def stop(self) -> None:
        """Turn the robot off: disconnect, then stop (or put to sleep) its daemon."""
        self.controller = None
        self.controlled_since = None
        await asyncio.to_thread(self.close)
        if self.mode == "reachy" and self.daemon is not None:
            await asyncio.to_thread(self.daemon.shutdown)

    def _await_flow(self, timeout_s: float = 8.0) -> None:
        """Wait (bounded) for the first telemetry, camera frame and microphone audio.

        A daemon just spawned hands out its first camera frame ~5 s after it answers; with the
        daemon already up everything arrives within a second and the wait ends then.
        """
        pump = self.pump
        chunks = pump.chunks if pump is not None else 0
        deadline = time.monotonic() + timeout_s
        flow = {"pose": False, "frame": False, "mic": False}
        while time.monotonic() < deadline and not all(flow.values()):
            flow["pose"] = flow["pose"] or self.backend.present_head_pose() is not None
            flow["frame"] = flow["frame"] or self.frame(max_age_s=1.0) is not None
            flow["mic"] = flow["mic"] or (pump is not None and pump.chunks > chunks)
            time.sleep(0.1)
        self._flow = flow

    def check(self) -> list[dict[str, Any]]:
        """Readiness items: the daemon, the connection, telemetry, the camera, the microphone."""
        if self.mode != "reachy":
            return [
                {"id": "body", "title": "robot", "level": "ok", "detail": "no robot (null body)"}
            ]
        items: list[dict[str, Any]] = []
        daemon = self.daemon.cached_status(2.0) if self.daemon is not None else None
        if daemon is not None:
            items.append(
                {
                    "id": "daemon",
                    "title": "daemon",
                    "level": "ok" if daemon.running else "bad",
                    "detail": daemon.line(),
                }
            )
        status = self._status
        if not status.connected:
            detail = status.error or "not connected"
            items.append({"id": "link", "title": "connection", "level": "bad", "detail": detail})
            return items
        awake = status.state == BodyState.AWAKE
        items.append(
            {
                "id": "link",
                "title": "connection",
                "level": "ok" if awake else "warn",
                "detail": f"{status.robot_name or 'robot'} {status.state.value}"
                + (" · simulated" if status.simulated else ""),
            }
        )
        flow, pump = self._flow, self.pump
        mic_ok = bool(flow.get("mic")) or (pump is not None and pump.level_dbfs > -90.0)
        items.append(
            {
                "id": "telemetry",
                "title": "telemetry",
                "level": "ok" if flow.get("pose") or self.motion is not None else "warn",
                "detail": "head pose arriving" if flow.get("pose") else "no head pose yet",
            }
        )
        fps = self.camera_fps()
        items.append(
            {
                "id": "camera",
                "title": "camera",
                "level": "ok" if fps > 0 or flow.get("frame") else "warn",
                "detail": f"{fps:.0f} fps" if fps > 0 else "no frame",
            }
        )
        items.append(
            {
                "id": "mic",
                "title": "microphone",
                "level": "ok" if mic_ok else "bad",
                "detail": f"{pump.level_dbfs:.0f} dBFS" if mic_ok and pump else "no audio arriving",
            }
        )
        return items

    def connect(self, audio: bool = True, wobble: bool | None = None) -> BodyStatus:
        """Connect the backend and start the owner threads.

        `wobble` is the SDK's daemon-side head wobble; None follows `ConfigBody.sdk_wobble`
        (off by default: our own `SpeechSway` moves the head with the voice instead).
        """
        Log.info0(f"backend={self.backend.name}")
        wobble = self.sdk_wobble if wobble is None else wobble
        status = self.backend.connect()
        self._status = status
        if not status.connected:
            Log.warning(f"body not connected: {status.error}")
            return status
        self.connected_at = time.monotonic()
        if self.volume is not None and hasattr(self.backend, "set_volume"):
            self.backend.set_volume(int(self.volume))
        if audio:
            try:
                self.backend.start_audio()
            except Exception as exc:
                Log.error(f"audio start failed: {exc!r}")
            else:
                self.pump = AudioPump(self.backend)
                self.player = AudioPlayer(self.backend)
                self.sway = SpeechSway(self.sway_configuration)
                self.player.sway = self.sway
                self.pump.start()
                self.player.start()
                self.backend.set_wobbling(bool(wobble))
        self.motion = MotionOwner(self.backend, on_touch=self._on_touch)
        self.motion.sway = self.sway
        self.motion.library = self.library
        self.motion.energy = self.energy
        self.motion.enable(status.awake)
        self.motion.start()
        stop = threading.Event()  # this run's: a thread left over from the last run keeps its own
        self._stop = stop
        self._monitor = threading.Thread(
            target=self._monitor_loop, args=(stop,), name="sidekick-body-monitor", daemon=True
        )
        self._monitor.start()
        self._frame_thread = threading.Thread(
            target=self._frame_loop, args=(stop,), name="sidekick-body-frames", daemon=True
        )
        self._frame_thread.start()
        return status

    def close(self) -> None:
        """Stop threads and release the backend."""
        Log.info0()
        self._stop.set()
        if self.motion is not None:
            self.motion.stop()
        if self.player is not None:
            self.player.stop()
        if self.pump is not None:
            self.pump.stop()
        for thread in (self.motion, self.player, self.pump, self._monitor, self._frame_thread):
            if (
                thread is not None
                and thread.is_alive()
                and thread is not threading.current_thread()
            ):
                thread.join(timeout=2.0)
        try:
            self.backend.set_wobbling(False)
        except Exception:
            pass
        self.backend.close()
        self._status = BodyStatus(BodyState.DISCONNECTED)
        self.motion = self.player = self.pump = self._monitor = self._frame_thread = None
        with self._frame_lock:
            self._frame, self._frame_ts = None, 0.0
            self._frame_times.clear()

    def _frame_loop(self, stop: threading.Event) -> None:
        """The only reader of the backend's camera: keep the latest frame for everyone."""
        while not stop.is_set():
            try:
                frame = self.backend.frame()
            except Exception as exc:
                Log.warning(f"frame pump: {exc!r}")
                frame = None
            if frame is None:
                time.sleep(0.02)
                continue
            now = time.monotonic()
            with self._frame_lock:
                self._frame, self._frame_ts = frame, now
                self._frame_times.append(now)
            time.sleep(0.005)  # a backend that re-serves the same frame must not spin

    def _monitor_loop(self, stop: threading.Event) -> None:
        tick = 0
        while not stop.is_set():
            tick += 1
            try:
                doa = self.backend.doa()
                if doa is not None:
                    with self._lock:
                        self._doa, self._doa_at = doa, time.monotonic()
                        self._doa_history.append((self._doa_at, doa))
                if tick % 2 == 0:
                    previous = self._status
                    status = self.backend.status()
                    self._face = self.backend.tracked_face()
                    if status != previous:
                        self._status = status
                        if status.state != previous.state:
                            Log.info(f"body state {previous.state.value} -> {status.state.value}")
                            if self.motion is not None:
                                self.motion.enable(status.awake)
                            for callback in list(self._state_callbacks):
                                callback(previous, status)
            except Exception as exc:
                Log.warning(f"monitor: {exc!r}")
            time.sleep(self.poll_period)

    # ------------------------------------------------------------------ events

    def on_touch(self, callback: TouchCallback) -> None:
        """Register for antenna pushes (called from the motion thread); once per callback."""
        if callback not in self._touch_callbacks:
            self._touch_callbacks.append(callback)

    def on_state_change(self, callback: StateCallback) -> None:
        """Register for wake/sleep/disconnect transitions (monitor thread); once per callback."""
        if callback not in self._state_callbacks:
            self._state_callbacks.append(callback)

    def _on_touch(self, event: BodyTouch) -> None:
        self.last_touch = (time.time(), str(getattr(event, "side", "")))
        for callback in list(self._touch_callbacks):
            try:
                callback(event)
            except Exception as exc:
                Log.error(f"touch callback: {exc!r}")

    # ------------------------------------------------------------------- state

    def status(self) -> BodyStatus:
        """Last mirrored status."""
        return self._status

    @property
    def state(self) -> BodyState:
        """Last mirrored state."""
        return self._status.state

    @property
    def connected(self) -> bool:
        """Whether the backend is connected."""
        return self._status.connected

    @property
    def awake(self) -> bool:
        """Whether targets currently reach the motors."""
        return self._status.awake

    def doa(self, max_age_s: float = 1.0) -> BodyDoA | None:
        """Latest direction of arrival if fresh enough."""
        with self._lock:
            if self._doa is None or time.monotonic() - self._doa_at > max_age_s:
                return None
            return self._doa

    def doa_between(self, start: float, end: float) -> BodyDoA | None:
        """The direction of a stretch of speech (monotonic times), or None without readings.

        The median of the readings taken in the window — the chip's speech-flagged ones when
        there are any — with `agreement` = the share of them within `DOA_AGREE_RAD` of it.
        Angles run 0 … π (left, front, right), so a plain median needs no wrap-around.
        """
        with self._lock:
            readings = [doa for ts, doa in self._doa_history if start <= ts <= end]
        if not readings:
            return None
        speech = [doa for doa in readings if doa.speech]
        angles = sorted(doa.angle for doa in speech or readings)
        median = angles[len(angles) // 2]
        agree = sum(1 for angle in angles if abs(angle - median) <= DOA_AGREE_RAD)
        return BodyDoA(median, bool(speech), round(agree / len(angles), 2))

    def face(self) -> BodyFace:
        """Latest tracked face."""
        return self._face

    def frame(self, wait_s: float = 0.0, max_age_s: float = 1.0) -> npt.NDArray[np.uint8] | None:
        """The latest camera frame from the pump (shared by every reader), or None when stale.

        Without a running pump (tests on a bare session) the backend is read directly;
        `wait_s` > 0 waits that long for a first frame.
        """
        deadline = time.monotonic() + wait_s
        while True:
            if self._frame_thread is None:
                frame = self.backend.frame()
            else:
                with self._frame_lock:
                    fresh = time.monotonic() - self._frame_ts <= max_age_s
                    frame = self._frame if fresh else None
            if frame is not None or time.monotonic() >= deadline:
                return frame
            time.sleep(0.02)

    def camera_fps(self) -> float:
        """Frames the pump pulled in the last second."""
        now = time.monotonic()
        with self._frame_lock:
            return float(sum(1 for t in self._frame_times if now - t <= 1.0))

    def camera_fov(self) -> tuple[float, float] | None:
        """(horizontal, vertical) field of view in radians from the camera intrinsics."""
        if self._fov is None:
            spec = self.backend.camera_matrix()
            if spec is None:
                return None
            matrix, width, height = spec
            fx, fy = float(matrix[0, 0]), float(matrix[1, 1])
            if fx <= 0 or fy <= 0:
                return None
            self._fov = (2.0 * math.atan(width / (2.0 * fx)), 2.0 * math.atan(height / (2.0 * fy)))
            Log.info(
                f"camera fov {math.degrees(self._fov[0]):.0f}° x {math.degrees(self._fov[1]):.0f}°"
                f" ({width}x{height})"
            )
        return self._fov

    def current_look(self) -> LookTarget:
        """The motion owner's eased look pose (the face servo's base)."""
        return self.motion.current_look() if self.motion is not None else LookTarget()

    # ------------------------------------------------------------- expressions

    def expression(self, name: str) -> ExpressionSpec | None:
        """A library entry by name or alias (case-insensitive), else by a unique prefix (≥ 4)."""
        key = name.strip().lower().replace(" ", "_").replace("-", "_")
        spec = self.library.get(key) or self.library.get(self._aliases.get(key, ""))
        if spec is not None or len(key) < 4:
            return spec
        hits = {n for n in self.library if n.startswith(key)}
        hits |= {target for alias, target in self._aliases.items() if alias.startswith(key)}
        return self.library[hits.pop()] if len(hits) == 1 else None

    def expression_catalog(self) -> list[dict[str, Any]]:
        """Every entry for the dashboard and the agent, by kind then name."""
        order = {"beat": 0, "emotion": 1, "performance": 2, "state": 3}
        specs = sorted(self.library.values(), key=lambda s: (order.get(s.kind, 9), s.name))
        return [spec.as_dict() for spec in specs]

    @property
    def energy(self) -> float:
        """How big motions are right now: expressiveness × the current reply's style."""
        return self.expressiveness * STYLE_ENERGY.get(self.style, 1.0)

    def set_style(self, style: str) -> None:
        """The current reply's style (`[style:…]`); natural again when the reply ends."""
        self.style = style if style in STYLE_ENERGY else "natural"
        if self.motion is not None:
            self.motion.energy = self.energy

    def set_expressiveness(self, value: float) -> None:
        """The household's baseline (`ConfigBody.expressiveness`), applied live."""
        self.expressiveness = max(0.0, float(value))
        if self.motion is not None:
            self.motion.energy = self.energy
        Log.info(f"expressiveness {self.expressiveness:.2f}")

    def _play(
        self,
        name: str,
        layer: str,
        intensity: float = 1.0,
        mirror: bool = False,
        delay_s: float = 0.0,
        manual: bool = False,
    ) -> bool:
        spec = self.expression(name)
        if spec is None:
            Log.info(f"unknown expression {name!r} ignored")
            return False
        if self.motion is not None:
            self.motion.expression(spec.name, layer, intensity, mirror, delay_s, manual)
        return True

    def express(self, name: str, manual: bool = False, intensity: float = 1.0) -> bool:
        """An expression the agent or the dashboard asked for; False when the name is unknown."""
        return self._play(name, "express", intensity, manual=manual)

    def beat(self, name: str, intensity: float = 1.0) -> bool:
        """A small automatic motion (acknowledge, backchannel, turn-yield) on its own layer."""
        return self._play(name, "beat", intensity)

    def hold_state(self, name: str, mirror: bool = False, delay_s: float = 0.0) -> bool:
        """Start a state (thinking) that runs until `end_state()`; chained states follow."""
        return self._play(name, "state", mirror=mirror, delay_s=delay_s)

    def end_state(self, fade_s: float = 0.35) -> None:
        """Fade the state out (the head eases back onto its look target)."""
        if self.motion is not None:
            self.motion.stop_expression("state", fade_s)

    def gaze_held(self) -> bool:
        """Whether a state or an expression is turning the head (the face servo waits)."""
        return self.motion is not None and self.motion.state.gaze_held

    def telemetry(self, peaks: int = 10) -> BodyTelemetry:
        """One sample of pose, measured joints and audio levels (Live view, recorder)."""
        motion, pump, player = self.motion, self.pump, self.player
        commanded = motion.pose_snapshot if motion is not None else MotionPose()
        head = self.backend.present_head_pose()
        joints = self.backend.present_joints()
        doa = self.doa()
        playing = player is not None and player.is_playing()
        return BodyTelemetry(
            ts=time.time(),
            state=self._status.state.value,
            commanded=commanded,
            head_measured=None
            if head is None
            else tuple(float(v) for v in np.asarray(head, dtype=np.float64).reshape(-1)),
            joints_measured=None if joints is None else tuple(joints[0]),
            antennas_measured=None
            if joints is None or len(joints[1]) < 2
            else (joints[1][0], joints[1][1]),
            mic_dbfs=pump.level_dbfs if pump is not None else -100.0,
            speaker_dbfs=player.level_dbfs if playing and player is not None else -100.0,
            mic_peaks=tuple(list(pump.peaks)[-peaks:]) if pump is not None else (),
            speaker_peaks=tuple(list(player.peaks)[-peaks:])
            if playing and player is not None
            else (),
            speaking=playing,
            gain_db=player.gain_db if player is not None else 0.0,
            doa_yaw=doa.yaw if doa is not None else None,
            face=self._face if self._face.detected else None,
            camera_fps=self.camera_fps(),
        )

    @staticmethod
    def display_model() -> dict[str, Any]:
        """The SDK URDF reduced to what a 3D view needs (see `model.py`)."""
        return display_model()

    @staticmethod
    def mesh_path(name: str) -> Path | None:
        """An allowlisted STL mesh of the display model, from the installed SDK."""
        return mesh_path(name)

    # ------------------------------------------------------------------ motion

    def look(
        self, yaw: float = 0.0, pitch: float = 0.0, roll: float = 0.0, duration_s: float = 0.6
    ) -> None:
        """Rest the head on a direction (radians, left/up positive for yaw/pitch-up)."""
        if self.motion is not None:
            self.motion.look(
                LookTarget(clamp(yaw, -1.2, 1.2), clamp(pitch, -0.6, 0.6), roll, duration_s)
            )

    def look_at_doa(self, angle: float, duration_s: float = 0.5) -> None:
        """Turn toward a ReSpeaker angle."""
        self.look(yaw=doa_to_yaw(angle), duration_s=duration_s)

    def look_neutral(self, duration_s: float = 1.0) -> None:
        """Back to straight ahead."""
        self.look(duration_s=duration_s)

    def gesture(self, gesture: Gesture, manual: bool = False) -> None:
        """Nod, shake, tilt, look up, perk (library beats)."""
        if self.motion is not None:
            self.motion.gesture(gesture, manual=manual)

    def antennas(self, pose: tuple[float, float] | None, duration_s: float | None = None) -> None:
        """Hold an antenna pose; `listening()` and `relax()` are the common two."""
        if self.motion is not None:
            self.motion.antennas(pose, duration_s)

    def listening(self) -> None:
        """Lift the antennas as the listening cue."""
        self.antennas(LISTENING_ANTENNAS)

    def relax(self) -> None:
        """Antennas back to neutral."""
        self.antennas(INIT_ANTENNAS)

    def configure_sway(self, config: Any) -> SwayConfiguration:
        """Apply a changed `ConfigBody.sway` live (Settings slider)."""
        self.sway_configuration = SwayConfiguration.from_config(config)
        if self.sway is not None:
            self.sway.configure(self.sway_configuration)
        Log.info(f"speech sway master={self.sway_configuration.master:.2f}")
        return self.sway_configuration

    def track_face(self, enabled: bool, weight: float = 1.0) -> None:
        """Daemon-side face tracking."""
        self.backend.track_face(enabled, weight)

    def moving(self) -> bool:
        """Whether the motion owner is moving the head / antennas right now."""
        return self.motion is not None and self.motion.moving()

    def live(self) -> dict[str, Any]:
        """Vital signs for the Live page, from memory only (block #69)."""
        status = self._status
        motion = self.motion
        state = motion.state if motion is not None else None
        touch = self.last_touch
        return {
            "state": status.state.value,
            "daemon": status.daemon_state,
            "connected": status.connected,
            "error": status.error,
            "manual": bool(state is not None and state.manual),
            "holder": self.controller,
            "dropped": state.dropped if state is not None else 0,
            "layers": dict(state.layers) if state is not None else {},
            "look": None
            if state is None
            else {"yaw": round(state.look.yaw, 3), "pitch": round(state.look.pitch, 3)},
            "moving": self.moving(),
            "speaking": self.is_speaking(),
            "sway": bool(self.sway is not None and self.sway.enabled),
            "style": self.style,
            "volume": self.volume,
            "touch": None
            if touch is None
            else {"side": touch[1], "ago_s": round(time.time() - touch[0], 1)},
            "connected_at": self.connected_at,
        }

    def moving_until(self) -> float:
        """Monotonic time the current motion window ends (0 when nothing is moving)."""
        return self.motion.state.moving_until if self.motion is not None else 0.0

    # ----------------------------------------------------------- manual control

    def take_control(self, holder: str = "dashboard") -> None:
        """Hand the motion owner to a controller: every other motion source is dropped."""
        Log.info0(holder)
        self.controller = holder
        self.controlled_since = time.time()
        if self.motion is not None:
            self.motion.control(True)

    def release_control(self) -> None:
        """Give the motion owner back; the posture eases to neutral."""
        Log.info0(self.controller or "")
        self.controller = None
        self.controlled_since = None
        if self.motion is not None:
            self.motion.control(False)

    def control_status(self) -> dict[str, Any]:
        """Who holds the body, since when, and the limits a controller must respect."""
        motion = self.motion
        return {
            "held": self.controller is not None,
            "holder": self.controller,
            "since": self.controlled_since,
            "manual": bool(motion is not None and motion.state.manual),
            "dropped": motion.state.dropped if motion is not None else 0,
            "sway": self.sway.snapshot() if self.sway is not None else None,
            "limits": {
                "yaw": YAW_LIMIT,
                "pitch": PITCH_LIMIT,
                "roll": ROLL_LIMIT,
                "z": Z_LIMIT,
                "body_yaw": BODY_YAW_LIMIT,
                "antenna": ANTENNA_LIMIT,
            },
        }

    def manual_pose(
        self,
        yaw: float = 0.0,
        pitch: float = 0.0,
        roll: float = 0.0,
        z: float = 0.0,
        body_yaw: float | None = None,
        antennas: tuple[float, float] | None = None,
        duration_s: float = 0.4,
    ) -> None:
        """The controller's full target (radians / metres); only honoured while held."""
        if self.motion is not None:
            self.motion.pose(
                LookTarget(
                    clamp(yaw, -YAW_LIMIT, YAW_LIMIT),
                    clamp(pitch, -PITCH_LIMIT, PITCH_LIMIT),
                    clamp(roll, -ROLL_LIMIT, ROLL_LIMIT),
                    max(0.1, duration_s),
                    clamp(z, -Z_LIMIT, Z_LIMIT),
                ),
                antennas,
                body_yaw,
            )

    # ------------------------------------------------------------------- audio

    def subscribe_audio(self) -> queue.Queue[FloatArray] | None:
        """Queue of captured mono chunks, or None when audio is off."""
        return self.pump.subscribe() if self.pump is not None else None

    def unsubscribe_audio(self, q: queue.Queue[FloatArray]) -> None:
        """Release a capture queue."""
        if self.pump is not None:
            self.pump.unsubscribe(q)

    def subscribe_speaker(self) -> queue.Queue[FloatArray] | None:
        """Queue of frames pushed to the speaker (after ducking), or None when audio is off."""
        return self.player.subscribe() if self.player is not None else None

    def unsubscribe_speaker(self, q: queue.Queue[FloatArray]) -> None:
        """Release a speaker tap."""
        if self.player is not None:
            self.player.unsubscribe(q)

    def speak(self, audio: AudioClip | FloatArray | bytes) -> None:
        """Queue audio for the speaker."""
        if self.player is not None:
            self.player.speak(audio)

    def begin_speech_turn(self) -> None:
        """Reset the per-turn first-push mark."""
        if self.player is not None:
            self.player.begin_turn()

    def speech_turn_first_push(self) -> float | None:
        """Monotonic time the first frame of the current turn reached the backend."""
        return self.player.turn_first_push_at if self.player is not None else None

    def duck(self, db: float = -12.0) -> None:
        """Lower playback (stage one of barge-in)."""
        if self.player is not None:
            self.player.set_gain_db(db)

    def unduck(self) -> None:
        """Restore playback gain."""
        if self.player is not None:
            self.player.set_gain_db(0.0)

    def stop_speaking(self) -> None:
        """Flush playback (hard stop)."""
        if self.player is not None:
            self.player.flush()

    def is_speaking(self) -> bool:
        """Whether audio is queued or still audible."""
        return self.player is not None and self.player.is_playing()

    def speaking_remaining_s(self) -> float:
        """Seconds of audio left."""
        return self.player.remaining_seconds() if self.player is not None else 0.0

    def wait_quiet(self, timeout: float | None = None) -> bool:
        """Block until the speaker is idle."""
        return self.player.wait_idle(timeout) if self.player is not None else True

    def input_level_dbfs(self) -> float:
        """Last captured chunk level."""
        return self.pump.level_dbfs if self.pump is not None else -100.0
