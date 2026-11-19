"""sidekick.record.record — RecordSession: the 24 h ring of video, audio and telemetry chunks

Overview
    `RecordSession.shared` records everything the body sees, hears and says into 5-minute chunk
    directories under the recordings root (`YYYY-MM-DD/HH-MM-SS/`): `video.mp4` (H.264 from the
    camera at a reduced size and rate), `mic.wav`, `speaker.wav` (PCM pushed to the speaker,
    silence-padded so it stays on the wall clock), `telemetry.jsonl` (10 Hz: commanded and
    measured pose, joints, antennas, levels, speaking / ducking, DoA, face, plus whatever the
    injected `extra()` callable adds — the interaction state and captions in `app.py`), and
    `chunk.json`. Old chunks are pruned by retention and the recorder pauses below a free-disk
    floor instead of filling the volume. The Replay tab and the Record page read the same
    directories through `days()`, `chunks()`, `chunk()` and `chunk_file()`.
Design
    One daemon thread (`_run`) does all the work with blocking calls — the SDK frame grab, the
    GStreamer push and file writes — so nothing touches the asyncio loop; `start()` / `stop()`
    are synchronous and cheap. Audio arrives through the body's fan-out queues (mic pump and
    speaker tap) and is drained on every telemetry tick, so a slow disk drops the oldest audio
    chunk in the bounded queue instead of stalling capture. Chunks roll on the clock, not on
    frame counts, and the descriptor is written at open (`open: true`) and at close, so a crash
    leaves a readable, prunable chunk. Dependency direction: `record` imports `log`, `storage`,
    `audio`, `body` only; interaction state comes in through the `extra` callable (rule 1), and
    `mic_reader()` hands interaction `read_mic` when the ring keeps WAV audio, so decision clips
    are sliced from it instead of copied under `audio/`.
    Each run has its own stop event (a thread left over from the last run never revives) and
    `check()` reports the ring and free disk (block #87).
Depends on
    sidekick.log, sidekick.audio, sidekick.body (duck-typed session), numpy; GStreamer lazily
    through `video.py` / `tracks.py`.

See Also
--------
    AGENTS.md "Recording", PLAN.md block "[2026-10-26 #25]".

"""

from __future__ import annotations

import gzip
import json
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

from .chunks import (
    chunk_id,
    chunk_path,
    dir_bytes,
    free_gb,
    list_chunks,
    list_days,
    prune,
    read_chunk,
    resolve,
)
from .schemas import (
    CHUNK_FILE,
    TELEMETRY_FILE,
    TELEMETRY_GZ,
    VIDEO_FILE,
    RecordChunk,
    RecordSettings,
    RecordStatus,
)
from .tracks import AudioTrack, WavTrack, open_track, repair_wav_header
from .video import VideoWriter, encoder_name

CHUNK_FILES = ("video.mp4", "mic.wav", "speaker.wav", "mic.flac", "speaker.flac")
DISK_CHECK_S = 60.0
PAUSE_RETRY_S = 60.0
DESCRIPTOR_REFRESH_S = 30.0
STATUS_TTL_S = 30.0  # the chunk walk behind the totals runs at most this often for live views


__all__ = ["RecordSession", "VideoWriter", "WavTrack", "encoder_name"]


class RecordSession:
    """Façade: start / stop the recorder, read chunks."""

    shared: ClassVar[RecordSession]

    def __init__(self) -> None:
        self.settings: RecordSettings | None = None
        self.body: Any = None
        self.extra: Callable[[], dict[str, Any]] | None = None
        self.state = "off"
        self.current: RecordChunk | None = None
        self.last_error: str | None = None
        self.frames_total = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # `status()` walks every chunk directory: the health poll and the Live page read this
        # copy instead, refreshed at most every STATUS_TTL_S (by a worker thread for `live()`).
        self._status: tuple[float, RecordStatus] | None = None
        self._status_lock = threading.Lock()
        self._refreshing = False

    # ------------------------------------------------------------------- setup

    def setup(
        self,
        settings: RecordSettings,
        body: Any,
        extra: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        """Bind the settings, the body session and the telemetry extra callable."""
        self.settings = settings
        self.body = body
        self.extra = extra

    def start(self) -> None:
        """Start the recorder thread (no-op when disabled or without a connected body)."""
        if self.settings is None or not self.settings.enabled:
            self.state = "off"
            return
        if self.body is None or not getattr(self.body, "connected", True):
            self.state = "off"
            Log.warning("recording off: no body connection")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        Log.info0(
            f"root={self.settings.root} chunk={self.settings.chunk_s:.0f}s "
            f"{self.settings.width}x{self.settings.height}@{self.settings.fps:g}fps "
            f"{self.settings.bitrate_kbps}kbps audio={self.settings.audio_codec} "
            f"retention={self.settings.retention_hours:g}h floor={self.settings.min_free_gb:g}GB"
        )
        self.settings.root.mkdir(parents=True, exist_ok=True)
        self._repair_open_chunks()
        stop = threading.Event()  # this run's: a thread left from the last run keeps its own
        self._stop = stop
        self.state = "starting"
        self._thread = threading.Thread(
            target=self._run, args=(stop,), name="sidekick-record", daemon=True
        )
        self._thread.start()

    def stop(self, timeout_s: float = 15.0) -> None:
        """Close the current chunk and stop the thread."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout_s)
        self._thread = None
        if self.state != "off":
            self.state = "stopped"

    def check(self) -> list[dict[str, Any]]:
        """Readiness items: recording (advice only: Banana talks without it) and free disk."""
        if self.settings is None or not self.settings.enabled:
            return [{"id": "ring", "title": "recording", "level": "off", "detail": "off"}]
        status = self.cached_status()  # the disk figures; the state is the live one
        alive = self._thread is not None and self._thread.is_alive()
        state = self.state if alive or self.state != "starting" else "not started"
        errors = getattr(status, "errors", None)
        detail = state + (f" · {errors}" if errors else "")
        if state == "paused":
            detail += f" · below {status.min_free_gb:g} GB free"
        else:
            detail += f" · {status.free_gb:.0f} GB free"
        level = "ok" if alive and state != "paused" and not errors else "warn"
        return [{"id": "ring", "title": "recording", "level": level, "detail": detail}]

    # ------------------------------------------------------------------ reading

    def cached_status(self, max_age_s: float = STATUS_TTL_S) -> RecordStatus:
        """`status()` at most every `max_age_s` (the dashboard's 1 Hz health poll)."""
        cached = self._status
        if cached is None or time.monotonic() - cached[0] > max_age_s:
            return self.status()
        return cached[1]

    def live(self) -> dict[str, Any]:
        """Vital signs for the Live page: live counters plus the cached totals.

        The chunk walk never runs on the caller's thread: a stale copy is refreshed by a worker.
        """
        cached = self._status
        if (cached is None or time.monotonic() - cached[0] > STATUS_TTL_S) and not self._refreshing:
            self._refreshing = True
            threading.Thread(target=self._refresh_status, name="record-status", daemon=True).start()
        totals = cached[1] if cached is not None else None
        chunk = self.current
        return {
            "state": self.state,
            "chunk": chunk.id if chunk is not None else None,
            "chunk_age_s": round(time.time() - chunk.start_ts) if chunk is not None else None,
            "frames": self.frames_total,
            "error": self.last_error,
            "hours": round(totals.hours, 2) if totals is not None else None,
            "size_gb": round(totals.size_gb, 2) if totals is not None else None,
            "free_gb": round(totals.free_gb, 1) if totals is not None else None,
            "min_free_gb": totals.min_free_gb if totals is not None else None,
            "retention_hours": totals.retention_hours if totals is not None else None,
        }

    def _refresh_status(self) -> None:
        try:
            self.status()
        except Exception as exc:
            Log.debug(f"record status: {exc!r}")
        finally:
            self._refreshing = False

    def status(self) -> RecordStatus:
        """Health-card summary (works without a running recorder, e.g. from the CLI)."""
        settings = self.settings
        root = settings.root if settings is not None else Path(".")
        chunks = list_chunks(root) if settings is not None else []
        size = sum(c.bytes for c in chunks)
        hours = sum(c.duration_s for c in chunks) / 3600.0
        status = RecordStatus(
            state=self.state,
            root=str(root),
            chunk=self.current.id if self.current is not None else None,
            chunks=len(chunks),
            hours=hours,
            size_gb=size / 1e9,
            free_gb=free_gb(root),
            min_free_gb=settings.min_free_gb if settings is not None else 0.0,
            retention_hours=settings.retention_hours if settings is not None else 0.0,
            video=encoder_name() if settings is not None else None,
            errors=self.last_error,
            frames=self.frames_total,
        )
        with self._status_lock:
            self._status = (time.monotonic(), status)
        return status

    def days(self) -> list[str]:
        """Recorded days, oldest first."""
        return list_days(self.settings.root) if self.settings is not None else []

    def chunks(self, day: str | None = None) -> list[RecordChunk]:
        """Chunks of a day (or all), oldest first; the open chunk reflects live counters."""
        if self.settings is None:
            return []
        out = list_chunks(self.settings.root, day)
        current = self.current
        if current is not None:
            out = [current if c.id == current.id else c for c in out]
        return out

    def chunk(self, identifier: str) -> RecordChunk | None:
        """One chunk by id."""
        if self.settings is None:
            return None
        if self.current is not None and self.current.id == identifier:
            return self.current
        path = resolve(self.settings.root, identifier)
        return read_chunk(path) if path is not None else None

    def chunk_file(self, identifier: str, name: str) -> Path | None:
        """A media file of a chunk (`video.mp4`, `mic.wav`, `speaker.wav`, FLAC variants)."""
        if self.settings is None or name not in CHUNK_FILES:
            return None
        path = resolve(self.settings.root, identifier)
        if path is None:
            return None
        file = path / name
        return file if file.is_file() else None

    def mic_reader(self) -> Callable[[float, float], AudioClip | None] | None:
        """`read_mic` when the ring keeps WAV microphone audio (decision clips come from it)."""
        settings = self.settings
        if settings is None or not settings.enabled or settings.audio_codec != "wav":
            return None
        return self.read_mic

    def read_mic(self, start_ts: float, end_ts: float) -> AudioClip | None:
        """Microphone audio between two wall-clock times, sliced from the ring's WAV chunks.

        The open chunk is read as raw PCM past the 44-byte header (its header is finalised only
        at close), so a decision made seconds ago can be played back at once. FLAC chunks
        (the Pi preset) are not sliced; callers fall back to their own copy.
        """
        if self.settings is None or end_ts <= start_ts:
            return None
        rate = self.settings.sample_rate
        pieces: list[npt.NDArray[np.float32]] = []
        days = sorted({time.strftime("%Y-%m-%d", time.localtime(ts)) for ts in (start_ts, end_ts)})
        for day in days:
            for chunk in self.chunks(day):
                chunk_end = chunk.end_ts or time.time()
                if chunk_end <= start_ts or chunk.start_ts >= end_ts:
                    continue
                path = chunk.path / "mic.wav"
                if not path.is_file():
                    continue
                first = max(0, int((start_ts - chunk.start_ts) * rate))
                last = max(first, int((min(end_ts, chunk_end) - chunk.start_ts) * rate))
                with path.open("rb") as handle:
                    handle.seek(44 + first * 2)
                    data = handle.read((last - first) * 2)
                if data:
                    samples = np.frombuffer(data[: len(data) - len(data) % 2], dtype="<i2")
                    pieces.append(samples.astype(np.float32) / 32768.0)
        if not pieces:
            return None
        return AudioClip(np.concatenate(pieces), rate)

    def telemetry(self, identifier: str) -> list[dict[str, Any]]:
        """Every telemetry row of a chunk (gzip or plain), oldest first."""
        if self.settings is None:
            return []
        path = resolve(self.settings.root, identifier)
        if path is None:
            return []
        rows: list[dict[str, Any]] = []
        for candidate in (path / TELEMETRY_GZ, path / TELEMETRY_FILE):
            if not candidate.exists():
                continue
            try:
                handle: Any = (
                    gzip.open(candidate, "rt", encoding="utf-8")
                    if candidate.suffix == ".gz"
                    else candidate.open("r", encoding="utf-8")
                )
                with handle:
                    for line in handle:
                        line = line.strip()
                        if line:
                            try:
                                rows.append(json.loads(line))
                            except ValueError:
                                continue
            except OSError:
                continue
            break
        return rows

    def prune(self, now: float | None = None) -> list[RecordChunk]:
        """Apply retention and the free-disk floor; returns what was removed."""
        if self.settings is None:
            return []
        keep = self.current.id if self.current is not None else None
        removed = prune(
            self.settings.root,
            self.settings.retention_hours,
            self.settings.min_free_gb,
            now,
            keep=keep,
        )
        if removed:
            Log.info(f"pruned {len(removed)} chunk(s): {removed[0].id} .. {removed[-1].id}")
        return removed

    # -------------------------------------------------------------- the thread

    def _repair_open_chunks(self) -> None:
        """Fix WAV headers of chunks a previous process left open."""
        assert self.settings is not None
        for chunk in list_chunks(self.settings.root):
            if not chunk.open:
                continue
            for name in ("mic.wav", "speaker.wav"):
                file = chunk.path / name
                if file.exists():
                    repair_wav_header(file)
            chunk.open = False
            chunk.end_ts = chunk.end_ts or chunk.path.stat().st_mtime
            chunk.errors.append("left open by a previous run")
            self._write_descriptor(chunk)

    @staticmethod
    def _write_descriptor(chunk: RecordChunk) -> None:
        chunk.bytes = dir_bytes(chunk.path)
        (chunk.path / CHUNK_FILE).write_text(
            json.dumps(chunk.as_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
        )

    def _run(self, stop: threading.Event) -> None:
        settings = self.settings
        assert settings is not None
        body = self.body
        mic_q: queue.Queue[Any] | None = body.subscribe_audio()
        spk_q: queue.Queue[Any] | None = body.subscribe_speaker()
        Log.info(
            f"recording started (mic={'on' if mic_q else 'off'}, speaker={'on' if spk_q else 'off'}, "
            f"video={encoder_name() or 'off'})"
        )
        try:
            while not stop.is_set():
                self.prune()
                if free_gb(settings.root) < settings.min_free_gb:
                    if self.state != "paused":
                        Log.warning(
                            f"recording paused: {free_gb(settings.root):.1f} GB free < "
                            f"{settings.min_free_gb:g} GB floor"
                        )
                    self.state = "paused"
                    self._drain(mic_q)
                    self._drain(spk_q)
                    if stop.wait(PAUSE_RETRY_S):
                        break
                    continue
                self.state = "recording"
                try:
                    self._record_chunk(settings, mic_q, spk_q, stop)
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    Log.error(f"recording chunk failed: {exc!r}")
                    if stop.wait(5.0):
                        break
        finally:
            if mic_q is not None:
                body.unsubscribe_audio(mic_q)
            if spk_q is not None:
                body.unsubscribe_speaker(spk_q)
            self.current = None
            Log.info("recording stopped")

    @staticmethod
    def _drain(q: queue.Queue[Any] | None) -> list[Any]:
        out: list[Any] = []
        if q is None:
            return out
        while True:
            try:
                out.append(q.get_nowait())
            except queue.Empty:
                return out

    def _record_chunk(
        self,
        settings: RecordSettings,
        mic_q: queue.Queue[Any] | None,
        spk_q: queue.Queue[Any] | None,
        stop: threading.Event,
    ) -> None:
        body = self.body
        start_wall = time.time()
        start_mono = time.monotonic()
        path = chunk_path(settings.root, start_wall)
        path.mkdir(parents=True, exist_ok=True)
        chunk = RecordChunk(
            id=chunk_id(start_wall),
            path=path,
            start_ts=start_wall,
            audio_codec=settings.audio_codec,
            sample_rate=settings.sample_rate,
            fps=settings.fps,
            open=True,
        )
        self.current = chunk
        video: VideoWriter | None = None
        mic: AudioTrack | None = None
        speaker: AudioTrack | None = None
        telemetry = (path / TELEMETRY_FILE).open("w", encoding="utf-8")
        activity = 0.0
        try:
            video = VideoWriter(
                path / VIDEO_FILE,
                settings.width,
                settings.height,
                settings.fps,
                settings.bitrate_kbps,
            )
            if video.error:
                chunk.errors.append(f"video: {video.error}")
                video = None
            else:
                chunk.video = video.encoder
            if mic_q is not None:
                self._drain(mic_q)
                mic = open_track(path / "mic", settings.audio_codec, settings.sample_rate)
            if spk_q is not None:
                self._drain(spk_q)
                speaker = open_track(path / "speaker", settings.audio_codec, settings.sample_rate)
            self._write_descriptor(chunk)
            frame_period = 1.0 / max(0.5, settings.fps)
            tel_period = 1.0 / max(1.0, settings.telemetry_hz)
            next_frame = next_tel = time.monotonic()
            next_disk = next_tel + DISK_CHECK_S
            next_descriptor = next_tel + DESCRIPTOR_REFRESH_S
            end = start_mono + settings.chunk_s
            while not stop.is_set():
                now = time.monotonic()
                if now >= end:
                    break
                if video is not None and now >= next_frame:
                    frame = body.frame()
                    if frame is not None and video.push(frame):
                        chunk.frames += 1
                        self.frames_total += 1
                    elif video.error:
                        chunk.errors.append(f"video: {video.error}")
                        self.last_error = video.error
                        video.close()
                        video = None
                    next_frame += frame_period
                    if next_frame < now:
                        next_frame = now + frame_period
                if now >= next_tel:
                    elapsed = now - start_mono
                    if mic is not None:
                        for samples in self._drain(mic_q):
                            mic.write(np.asarray(samples, dtype=np.float32))
                        chunk.mic_samples = mic.samples
                    if speaker is not None:
                        for samples in self._drain(spk_q):
                            speaker.write(np.asarray(samples, dtype=np.float32))
                        if not body.is_speaking():
                            deficit = int(elapsed * settings.sample_rate) - speaker.samples
                            if deficit > settings.sample_rate // 5:
                                speaker.pad(deficit)
                        chunk.speaker_samples = speaker.samples
                    row = self._row(body)
                    telemetry.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                    telemetry.write("\n")
                    chunk.telemetry_rows += 1
                    if row.get("speaking") or (row.get("x") or {}).get("state") in (
                        "engaged",
                        "speaking",
                    ):
                        activity += tel_period
                    next_tel += tel_period
                    if next_tel < now:
                        next_tel = now + tel_period
                if now >= next_descriptor:
                    next_descriptor = now + DESCRIPTOR_REFRESH_S
                    self._write_descriptor(chunk)  # progress visible to the CLI / other processes
                if now >= next_disk:
                    next_disk = now + DISK_CHECK_S
                    if free_gb(settings.root) < settings.min_free_gb:
                        Log.warning("free disk below the floor; closing the chunk early")
                        break
                wake = min(next_tel, next_frame if video is not None else next_tel)
                delay = wake - time.monotonic()
                if delay > 0:
                    stop.wait(min(delay, 0.25))
        finally:
            telemetry.close()
            if video is not None:
                video.close()
                if video.error:
                    chunk.errors.append(f"video: {video.error}")
            if mic is not None:
                for samples in self._drain(mic_q):
                    mic.write(np.asarray(samples, dtype=np.float32))
                chunk.mic_samples = mic.samples
                mic.close()
            if speaker is not None:
                for samples in self._drain(spk_q):
                    speaker.write(np.asarray(samples, dtype=np.float32))
                deficit = (
                    int((time.monotonic() - start_mono) * settings.sample_rate) - speaker.samples
                )
                if deficit > 0:
                    speaker.pad(deficit)
                chunk.speaker_samples = speaker.samples
                speaker.close()
            self._compress_telemetry(path)
            chunk.end_ts = time.time()
            chunk.open = False
            chunk.activity = min(1.0, activity / max(1.0, chunk.duration_s))
            self._write_descriptor(chunk)
            self.current = None
            Log.info(
                f"chunk {chunk.id}: {chunk.frames} frames, mic {chunk.mic_samples / settings.sample_rate:.0f}s, "
                f"speaker {chunk.speaker_samples / settings.sample_rate:.0f}s, "
                f"{chunk.telemetry_rows} rows, {chunk.bytes / 1e6:.1f} MB"
                + (f", errors={chunk.errors}" if chunk.errors else "")
            )

    def _row(self, body: Any) -> dict[str, Any]:
        row: dict[str, Any] = dict(body.telemetry(peaks=0).as_dict())
        row.pop("mic_peaks", None)
        row.pop("speaker_peaks", None)
        row["t"] = row.pop("ts")
        if self.extra is not None:
            try:
                row["x"] = self.extra()
            except Exception as exc:  # the extra callable must never stop the recorder
                row["x"] = {"error": repr(exc)}
        return row

    @staticmethod
    def _compress_telemetry(path: Path) -> None:
        raw = path / TELEMETRY_FILE
        if not raw.exists():
            return
        try:
            with (
                raw.open("rb") as src,
                gzip.open(path / TELEMETRY_GZ, "wb", compresslevel=6) as dst,
            ):
                dst.write(src.read())
            raw.unlink()
        except OSError as exc:
            Log.warning(f"telemetry compression failed: {exc!r}")
