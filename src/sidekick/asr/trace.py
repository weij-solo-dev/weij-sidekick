"""sidekick.asr.trace — ASR call trace table

Overview
    One row per `ASRSession.transcribe` call (invariant 5): slot, vendor, audio length, latency,
    transcript. The dashboard compares `primary` and `local` rows for the same utterance.
Design
    Thin wrapper over `storage.TraceTable`.
Depends on
    sidekick.storage.
"""

from __future__ import annotations

from pathlib import Path

from sidekick.storage import SERVICE_TRACE_RETENTION_DAYS, TraceTable

from .schemas import ASRResult

COLUMNS = {
    "slot": "TEXT",
    "provider": "TEXT",
    "api": "TEXT",
    "model": "TEXT",
    "api_key_hint": "TEXT",
    "duration_ms": "REAL",
    "success": "INTEGER",
    "status_code": "INTEGER",
    "api_code": "INTEGER",
    "error": "TEXT",
    "language": "TEXT",
    "audio_s": "REAL",
    "text_chars": "INTEGER",
    "text": "TEXT",
    "task": "TEXT",
}


class ASRTrace(TraceTable):
    """`asr_trace` table in `asr_trace_v1.db`."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, "asr_trace", COLUMNS, SERVICE_TRACE_RETENTION_DAYS)

    def record_result(
        self, slot: str, result: ASRResult, duration_ms: float, task: str | None
    ) -> str:
        """Flatten one call into a row."""
        return self.record(
            slot=slot,
            provider=result.provider,
            api=result.api,
            model=result.model,
            api_key_hint=result.api_key_hint,
            duration_ms=duration_ms,
            success=1 if result.success else 0,
            status_code=result.status_code,
            api_code=result.api_code,
            error=result.error_message,
            language=result.language,
            audio_s=result.duration_s,
            text_chars=len(result.text or ""),
            text=result.text,
            task=task,
        )
