"""sidekick.interaction.frontend — the audio thread: VAD over the body's microphone stream

Overview
    Pulls captured chunks from `BodySession`, runs the `vad.primary` detector, and reports
    `speech_start` (with the direction of arrival at onset), `speech_ongoing` (every 100 ms while
    speech continues, for barge-in stage 2), `pause` (a short dip inside a sentence, for the
    listener's "mm-hm" nod) and `speech_end` (with the completed segment and the direction of
    its speech) into an asyncio queue. Also forwards antenna touches and body state changes so the façade consumes a
    single ordered event stream.
Design
    One daemon thread; the only hand-off to asyncio is `loop.call_soon_threadsafe(queue.put_nowait)`.
    Speech onset is detected from the detector's live flag so ducking happens before the segment
    is complete. Every event carries `self_motion`: for `speech_start` / `speech_ongoing` whether
    the body is inside its moving window right now, for `speech_end` whether the whole segment
    (onset to end of speech, half a second of slack) fell inside one — the façade then treats it
    as motor noise rather than the room. A `pause` is ≥ `PAUSE_S` of input 14 dB under the
    sentence's decaying peak after ≥ `PAUSE_MIN_SPEECH_S` of speech, once per dip, while the
    detector still holds the segment open. A segment's direction is
    `BodySession.doa_between(onset − SEGMENT_DOA_LEAD_S, end)`: the median of the readings taken
    while it was spoken. It used to be the one reading taken when the detector closed the
    segment — in the silence after the sentence, so mostly the room: the owner's sentences of
    2026-10-30 read −57°, 63°, 59° that way and 3°, 0°, −2° as a median (block #80). Nothing here
    leaves the host (invariant 17).
Depends on
    sidekick.log, sidekick.audio, sidekick.body, sidekick.vad, numpy.

See Also
--------
    AGENTS.md "Conventions" (audio front end in its own thread).

"""

from __future__ import annotations

import asyncio
import collections
import queue
import threading
import time
from typing import Any

import numpy as np

from sidekick.audio import AudioClip
from sidekick.body import BodySession, BodyStatus, BodyTouch, FloatArray
from sidekick.log import Log
from sidekick.vad import VADBackend, VADSegment

from .schemas import FrontEndEvent

PAUSE_S = 0.3  # a dip this long inside a sentence is a pause
PAUSE_MIN_SPEECH_S = 1.5  # ...after at least this much of the sentence
PAUSE_DROP_DB = 14.0  # under the sentence's decaying peak
PEAK_DECAY_DB_S = 6.0
SEGMENT_DOA_LEAD_S = 0.3  # the detector flags speech 0.2–0.4 s after it starts


class AudioFrontEnd(threading.Thread):
    """VAD thread feeding the façade's event queue."""

    def __init__(
        self,
        body: BodySession,
        vad: VADBackend,
        loop: asyncio.AbstractEventLoop,
        events: asyncio.Queue[FrontEndEvent],
        ongoing_period_s: float = 0.1,
        pre_roll_s: float = 0.25,
        keyword_stream: Any | None = None,
    ) -> None:
        super().__init__(name="sidekick-frontend", daemon=True)
        self.body = body
        self.vad = vad
        self.loop = loop
        self.events = events
        self.ongoing_period_s = ongoing_period_s
        self.pre_roll_s = pre_roll_s
        self.keyword_stream = keyword_stream
        self.keywords_spotted = 0
        self._ring: collections.deque[FloatArray] = collections.deque()
        self._ring_samples = 0
        self._fed_samples = 0
        self._stop_event = threading.Event()
        self._audio: queue.Queue[FloatArray] | None = None
        self.speech_onset: float | None = None
        self._onset_moving = False
        self._moving_until_seen = 0.0
        self.segments = 0
        self.chunks = 0
        self.self_motion_segments = 0
        self.pauses = 0
        self._peak_db = -100.0
        self._quiet_since: float | None = None
        self._pause_sent = False

    def emit(self, event: FrontEndEvent) -> None:
        """Thread-safe hand-off to the asyncio side."""
        self.loop.call_soon_threadsafe(self.events.put_nowait, event)

    def on_touch(self, touch: BodyTouch) -> None:
        """Body touch callback (motion thread)."""
        self.emit(FrontEndEvent("touch", time.monotonic(), side=touch.side))

    def on_body_state(self, previous: BodyStatus, current: BodyStatus) -> None:
        """Body state callback (monitor thread)."""
        self.emit(FrontEndEvent("body_state", time.monotonic(), awake=current.awake))

    def stop(self) -> None:
        """Ask the thread to exit."""
        self._stop_event.set()

    def recent_audio(self, seconds: float) -> AudioClip | None:
        """The last `seconds` of captured audio (for a quick look at speech still in progress)."""
        if not self._ring:
            return None
        want = int(seconds * self.vad.sample_rate)
        chunks: list[FloatArray] = []
        total = 0
        for chunk in reversed(self._ring):
            chunks.append(chunk)
            total += len(chunk)
            if total >= want:
                break
        samples = np.concatenate(list(reversed(chunks)))[-want:]
        return AudioClip(samples.astype(np.float32, copy=False), self.vad.sample_rate)

    def _remember(self, chunk: FloatArray) -> None:
        """Keep the last `pre_roll_s` of audio so a segment can include its onset."""
        self._fed_samples += len(chunk)
        self._ring.append(chunk)
        self._ring_samples += len(chunk)
        # A segment is reported only after the trailing silence, and it may be up to the
        # detector's max speech length, so the ring must reach back that far plus the pre-roll.
        limit = int((self.pre_roll_s + 25.0) * self.vad.sample_rate)
        while self._ring and self._ring_samples - len(self._ring[0]) > limit:
            self._ring_samples -= len(self._ring.popleft())

    def _track_pause(self, chunk: FloatArray, now: float, speaking: bool) -> None:
        """Emit `pause` for a dip inside an open sentence (the listener nods at those)."""
        if not speaking or self.speech_onset is None:
            self._peak_db, self._quiet_since, self._pause_sent = -100.0, None, False
            return
        rms = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float32)) + 1e-12))
        level = 20.0 * float(np.log10(rms + 1e-12))
        seconds = len(chunk) / float(self.vad.sample_rate)
        self._peak_db = max(level, self._peak_db - PEAK_DECAY_DB_S * seconds)
        if level >= self._peak_db - PAUSE_DROP_DB:
            self._quiet_since, self._pause_sent = None, False
            return
        if self._quiet_since is None:
            self._quiet_since = now
        elif (
            not self._pause_sent
            and now - self._quiet_since >= PAUSE_S
            and self._quiet_since - self.speech_onset >= PAUSE_MIN_SPEECH_S
        ):
            self._pause_sent = True
            self.pauses += 1
            self.emit(FrontEndEvent("pause", now))

    def _with_pre_roll(self, segment: VADSegment) -> VADSegment:
        """Prepend up to `pre_roll_s` of audio preceding the detector's segment start."""
        if self.pre_roll_s <= 0 or not self._ring:
            return segment
        rate = self.vad.sample_rate
        start_index = round(segment.start_s * rate)
        ring_start = self._fed_samples - self._ring_samples
        want = int(self.pre_roll_s * rate)
        lo = max(ring_start, start_index - want)
        if lo >= start_index or start_index > self._fed_samples:
            return segment
        buffer = np.concatenate(list(self._ring))
        pre = buffer[lo - ring_start : start_index - ring_start]
        if len(pre) == 0:
            return segment
        clip = AudioClip(np.concatenate([pre, segment.clip.samples]).astype(np.float32), rate)
        return VADSegment(clip, segment.start_s - len(pre) / rate, segment.end_s)

    def run(self) -> None:
        """Pull audio, run VAD, emit events."""
        Log.info0()
        self._audio = self.body.subscribe_audio()
        if self._audio is None:
            Log.warning("body has no audio; front end idle")
            return
        last_ongoing = 0.0
        last_level = 0.0
        try:
            while not self._stop_event.is_set():
                try:
                    chunk = self._audio.get(timeout=0.2)
                except queue.Empty:
                    continue
                self.chunks += 1
                now = time.monotonic()
                self._remember(chunk)
                self.vad.feed(chunk)
                if self.keyword_stream is not None:
                    try:
                        hits = self.keyword_stream.feed(chunk, self.vad.sample_rate)
                    except Exception as exc:
                        Log.warning(f"keyword stream failed; disabled: {exc!r}")
                        self.keyword_stream = None
                        hits = []
                    for hit in hits:
                        self.keywords_spotted += 1
                        self.emit(
                            FrontEndEvent(
                                "keyword",
                                now,
                                side=str(hit),
                                doa=self.body.doa_between(now - 1.0, now),
                            )
                        )
                speaking = self.vad.is_speech()
                self._track_pause(chunk, now, speaking)
                moving_until = self.body.moving_until()
                moving = now < moving_until
                if speaking and self.speech_onset is None:
                    self.speech_onset = now
                    self._onset_moving = moving
                    self._moving_until_seen = moving_until if moving else 0.0
                    last_ongoing = now
                    self.emit(
                        FrontEndEvent("speech_start", now, doa=self.body.doa(), self_motion=moving)
                    )
                elif speaking and self.speech_onset is not None:
                    if moving:
                        self._moving_until_seen = max(self._moving_until_seen, moving_until)
                    if now - last_ongoing >= self.ongoing_period_s:
                        last_ongoing = now
                        self.emit(
                            FrontEndEvent(
                                "speech_ongoing",
                                now,
                                duration_s=now - self.speech_onset,
                                doa=self.body.doa(),
                                self_motion=moving,
                            )
                        )
                for raw in self.vad.pop_segments():
                    self.segments += 1
                    onset = self.speech_onset
                    self.speech_onset = None
                    segment = self._with_pre_roll(raw)
                    duration = raw.end_s - raw.start_s
                    self_motion = (
                        onset is not None
                        and self._onset_moving
                        and onset + duration <= self._moving_until_seen + 0.5
                    )
                    if self_motion:
                        self.self_motion_segments += 1
                    spoken_from = (onset if onset is not None else now - duration) - (
                        SEGMENT_DOA_LEAD_S
                    )
                    self.emit(
                        FrontEndEvent(
                            "speech_end",
                            now,
                            duration_s=duration,
                            segment=segment,
                            doa=self.body.doa_between(spoken_from, now),
                            self_motion=self_motion,
                        )
                    )
                    if onset is None:
                        Log.debug("segment without onset event")
                if not speaking and self.speech_onset is not None and not self.vad.is_speech():
                    # Detector dropped speech without emitting a segment (too short): still close
                    # the onset with a segment-less `speech_end` so listeners (captions) reset.
                    if now - self.speech_onset > 0.05:
                        onset = self.speech_onset
                        self.speech_onset = None
                        self.emit(FrontEndEvent("speech_end", now, duration_s=now - onset))
                if now - last_level >= 0.5:
                    last_level = now
                    self.emit(FrontEndEvent("level", now, level_dbfs=self.body.input_level_dbfs()))
        finally:
            if self._audio is not None:
                self.body.unsubscribe_audio(self._audio)
            Log.info("front end stopped")
