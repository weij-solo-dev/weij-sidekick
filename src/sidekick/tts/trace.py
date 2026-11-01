"""sidekick.tts.trace — TTS call trace table

Overview
    One row per `TTSSession.infer` call (invariant 5). Streaming sessions are traced by the
    interaction pipeline, which knows the text and the timing of a turn.
Design
    Thin wrapper over `storage.TraceTable`. Audio bytes are not stored; the dashboard plays
    clips from `.derived_data/audio/` when the pipeline saves them.
Depends on
    sidekick.storage.
"""

from __future__ import annotations

from pathlib import Path

from sidekick.storage import SERVICE_TRACE_RETENTION_DAYS, TraceTable

from .schemas import TTSResult

COLUMNS = {
    "slot": "TEXT",
    "provider": "TEXT",
    "api": "TEXT",
    "model": "TEXT",
    "voice": "TEXT",
    "api_key_hint": "TEXT",
    "duration_ms": "REAL",
    "success": "INTEGER",
    "status_code": "INTEGER",
    "api_code": "INTEGER",
    "error": "TEXT",
    "input_chars": "INTEGER",
    "output_bytes": "INTEGER",
    "usage_chars": "INTEGER",
    "audio_ms": "REAL",
    "text": "TEXT",
    "task": "TEXT",
}


class TTSTrace(TraceTable):
    """`tts_trace` table in `tts_trace_v1.db`."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, "tts_trace", COLUMNS, SERVICE_TRACE_RETENTION_DAYS)

    def record_result(
        self, slot: str, text: str, result: TTSResult, duration_ms: float, task: str | None
    ) -> str:
        """Flatten one call into a row."""
        audio_ms = None
        if result.success and result.audio and result.format == "pcm":
            audio_ms = len(result.audio) / 2.0 / result.channels / result.sample_rate * 1000.0
        return self.record(
            slot=slot,
            provider=result.provider,
            api=result.api,
            model=result.model,
            voice=result.voice,
            api_key_hint=result.api_key_hint,
            duration_ms=duration_ms,
            success=1 if result.success else 0,
            status_code=result.status_code,
            api_code=result.api_code,
            error=result.error_message,
            input_chars=len(text),
            output_bytes=len(result.audio) if result.audio else None,
            usage_chars=result.usage_chars,
            audio_ms=audio_ms,
            text=text,
            task=task,
        )
