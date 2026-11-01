"""sidekick.body.reachy — Reachy Mini adapter over the `reachy_mini` SDK and the daemon's REST API

Overview
    Implements `BodyBackend` for a real or simulated Reachy Mini whose daemon is reachable at
    `host:port`. Motion, media and tracking go through `reachy_mini.ReachyMini`; status and DoA
    use the daemon's HTTP API because those endpoints are cheap, documented and never block on
    a WebSocket broadcast.
Design
    `reachy_mini` and GStreamer are imported lazily in `connect()` so importing sidekick never
    pays the ~30 s first-run GStreamer registry scan or requires a robot. The SDK's
    `set_target` is called only by the motion owner thread (invariant 10); this class does no
    pacing or arbitration of its own. Audio capture and playback share one GStreamer pipeline
    in the SDK, so the pipeline is started once and stopped only on `stop_audio()`; a hard stop
    flushes queued playback with `clear_player()` instead of pausing the pipeline. Expressions
    are ours (`expression.py`, played by the motion owner through `set_target`); the SDK's
    recorded-move library and `play_move()` are not used any more — they blocked the motion
    thread and played a sound effect over Bobby's voice (blocks #46, #50). Provider-style failures (daemon gone,
    connection lost) are logged and reflected in `status()`, never raised to the owner loop.
Depends on
    sidekick.log, numpy, httpx, reachy_mini (lazy).

See Also
--------
    AGENTS.md "Body", PLAN.md block "[2026-10-26 #12]" (SDK research).

"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx
import numpy as np
import numpy.typing as npt

from sidekick.log import Log

from .schemas import INIT_ANTENNAS, BodyDoA, BodyFace, BodyState, BodyStatus, FloatArray, Pose

MOTOR_TO_STATE = {
    "enabled": BodyState.AWAKE,
    "disabled": BodyState.ASLEEP,
    "gravity_compensation": BodyState.GRAVITY,
}


@dataclass(frozen=True, slots=True)
class BodyReachyConfiguration:
    """Where the daemon is and how media is attached."""

    host: str = "localhost"
    port: int = 8000
    media_backend: str = "default"
    connect_timeout_s: float = 10.0
    http_timeout_s: float = 2.0

    @property
    def base_url(self) -> str:
        """HTTP root of the daemon."""
        return f"http://{self.host}:{self.port}"

    @property
    def local(self) -> bool:
        """Daemon on this machine (Lite) versus on the robot (Wireless)."""
        return self.host in ("localhost", "127.0.0.1", "::1")


def status_from_payload(payload: dict[str, Any] | None, error: str | None = None) -> BodyStatus:
    """Map `GET /api/daemon/status` into a `BodyStatus`."""
    if payload is None:
        return BodyStatus(BodyState.DISCONNECTED, error=error)
    backend = payload.get("backend_status") or {}
    motor = backend.get("motor_control_mode") if isinstance(backend, dict) else None
    daemon_state = str(payload.get("state", "unknown"))
    if daemon_state == "error":
        state = BodyState.ERROR
    elif daemon_state != "running" or motor is None:
        state = (
            BodyState.DISCONNECTED if daemon_state in ("stopped", "unknown") else BodyState.ASLEEP
        )
    else:
        state = MOTOR_TO_STATE.get(str(motor), BodyState.ERROR)
    return BodyStatus(
        state=state,
        daemon_state=daemon_state,
        motor_mode=str(motor) if motor is not None else None,
        robot_name=payload.get("robot_name"),
        version=payload.get("version"),
        media=not bool(payload.get("no_media", False)),
        simulated=bool(payload.get("simulation_enabled") or payload.get("mockup_sim_enabled")),
        error=payload.get("error") or error,
    )


def face_from_payload(payload: dict[str, Any] | None) -> BodyFace:
    """Map the daemon's `face_target` into a `BodyFace`."""
    if not payload:
        return BodyFace(False)
    return BodyFace(
        detected=bool(payload.get("detected", False)),
        x=payload.get("x"),
        y=payload.get("y"),
        roll=payload.get("roll"),
        ts=payload.get("ts"),
    )


class BodyReachyBackend:
    """`BodyBackend` for Reachy Mini (Lite, Wireless, `--sim`, `--mockup-sim`)."""

    name = "reachy"

    def __init__(self, configuration: BodyReachyConfiguration = BodyReachyConfiguration()) -> None:
        self.configuration = configuration
        self._mini: Any = None
        self._http = self._client()
        self._last_status = BodyStatus(BodyState.DISCONNECTED)
        self._last_face = BodyFace(False)
        self._audio_started = False
        self._failures = 0

    # ----------------------------------------------------------------- lifecycle

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.configuration.base_url, timeout=self.configuration.http_timeout_s
        )

    def connect(self) -> BodyStatus:
        """Connect the SDK client; the daemon must already be running.

        `close()` closes the REST client, so a connect after it (the service started again,
        block #87) opens a new one.
        """
        Log.info0(f"connect {self.configuration.base_url} media={self.configuration.media_backend}")
        if self._http.is_closed:
            self._http = self._client()
        status = self.status()
        if not status.connected:
            Log.warning(f"daemon not reachable at {self.configuration.base_url}: {status.error}")
            return status
        from reachy_mini import ReachyMini

        mode = "localhost_only" if self.configuration.local else "network"
        self._mini = ReachyMini(
            host=self.configuration.host,
            port=self.configuration.port,
            connection_mode=mode,
            media_backend=self.configuration.media_backend,
            timeout=self.configuration.connect_timeout_s,
            log_level="WARNING",
        )
        self._failures = 0
        Log.info(f"connected to {status.robot_name} v{status.version} state={status.state.value}")
        return status

    def close(self) -> None:
        """Stop media and disconnect."""
        Log.info0()
        mini, self._mini = self._mini, None
        if mini is not None:
            try:
                self.stop_audio_of(mini)
                mini.media_manager.close()
                mini.client.disconnect()
            except Exception as exc:  # pragma: no cover - teardown best effort
                Log.warning(f"close: {exc!r}")
        self._http.close()

    def stop_audio_of(self, mini: Any) -> None:
        """Stop the media pipelines of a client (used by `close`)."""
        if self._audio_started:
            try:
                mini.media.stop_recording()
                mini.media.stop_playing()
            except Exception as exc:  # pragma: no cover
                Log.warning(f"stop_audio: {exc!r}")
            self._audio_started = False

    def set_volume(self, volume: int) -> bool:
        """Speaker volume 0–100 through the daemon."""
        try:
            response = self._http.post("/api/volume/set", json={"volume": int(volume)})
        except httpx.HTTPError as exc:
            Log.warning(f"set_volume: {type(exc).__name__}")
            return False
        ok = response.status_code == 200
        Log.info(f"speaker volume -> {volume} ({'ok' if ok else response.status_code})")
        return ok

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any | None:
        try:
            response = self._http.get(path, params=params)
        except httpx.HTTPError as exc:
            self._failures += 1
            if self._failures in (1, 10, 100):
                Log.warning(f"GET {path}: {type(exc).__name__}")
            return None
        if response.status_code != 200:
            return None
        self._failures = 0
        return response.json()

    # ------------------------------------------------------------------- status

    def status(self) -> BodyStatus:
        """Poll `GET /api/daemon/status`; also refreshes the cached face target."""
        payload = self._get_json("/api/daemon/status")
        if payload is None:
            self._last_status = BodyStatus(BodyState.DISCONNECTED, error="daemon unreachable")
            return self._last_status
        self._last_status = status_from_payload(payload)
        self._last_face = face_from_payload(payload.get("face_target"))
        return self._last_status

    # ------------------------------------------------------------------- motion

    def set_target(
        self, head: Pose | None, antennas: Sequence[float] | None, body_yaw: float | None
    ) -> None:
        """Forward an immediate target to the daemon."""
        if self._mini is None:
            return
        try:
            self._mini.set_target(
                head=head,
                antennas=list(antennas) if antennas is not None else None,
                body_yaw=body_yaw,
            )
        except Exception as exc:
            self._note_motion_failure("set_target", exc)

    def goto(self, head: Pose | None, antennas: Sequence[float] | None, duration_s: float) -> None:
        """Interpolated move; blocks until the daemon reports completion."""
        if self._mini is None:
            return
        try:
            self._mini.goto_target(
                head=head,
                antennas=list(antennas) if antennas is not None else None,
                duration=max(0.05, duration_s),
                body_yaw=None,
            )
        except Exception as exc:
            self._note_motion_failure("goto", exc)

    def _note_motion_failure(self, what: str, exc: Exception) -> None:
        self._failures += 1
        if self._failures in (1, 50, 500):
            Log.warning(f"{what}: {exc!r}")

    def present_antennas(self) -> tuple[float, float] | None:
        """Measured antenna angles (right, left) from the SDK's state stream."""
        if self._mini is None:
            return None
        try:
            right, left = self._mini.get_present_antenna_joint_positions()
        except Exception:
            return None
        return float(right), float(left)

    def present_head_pose(self) -> Pose | None:
        """Measured head pose from the SDK's state stream (cached client-side, free to read)."""
        if self._mini is None:
            return None
        try:
            return np.asarray(self._mini.get_current_head_pose(), dtype=np.float64)
        except Exception:
            return None

    def present_joints(self) -> tuple[list[float], list[float]] | None:
        """Measured head and antenna joints from the SDK's state stream."""
        if self._mini is None:
            return None
        try:
            head, antennas = self._mini.get_current_joint_positions()
        except Exception:
            return None
        return [float(v) for v in head], [float(v) for v in antennas]

    # ------------------------------------------------------------------ tracking

    def track_face(self, enabled: bool, weight: float = 1.0) -> None:
        """Daemon-side face tracking."""
        if self._mini is None:
            return
        try:
            if enabled:
                self._mini.start_head_tracking(weight=float(weight))
            else:
                self._mini.stop_head_tracking()
        except Exception as exc:
            Log.warning(f"track_face: {exc!r}")

    def tracked_face(self) -> BodyFace:
        """Face target from the last status poll."""
        return self._last_face

    def doa(self) -> BodyDoA | None:
        """`GET /api/state/doa`; the daemon starts polling the array on first request."""
        payload = self._get_json("/api/state/doa")
        if not isinstance(payload, dict):
            return None
        try:
            return BodyDoA(float(payload["angle"]), bool(payload["speech_detected"]))
        except (KeyError, TypeError, ValueError):
            return None

    # -------------------------------------------------------------------- audio

    def start_audio(self) -> None:
        """Start the shared capture/playback pipeline."""
        if self._mini is None or self._audio_started:
            return
        media = self._mini.media
        media.start_recording()
        media.start_playing()
        self._audio_started = True
        Log.info(
            f"audio started: in {media.get_input_audio_samplerate()} Hz x{media.get_input_channels()}, out {media.get_output_audio_samplerate()} Hz x{media.get_output_channels()}"
        )

    def read_audio(self) -> FloatArray | None:
        """Next captured chunk mixed to mono."""
        if self._mini is None or not self._audio_started:
            return None
        sample = self._mini.media.get_audio_sample()
        if sample is None:
            return None
        arr = np.asarray(sample, dtype=np.float32)
        if arr.ndim == 2:
            arr = arr.mean(axis=1)
        return arr.astype(np.float32, copy=False)

    def push_audio(self, samples: FloatArray) -> None:
        """Queue mono samples for the speaker (the SDK duplicates to stereo)."""
        if self._mini is None or not self._audio_started:
            return
        self._mini.media.push_audio_sample(np.ascontiguousarray(samples, dtype=np.float32))

    def clear_audio(self) -> None:
        """Flush queued playback without stopping capture."""
        if self._mini is None or not self._audio_started:
            return
        audio = getattr(self._mini.media, "audio", None)
        clear = getattr(audio, "clear_player", None)
        if callable(clear):
            try:
                clear()
            except Exception as exc:  # pragma: no cover
                Log.warning(f"clear_audio: {exc!r}")

    def stop_audio(self) -> None:
        """Stop capture and playback."""
        if self._mini is not None:
            self.stop_audio_of(self._mini)

    def frame(self) -> npt.NDArray[np.uint8] | None:
        """Latest BGR frame from the daemon's IPC endpoint."""
        if self._mini is None:
            return None
        try:
            frame = self._mini.media.get_frame()
        except Exception:
            return None
        return None if frame is None else np.asarray(frame, dtype=np.uint8)

    def camera_matrix(self) -> tuple[npt.NDArray[np.float64], int, int] | None:
        """The SDK camera's intrinsics rescaled to the streamed resolution."""
        if self._mini is None:
            return None
        try:
            camera = self._mini.media.camera
            matrix = camera.K if camera is not None else None
            if matrix is None:
                return None
            width, height = camera.resolution
            return np.asarray(matrix, dtype=np.float64), int(width), int(height)
        except Exception:
            return None

    def set_wobbling(self, enabled: bool) -> None:
        """Audio-reactive head wobble (SDK + daemon side)."""
        if self._mini is None:
            return
        try:
            if enabled:
                self._mini.enable_wobbling()
            else:
                self._mini.disable_wobbling()
        except Exception as exc:
            Log.warning(f"set_wobbling: {exc!r}")

    @staticmethod
    def init_antennas() -> tuple[float, float]:
        """Neutral antenna pose used by the motion owner."""
        return INIT_ANTENNAS
