"""sidekick.body.media — capture fan-out and paced, duckable playback on top of a body backend

Overview
    `AudioPump` pulls mono 16 kHz chunks from the backend on its own thread and copies them into
    every subscriber queue (VAD / name spotting, engagement clips, dashboard meter). `AudioPlayer`
    owns the speaker: it queues PCM, pushes it in 20 ms frames while staying only ~250 ms ahead
    of real time, applies a live gain (ducking) at push time, and can flush everything for a
    hard stop. Both expose timing marks used for latency measurements.
Design
    Pacing is the key design point: GStreamer would happily buffer seconds of audio, which
    would make ducking and stopping lag by that much. Keeping the lead small bounds the
    reaction time of invariant 20 to ~250 ms plus the sink latency. Subscriber queues are
    bounded and drop the oldest chunk when a consumer stalls, so a slow consumer never blocks
    capture. Frames are not pumped here: camera consumers poll `frame()` at their own rate.
Depends on
    sidekick.log, sidekick.audio, numpy.

See Also
--------
    AGENTS.md "Interaction" (two-stage barge-in), PLAN.md block "[2026-10-26 #12]".

"""

from __future__ import annotations

import collections
import math
import queue
import threading
import time
from typing import Any

import numpy as np

from sidekick.audio import AudioClip, int16_to_float
from sidekick.log import Log

from .schemas import BodyBackend, FloatArray

SAMPLE_RATE = 16000
FRAME = 320  # 20 ms
PEAK_HISTORY = 400  # 8 s of per-chunk peaks for the dashboard waveform strips


class AudioPump(threading.Thread):
    """Capture thread with subscriber fan-out."""

    def __init__(self, backend: BodyBackend, max_queue: int = 250) -> None:
        super().__init__(name="sidekick-audio-in", daemon=True)
        self.backend = backend
        self.max_queue = max_queue
        self._subscribers: list[queue.Queue[FloatArray]] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self.chunks = 0
        self.samples = 0
        self.level_dbfs = -100.0
        self.peaks: collections.deque[float] = collections.deque(maxlen=PEAK_HISTORY)

    def subscribe(self) -> queue.Queue[FloatArray]:
        """A new bounded queue receiving every chunk from now on."""
        q: queue.Queue[FloatArray] = queue.Queue(maxsize=self.max_queue)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[FloatArray]) -> None:
        """Stop delivering to a queue."""
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def stop(self) -> None:
        """Ask the thread to exit."""
        self._stop_event.set()

    def run(self) -> None:
        """Pull and fan out until stopped."""
        Log.info0()
        idle = 0
        while not self._stop_event.is_set():
            chunk = self.backend.read_audio()
            if chunk is None or len(chunk) == 0:
                idle += 1
                time.sleep(0.005 if idle < 200 else 0.02)
                continue
            idle = 0
            self.chunks += 1
            self.samples += len(chunk)
            rms = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64)))) if len(chunk) else 0.0
            self.level_dbfs = 20.0 * math.log10(rms) if rms > 1e-9 else -100.0
            self.peaks.append(float(np.max(np.abs(chunk))))
            with self._lock:
                targets = list(self._subscribers)
            for q in targets:
                try:
                    q.put_nowait(chunk)
                except queue.Full:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        q.put_nowait(chunk)
                    except queue.Full:
                        pass
        Log.info("audio pump stopped")


class AudioPlayer(threading.Thread):
    """Speaker thread: paced pushes, live gain, flush."""

    def __init__(self, backend: BodyBackend, lead_s: float = 0.25) -> None:
        super().__init__(name="sidekick-audio-out", daemon=True)
        self.backend = backend
        self.lead_s = lead_s
        self._pending: collections.deque[FloatArray] = collections.deque()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop_event = threading.Event()
        self._gain = 1.0
        self._scheduled_end = 0.0
        self._generation = 0
        self._active = False
        self.first_push_at: float | None = None
        self.last_push_at: float | None = None
        self.turn_first_push_at: float | None = None
        self.pushed_samples = 0
        self.level_dbfs = -100.0
        self.peaks: collections.deque[float] = collections.deque(maxlen=PEAK_HISTORY)
        self._taps: list[queue.Queue[FloatArray]] = []
        self.max_queue = 250
        self.sway: Any = None  # `SpeechSway`: fed every pushed frame with its playback instant

    # ------------------------------------------------------------------- api

    def subscribe(self) -> queue.Queue[FloatArray]:
        """A bounded queue receiving every frame pushed to the speaker (after the gain)."""
        q: queue.Queue[FloatArray] = queue.Queue(maxsize=self.max_queue)
        with self._lock:
            self._taps.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[FloatArray]) -> None:
        """Stop delivering to a tap."""
        with self._lock:
            if q in self._taps:
                self._taps.remove(q)

    def speak(self, audio: AudioClip | FloatArray | bytes) -> None:
        """Queue audio (clip, float32 array, or raw PCM16 bytes)."""
        if isinstance(audio, AudioClip):
            samples = audio.samples
        elif isinstance(audio, bytes | bytearray):
            samples = int16_to_float(np.frombuffer(audio, dtype="<i2"))
        else:
            samples = np.asarray(audio, dtype=np.float32)
        if len(samples) == 0:
            return
        with self._lock:
            self._pending.append(samples.astype(np.float32, copy=False))
        self._wake.set()

    def begin_turn(self) -> None:
        """Reset the per-turn first-push mark (latency measurement)."""
        with self._lock:
            self.turn_first_push_at = None

    def set_gain_db(self, db: float) -> None:
        """Live playback gain; 0 dB restores, −12 dB ducks."""
        self._gain = float(10.0 ** (db / 20.0))

    @property
    def gain_db(self) -> float:
        """Current gain in dB."""
        return 20.0 * math.log10(self._gain) if self._gain > 0 else -100.0

    def flush(self) -> None:
        """Drop everything queued here and in the backend (hard stop)."""
        with self._lock:
            self._pending.clear()
            self._generation += 1
            self._scheduled_end = 0.0
        self.backend.clear_audio()
        if self.sway is not None:
            self.sway.reset()

    def queued_seconds(self) -> float:
        """Audio not yet pushed to the backend."""
        with self._lock:
            return sum(len(s) for s in self._pending) / SAMPLE_RATE

    def is_playing(self) -> bool:
        """Whether anything is queued, being pushed, or scheduled to still be audible."""
        with self._lock:
            if self._pending or self._active:
                return True
        return time.monotonic() < self._scheduled_end

    def remaining_seconds(self) -> float:
        """Seconds until the speaker goes quiet if nothing else is queued."""
        return max(0.0, self._scheduled_end - time.monotonic()) + self.queued_seconds()

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Block until playback is over (or timeout)."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.is_playing():
            if deadline is not None and time.monotonic() > deadline:
                return False
            time.sleep(0.02)
        return True

    def stop(self) -> None:
        """Ask the thread to exit."""
        self._stop_event.set()
        self._wake.set()

    # ------------------------------------------------------------------ loop

    def run(self) -> None:
        """Push 20 ms frames while staying `lead_s` ahead of real time."""
        Log.info0()
        while not self._stop_event.is_set():
            with self._lock:
                if not self._pending:
                    chunk = None
                    generation = self._generation
                else:
                    chunk = self._pending.popleft()
                    generation = self._generation
                    self._active = True
            if chunk is None:
                self._wake.wait(0.05)
                self._wake.clear()
                continue
            self._push_chunk(chunk, generation)
            with self._lock:
                self._active = False
        Log.info("audio player stopped")

    def _push_chunk(self, chunk: FloatArray, generation: int) -> None:
        for start in range(0, len(chunk), FRAME):
            if self._stop_event.is_set():
                break
            with self._lock:
                if generation != self._generation:
                    break
            frame = chunk[start : start + FRAME]
            now = time.monotonic()
            if self._scheduled_end < now:
                self._scheduled_end = now
            ahead = self._scheduled_end - now
            if ahead > self.lead_s:
                time.sleep(ahead - self.lead_s)
            out = frame * self._gain if self._gain != 1.0 else frame
            self.backend.push_audio(out)
            self._observe(out)
            if self.sway is not None:
                self.sway.feed(out, self._scheduled_end)  # heard at the scheduled start
            self._scheduled_end += len(frame) / SAMPLE_RATE
            self.pushed_samples += len(frame)
            self.last_push_at = time.monotonic()
            if self.first_push_at is None:
                self.first_push_at = self.last_push_at
            if self.turn_first_push_at is None:
                self.turn_first_push_at = self.last_push_at

    def _observe(self, frame: FloatArray) -> None:
        """Level, peak ring and tap fan-out for what just went to the speaker."""
        if len(frame) == 0:
            return
        rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float64))))
        self.level_dbfs = 20.0 * math.log10(rms) if rms > 1e-9 else -100.0
        self.peaks.append(float(np.max(np.abs(frame))))
        with self._lock:
            taps = list(self._taps)
        for q in taps:
            try:
                q.put_nowait(frame)
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(frame)
                except queue.Full:
                    pass
