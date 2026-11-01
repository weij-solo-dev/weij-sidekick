"""sidekick.asr.schemas — ASR result and backend protocol

Overview
    Utterance-level speech recognition: a clip in, text out, with the vendor bookkeeping every
    `*Result` carries (invariant 4). Real-time streaming is a separate optional protocol so the
    pipeline can adopt a streaming vendor later without changing callers of `transcribe`.
Design
    Language codes are BCP-47-ish and shared project-wide: `yue`, `zh`, `en`; `None` means let
    the vendor auto-detect (MiniMax: empty `language` header; SenseVoice: `auto`).
Depends on
    sidekick.audio.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from sidekick.audio import AudioClip


@dataclass(frozen=True, slots=True)
class ASRResult:
    """One transcription."""

    success: bool
    text: str | None
    provider: str
    api: str
    model: str
    api_key_hint: str
    language: str | None = None
    duration_s: float | None = None
    status_code: int | None = None
    api_code: int | None = None
    error_message: str | None = None
    latency_ms: float | None = None


@dataclass(frozen=True, slots=True)
class ASRPartial:
    """A streaming hypothesis; `is_final` marks the end of an utterance."""

    text: str
    is_final: bool
    language: str | None = None


class ASRBackend(Protocol):
    """Utterance transcription."""

    async def transcribe(self, clip: AudioClip, language: str | None = None) -> ASRResult:
        """Transcribe one clip."""
        ...


class ASRStreamingBackend(Protocol):
    """Real-time transcription for vendors that accept audio while the user speaks."""

    def transcribe_stream(
        self, frames: AsyncIterator[AudioClip], language: str | None = None
    ) -> AsyncIterator[ASRPartial]:
        """Yield partial and final hypotheses as frames arrive."""
        ...
