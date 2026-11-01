"""sidekick.dashboard.robot — the Robot tab's back end: take the body over and test each capability

Overview
    `RobotControl` is what the `/api/robot/*` routes call. `take()` parks the voice front end
    (`InteractionSession.hold`), switches daemon-side face tracking off and hands the motion
    owner to the dashboard (`BodySession.take_control`); while held, `pose()` drives head,
    height, body yaw and antennas, `gesture()` / `express()` go through the
    manual path, and the capability tests run: microphone capture to WAV with peak / RMS,
    speaker tone / sweep / replay of the last capture, a camera snapshot to JPEG, and a short
    video clip (H.264 through `record.VideoWriter` plus a mic WAV). `release()` gives everything
    back and the idle posture returns.
Design
    No business logic in `api.py`: one method per route. Blocking work (collecting audio,
    pushing frames into GStreamer, waiting for the speaker) runs in a worker thread through
    `asyncio.to_thread`; a lock keeps it to one test at a time (the route answers 409 when
    busy). Test files live in `.derived_data/cache/robot/` under names
    `<kind>-<YYYYMMDD>-<HHMMSS>.<ext>`; only names of that shape are served, and the directory
    is pruned to the newest `KEEP_FILES`. Motion requires the hold (409 otherwise) so a slider
    cannot fight the attention logic; the tests do not, because listening to the room or
    playing a tone is harmless while the robot runs normally.
Depends on
    sidekick.log, sidekick.audio, sidekick.body, sidekick.record, numpy, opencv (lazy).

See Also
--------
    AGENTS.md "Dashboard and CLI", PLAN.md block "[2026-10-26 #28]".

"""

from __future__ import annotations

import asyncio
import math
import queue
import re
import time
from pathlib import Path
from typing import Any

import numpy as np

from sidekick.audio import AudioClip, decode_wav, encode_wav, tone
from sidekick.body import FloatArray, Gesture
from sidekick.log import Log
from sidekick.record import VideoWriter, WavTrack, encoder_name

SAMPLE_RATE = 16000
KEEP_FILES = 20
MAX_SECONDS = 30.0
FILE_NAME = re.compile(r"^(mic|speaker|snapshot|video|video_mic)-\d{8}-\d{6}\.(wav|jpg|mp4)$")
MEDIA_TYPES = {"wav": "audio/wav", "jpg": "image/jpeg", "mp4": "video/mp4"}


def _dbfs(value: float) -> float:
    return round(20.0 * math.log10(value), 1) if value > 1e-6 else -100.0


def sweep(seconds: float, start: float = 100.0, stop: float = 6000.0) -> FloatArray:
    """A logarithmic sine sweep (speaker frequency check)."""
    n = max(1, int(seconds * SAMPLE_RATE))
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    k = math.log(stop / start) / max(seconds, 1e-3)
    phase = 2.0 * np.pi * start * (np.exp(k * t) - 1.0) / k
    out = (0.25 * np.sin(phase)).astype(np.float32)
    return _fade(out)


def _fade(samples: FloatArray, ms: float = 20.0) -> FloatArray:
    n = min(len(samples) // 2, int(SAMPLE_RATE * ms / 1000.0))
    if n > 0:
        ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
        samples[:n] *= ramp
        samples[-n:] *= ramp[::-1]
    return samples


class RobotControl:
    """Hold, drive and test one body from the dashboard."""

    def __init__(self, ctx: Any, cache_dir: Path) -> None:
        self.ctx = ctx
        self.dir = cache_dir / "robot"
        self._lock = asyncio.Lock()
        self.last: dict[str, dict[str, Any]] = {}
        self.holder = "dashboard"

    # ------------------------------------------------------------------ state

    def status(self) -> dict[str, Any]:
        """Hold state, limits, the last test results and the files on disk."""
        body = self.ctx.body
        control = body.control_status() if body is not None else {"held": False, "limits": {}}
        interaction = self.ctx.interaction
        return {
            **control,
            "interaction_held": interaction.held if interaction is not None else None,
            "busy": self._lock.locked(),
            "expressions": body.expression_catalog() if body is not None else [],
            "gestures": [g.value for g in Gesture],
            "last": self.last,
            "files": self.files(),
            "video_encoder": encoder_name(),
        }

    async def take(self) -> dict[str, Any]:
        """Park the front end, stop face tracking, hold the motion owner."""
        Log.info0()
        body = self.ctx.body
        if body is None:
            raise RuntimeError("no body")
        interaction = self.ctx.interaction
        if interaction is not None and interaction.started:
            await interaction.hold(self.holder)
        body.track_face(False)
        body.take_control(self.holder)
        return self.status()

    async def release(self) -> dict[str, Any]:
        """Hand the body back; the idle posture and face tracking return."""
        Log.info0()
        body = self.ctx.body
        if body is not None:
            body.release_control()
        interaction = self.ctx.interaction
        if interaction is not None:
            interaction.release_hold()
        return self.status()

    def _require_hold(self) -> Any:
        body = self.ctx.body
        if body is None:
            raise RuntimeError("no body")
        if body.controller is None:
            raise PermissionError("take control first")
        return body

    # ----------------------------------------------------------------- motion

    def pose(
        self,
        yaw: float,
        pitch: float,
        roll: float,
        z: float,
        body_yaw: float | None,
        antennas: tuple[float, float] | None,
        duration_s: float,
    ) -> dict[str, Any]:
        """Full manual target (radians / metres)."""
        body = self._require_hold()
        body.manual_pose(yaw, pitch, roll, z, body_yaw, antennas, duration_s)
        return {"ok": True}

    def gesture(self, name: str) -> dict[str, Any]:
        """One of the scripted overlays."""
        body = self._require_hold()
        body.gesture(Gesture(name), manual=True)
        return {"ok": True}

    def express(self, name: str, intensity: float = 1.0) -> dict[str, Any]:
        """One of Bobby's expressions, by hand."""
        body = self._require_hold()
        if not body.express(name, manual=True, intensity=intensity):
            raise KeyError(name)
        return {"ok": True}

    # ------------------------------------------------------------------ tests

    async def mic_test(self, seconds: float) -> dict[str, Any]:
        """Capture the microphone for `seconds` into a WAV with peak / RMS levels."""
        seconds = min(max(seconds, 0.2), MAX_SECONDS)
        async with self._busy():
            result = await asyncio.to_thread(self._capture_mic, seconds)
        self.last["mic"] = result
        return result

    def collect(self, seconds: float) -> AudioClip | None:
        """Blocking capture of `seconds` from the microphone (worker thread)."""
        body = self.ctx.body
        q = body.subscribe_audio() if body is not None else None
        if q is None:
            return None
        pieces: list[FloatArray] = []
        got = 0
        deadline = time.monotonic() + seconds + 1.0
        try:
            while got < seconds * SAMPLE_RATE and time.monotonic() < deadline:
                try:
                    chunk = q.get(timeout=0.2)
                except queue.Empty:
                    continue
                pieces.append(chunk)
                got += len(chunk)
        finally:
            body.unsubscribe_audio(q)
        if not pieces:
            return None
        return AudioClip(np.concatenate(pieces), SAMPLE_RATE)

    async def capture(self, seconds: float) -> AudioClip | None:
        """`collect()` off the loop, one capture at a time (enrollment, tests)."""
        seconds = min(max(seconds, 0.2), MAX_SECONDS)
        async with self._busy():
            return await asyncio.to_thread(self.collect, seconds)

    def _capture_mic(self, seconds: float) -> dict[str, Any]:
        clip = self.collect(seconds)
        if clip is None:
            return {"ok": False, "error": "no audio arrived (capture not running?)"}
        samples = clip.samples
        name = self._name("mic", "wav")
        (self.dir / name).write_bytes(encode_wav(AudioClip(samples, SAMPLE_RATE)))
        self._prune()
        peak = float(np.max(np.abs(samples)))
        rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
        return {
            "ok": True,
            "file": name,
            "url": f"/api/robot/file/{name}",
            "seconds": round(len(samples) / SAMPLE_RATE, 2),
            "samples": len(samples),
            "peak_dbfs": _dbfs(peak),
            "rms_dbfs": _dbfs(rms),
            "clipped": bool(peak >= 0.999),
        }

    async def speaker_test(self, kind: str, seconds: float, freq: float) -> dict[str, Any]:
        """Play a tone, a sweep or the last mic capture, and wait for it to finish."""
        seconds = min(max(seconds, 0.1), MAX_SECONDS)
        body = self.ctx.body
        if body is None:
            return {"ok": False, "error": "no body"}
        async with self._busy():
            if kind == "tone":
                samples = tone(seconds, min(max(freq, 50.0), 8000.0))
            elif kind == "sweep":
                samples = sweep(seconds)
            elif kind == "mic":
                last = self.last.get("mic")
                path = self.file_path(last["file"]) if last and last.get("ok") else None
                if path is None:
                    return {"ok": False, "error": "record the microphone first"}
                samples = decode_wav(path.read_bytes()).samples
            else:
                return {"ok": False, "error": f"unknown kind {kind!r}"}
            started = time.monotonic()
            body.begin_speech_turn()
            body.speak(samples)
            quiet = await asyncio.to_thread(body.wait_quiet, len(samples) / SAMPLE_RATE + 3.0)
            result = {
                "ok": bool(quiet),
                "kind": kind,
                "seconds": round(len(samples) / SAMPLE_RATE, 2),
                "played_in_s": round(time.monotonic() - started, 2),
                "first_push_s": None
                if body.speech_turn_first_push() is None
                else round(body.speech_turn_first_push() - started, 3),
                "error": None if quiet else "speaker did not drain in time",
            }
        self.last["speaker"] = result
        return result

    def _grab_frame(self) -> Any:
        """The SDK hands out each camera frame once; wait briefly for the next one."""
        body = self.ctx.body
        return body.frame(0.5) if body is not None else None

    def snapshot(self) -> dict[str, Any]:
        """The current camera frame as a JPEG file."""
        frame = self._grab_frame()
        if frame is None:
            return {"ok": False, "error": "no camera frame"}
        import cv2

        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            return {"ok": False, "error": "encode failed"}
        name = self._name("snapshot", "jpg")
        data = bytes(encoded.tobytes())
        (self.dir / name).write_bytes(data)
        self._prune()
        h, w = frame.shape[:2]
        result = {
            "ok": True,
            "file": name,
            "url": f"/api/robot/file/{name}",
            "width": int(w),
            "height": int(h),
            "bytes": len(data),
        }
        self.last["snapshot"] = result
        return result

    async def video_test(self, seconds: float, fps: float = 10.0) -> dict[str, Any]:
        """Record the camera (H.264) and the microphone for `seconds`."""
        seconds = min(max(seconds, 1.0), MAX_SECONDS)
        async with self._busy():
            result = await asyncio.to_thread(self._record_video, seconds, fps)
        self.last["video"] = result
        return result

    def _record_video(self, seconds: float, fps: float) -> dict[str, Any]:
        body = self.ctx.body
        frame = self._grab_frame()
        if body is None or frame is None:
            return {"ok": False, "error": "no camera frame"}
        h, w = frame.shape[:2]
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"video-{stamp}.mp4"
        mic_name = f"video_mic-{stamp}.wav"
        writer = VideoWriter(self.dir / name, int(w), int(h), fps, 2000)
        if not writer.ok:
            return {"ok": False, "error": writer.error or "video writer unavailable"}
        q = body.subscribe_audio()
        track = WavTrack(self.dir / mic_name) if q is not None else None
        period = 1.0 / fps
        started = time.monotonic()
        next_tick = started
        frames = 0
        try:
            while time.monotonic() - started < seconds:
                current = body.frame()
                if current is not None and writer.push(current):
                    frames += 1
                if q is not None and track is not None:
                    while True:
                        try:
                            track.write(q.get_nowait())
                        except queue.Empty:
                            break
                next_tick += period
                delay = next_tick - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
        finally:
            if q is not None:
                body.unsubscribe_audio(q)
            writer.close()
            if track is not None:
                track.close()
        self._prune()
        path = self.dir / name
        return {
            "ok": writer.error is None and frames > 0,
            "file": name,
            "url": f"/api/robot/file/{name}",
            "mic_file": mic_name if track is not None else None,
            "mic_url": f"/api/robot/file/{mic_name}" if track is not None else None,
            "seconds": round(time.monotonic() - started, 2),
            "frames": frames,
            "fps": fps,
            "width": int(w),
            "height": int(h),
            "encoder": writer.encoder,
            "bytes": path.stat().st_size if path.exists() else 0,
            "mic_seconds": round(track.samples / SAMPLE_RATE, 2) if track is not None else None,
            "error": writer.error,
        }

    # ------------------------------------------------------------------ files

    def files(self) -> list[dict[str, Any]]:
        """Test files on disk, newest first."""
        if not self.dir.is_dir():
            return []
        names = sorted(
            (p.name for p in self.dir.iterdir() if FILE_NAME.match(p.name)), reverse=True
        )
        rows: list[dict[str, Any]] = []
        for name in names:
            stat = (self.dir / name).stat()
            rows.append(
                {
                    "name": name,
                    "url": f"/api/robot/file/{name}",
                    "bytes": stat.st_size,
                    "ts": round(stat.st_mtime, 1),
                }
            )
        return rows

    def file_path(self, name: str) -> Path | None:
        """A test file by its (allowlisted) name."""
        if not FILE_NAME.match(name):
            return None
        path = self.dir / name
        return path if path.is_file() else None

    @staticmethod
    def media_type(name: str) -> str:
        """Content type from the extension."""
        return MEDIA_TYPES.get(name.rsplit(".", 1)[-1], "application/octet-stream")

    def _name(self, kind: str, ext: str) -> str:
        self.dir.mkdir(parents=True, exist_ok=True)
        return f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}.{ext}"

    def _prune(self) -> None:
        rows = self.files()
        for row in rows[KEEP_FILES:]:
            try:
                (self.dir / row["name"]).unlink()
            except OSError:
                pass

    def _busy(self) -> _Busy:
        return _Busy(self._lock)


class _Busy:
    """`async with` guard that refuses instead of queueing when a test is running."""

    def __init__(self, lock: asyncio.Lock) -> None:
        self.lock = lock

    async def __aenter__(self) -> None:
        if self.lock.locked():
            raise BlockingIOError("another test is running")
        await self.lock.acquire()

    async def __aexit__(self, *exc: object) -> None:
        self.lock.release()
