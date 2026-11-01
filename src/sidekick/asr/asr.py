"""sidekick.asr.asr — ASRSession façade with slots

Overview
    `primary` is the cloud recognizer used for engaged turns (MiniMax first); `local` is the
    on-host SenseVoice used for wake-name spotting and as fallback. Every call is traced.
Design
    Same shape as `LLMSession`: dict of slots, `setup(slot, backend)`, failures as results.
    A slot's `setup` closes the backend it replaces or unbinds — the pooled HTTP client, or the
    local model (`close()`), which `preload()` loads at the service's start (block #87).
Depends on
    sidekick.log, sidekick.audio, sidekick.storage (through .trace).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, ClassVar

from sidekick.audio import AudioClip
from sidekick.log import Log
from sidekick.storage import RecentCalls, StorageSession

from .schemas import ASRBackend, ASRResult
from .trace import ASRTrace

_closing: set[asyncio.Task[None]] = set()  # replaced backends closing on the loop


def _close(backend: Any) -> None:
    """Release what a replaced or unbound backend holds (pooled connections, a loaded model).

    `aclose()` runs on the running loop when there is one (kept referenced until done),
    otherwise `close()` when the backend has it.
    """
    aclose = getattr(backend, "aclose", None)
    if callable(aclose):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            task = loop.create_task(aclose())
            _closing.add(task)
            task.add_done_callback(_closing.discard)
            return
    close = getattr(backend, "close", None)
    if callable(close):
        try:
            close()
        except Exception as exc:  # pragma: no cover - teardown best effort
            Log.warning(f"closing {type(backend).__name__}: {exc!r}")


class ASRSession:
    """Holds the active ASR backends per slot and traces every call."""

    shared: ClassVar[ASRSession]

    def __init__(self) -> None:
        self._slots: dict[str, ASRBackend] = {}
        self._trace: ASRTrace | None = None
        self.calls = RecentCalls()  # the newest calls in memory, for the Live page

    @property
    def trace(self) -> ASRTrace:
        """The trace table (created under the storage home when none was configured)."""
        if self._trace is None:
            self._trace = ASRTrace(StorageSession.shared.layout.db_path("asr_trace"))
        return self._trace

    def configure_trace(self, path: Path | None) -> None:
        """Enable (or disable with None) persistence of call traces."""
        self._trace = ASRTrace(path) if path is not None else None

    def setup(self, slot: str, backend: ASRBackend | None) -> None:
        """Bind or unbind a slot; the backend it replaces is closed."""
        old = self._slots.pop(slot, None)
        if backend is not None:
            self._slots[slot] = backend
        if old is not None and old is not backend:
            _close(old)
        if backend is not None or old is not None:
            Log.info(f"slot {slot} -> {type(backend).__name__ if backend else None}")

    def is_ready(self, slot: str) -> bool:
        """Whether a slot has a backend."""
        return slot in self._slots

    def slots(self) -> list[str]:
        """Bound slot names."""
        return sorted(self._slots)

    def backend(self, slot: str) -> ASRBackend | None:
        """The backend bound to a slot, if any."""
        return self._slots.get(slot)

    async def transcribe(
        self, slot: str, clip: AudioClip, language: str | None = None, task: str | None = None
    ) -> ASRResult:
        """Transcribe on a slot, traced."""
        started = time.monotonic()
        backend = self._slots.get(slot)
        if backend is None:
            Log.error(f"slot {slot} has no backend")
            result = ASRResult(
                False,
                None,
                "",
                "",
                "",
                "",
                language=language,
                error_message=f"no backend for slot {slot}",
            )
        else:
            self.calls.begin(slot)
            try:
                result = await backend.transcribe(clip, language)
            except BaseException:
                self.calls.end(
                    slot, False, (time.monotonic() - started) * 1000.0, task, None, "raised"
                )
                raise
            self.calls.end(
                slot,
                result.success,
                (time.monotonic() - started) * 1000.0,
                task,
                None,
                result.error_message,
            )
        duration = (time.monotonic() - started) * 1000.0
        Log.info(f"slot={slot} success={result.success} duration={duration:.0f}ms")
        if self._trace is not None:
            try:
                self._trace.record_result(slot, result, duration, task)
            except Exception as exc:
                Log.error(f"trace failed: {exc!r}")
        return result

    def live(self) -> dict[str, Any]:
        """Per slot: the last call, medians, calls and errors in the last hour (in memory)."""
        return {"slots": self.calls.summary(), "bound": self.slots()}


ASRSession.shared = ASRSession()
