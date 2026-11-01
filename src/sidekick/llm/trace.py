"""sidekick.llm.trace — LLM call trace table

Overview
    One row per `LLMSession.infer`/`stream` call (invariant 5): who, how long, how many tokens,
    the query and the answer. Read by the dashboard's Traces page.
Design
    A thin wrapper over `storage.TraceTable` that knows the column set and how to flatten an
    `LLMResult`. Messages are stored as JSON; secrets never reach it because `api_key_hint` is
    already masked.
Depends on
    sidekick.storage.
"""

from __future__ import annotations

import json
from pathlib import Path

from sidekick.storage import SERVICE_TRACE_RETENTION_DAYS, TraceTable

from .schemas import LLMMessage, LLMResult

COLUMNS = {
    "slot": "TEXT",
    "provider": "TEXT",
    "api": "TEXT",
    "model": "TEXT",
    "api_key_hint": "TEXT",
    "duration_ms": "REAL",
    "first_token_ms": "REAL",
    "success": "INTEGER",
    "status_code": "INTEGER",
    "api_code": "INTEGER",
    "error": "TEXT",
    "finish_reason": "TEXT",
    "input_chars": "INTEGER",
    "output_chars": "INTEGER",
    "prompt_tokens": "INTEGER",
    "cached_tokens": "INTEGER",
    "completion_tokens": "INTEGER",
    "total_tokens": "INTEGER",
    "tool_calls": "INTEGER",
    "query": "TEXT",
    "answer": "TEXT",
    "task": "TEXT",
}


class LLMTrace(TraceTable):
    """`llm_trace` table in `llm_trace_v1.db`."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, "llm_trace", COLUMNS, SERVICE_TRACE_RETENTION_DAYS)

    def record_result(
        self,
        slot: str,
        messages: list[LLMMessage],
        result: LLMResult,
        duration_ms: float,
        task: str | None,
    ) -> str:
        """Flatten one call into a row."""
        query = json.dumps([m.to_openai() for m in messages], ensure_ascii=False)
        usage = result.usage
        return self.record(
            slot=slot,
            provider=result.provider,
            api=result.api,
            model=result.model,
            api_key_hint=result.api_key_hint,
            duration_ms=duration_ms,
            first_token_ms=result.first_token_ms,
            success=1 if result.success else 0,
            status_code=result.status_code,
            api_code=result.api_code,
            error=result.error_message,
            finish_reason=result.finish_reason,
            input_chars=len(query),
            output_chars=len(result.output or ""),
            prompt_tokens=usage.prompt_tokens if usage else None,
            cached_tokens=usage.cached_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
            tool_calls=len(result.tool_calls),
            query=query,
            answer=result.output,
            task=task,
        )
