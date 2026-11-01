"""sidekick.tts.schemas — TTS result, blocking backend and streaming session protocols

Overview
    Two ways to speak: `TTSBackend.infer(text)` returns whole encoded audio; a
    `TTSStreamingBackend.open_stream()` returns a `TTSStream` that accepts text fragments as the
    LLM produces them and emits audio chunks, which is the robot's main voice path.
Design
    Audio is requested as PCM 16 kHz mono so chunks go straight to the speaker; `TTSResult.to_clip`
    converts when the format is PCM. Stream events mirror the MiniMax bidirectional protocol
    (sentence boundaries, flush, cancel, finish) because those are exactly the hooks the
    interaction pipeline needs for barge-in and turn ends.
Depends on
    sidekick.audio.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

from sidekick.audio import AudioClip


@dataclass(frozen=True, slots=True)
class TTSResult:
    """One synthesis."""

    success: bool
    audio: bytes | None
    provider: str
    api: str
    model: str
    voice: str
    api_key_hint: str
    format: str = "pcm"
    sample_rate: int = 16000
    channels: int = 1
    usage_chars: int | None = None
    status_code: int | None = None
    api_code: int | None = None
    error_message: str | None = None
    latency_ms: float | None = None

    def to_clip(self) -> AudioClip | None:
        """The audio as a clip when it is raw PCM."""
        if not self.success or self.audio is None or self.format != "pcm":
            return None
        return AudioClip.from_pcm16_bytes(self.audio, self.sample_rate, self.channels)


class TTSBackend(Protocol):
    """Whole-utterance synthesis."""

    async def infer(self, text: str) -> TTSResult:
        """Synthesize one text."""
        ...


@dataclass(frozen=True, slots=True)
class TTSStreamEvent:
    """One event from a streaming session."""

    kind: Literal[
        "audio", "sentence_start", "sentence_end", "flushed", "canceled", "finished", "error"
    ]
    audio: bytes = b""
    message: str | None = None
    api_code: int | None = None


class TTSStream(Protocol):
    """A live synthesis session."""

    async def send(self, text: str) -> None:
        """Append text; the server buffers into sentences."""
        ...

    async def flush(self) -> None:
        """Synthesize whatever is buffered without closing (end of a turn)."""
        ...

    async def cancel(self) -> None:
        """Drop buffered text and in-flight synthesis (barge-in); session stays open."""
        ...

    async def finish(self) -> None:
        """Flush and close the session."""
        ...

    def events(self) -> AsyncIterator[TTSStreamEvent]:
        """Server events, ending with `finished` or `error`."""
        ...

    async def aclose(self) -> None:
        """Tear down the connection."""
        ...


class TTSStreamingBackend(Protocol):
    """Backends that can open a `TTSStream`."""

    async def open_stream(self) -> TTSStream:
        """Connect and start a session."""
        ...
