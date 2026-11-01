"""sidekick.tts.tts — TTSSession façade with slots

Overview
    `primary` is the streaming MiniMax WebSocket backend used by the voice pipeline; `fallback`
    is the HTTP backend. `infer` is traced; `open_stream` hands the live session to the caller;
    `synthesize` returns one clip for callers that only need audio (Bobby's own voice enrolment).
Design
    Same shape as `LLMSession` / `ASRSession`. `open_stream` raises when the slot's backend has
    no streaming support so the pipeline can fall back deliberately. `synthesize` prefers the
    blocking `fallback` slot, so it never opens a streaming session.
    A slot's `setup` closes the backend it replaces or unbinds (its pooled client, block #87).
Depends on
    sidekick.log, sidekick.storage (through .trace), sidekick.audio.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, ClassVar

from sidekick.audio import AudioClip
from sidekick.log import Log
from sidekick.storage import RecentCalls, StorageSession

from .schemas import TTSBackend, TTSResult, TTSStream
from .trace import TTSTrace

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


class TTSSession:
    """Holds the active TTS backends per slot and traces every blocking call."""

    shared: ClassVar[TTSSession]

    def __init__(self) -> None:
        self._slots: dict[str, TTSBackend] = {}
        self._trace: TTSTrace | None = None
        self.calls = RecentCalls()  # the newest calls in memory, for the Live page

    @property
    def trace(self) -> TTSTrace:
        """The trace table (created under the storage home when none was configured)."""
        if self._trace is None:
            self._trace = TTSTrace(StorageSession.shared.layout.db_path("tts_trace"))
        return self._trace

    def configure_trace(self, path: Path | None) -> None:
        """Enable (or disable with None) persistence of call traces."""
        self._trace = TTSTrace(path) if path is not None else None

    def setup(self, slot: str, backend: TTSBackend | None) -> None:
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

    def backend(self, slot: str) -> TTSBackend | None:
        """The backend bound to a slot, if any."""
        return self._slots.get(slot)

    def supports_streaming(self, slot: str) -> bool:
        """Whether the slot's backend can open a `TTSStream`."""
        return hasattr(self._slots.get(slot), "open_stream")

    async def infer(self, slot: str, text: str, task: str | None = None) -> TTSResult:
        """Blocking synthesis on a slot, traced."""
        started = time.monotonic()
        backend = self._slots.get(slot)
        if backend is None:
            Log.error(f"slot {slot} has no backend")
            result = TTSResult(
                False, None, "", "", "", "", "", error_message=f"no backend for slot {slot}"
            )
        else:
            self.calls.begin(slot)
            try:
                result = await backend.infer(text)
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
                self._trace.record_result(slot, text, result, duration, task)
            except Exception as exc:
                Log.error(f"trace failed: {exc!r}")
        return result

    async def synthesize(self, text: str, task: str | None = None) -> AudioClip | None:
        """One clip of `text` (the `fallback` slot when bound, else the first); None without TTS."""
        slots = self.slots()
        if not slots:
            return None
        slot = "fallback" if self.is_ready("fallback") else slots[0]
        result = await self.infer(slot, text, task=task)
        return result.to_clip()

    async def open_stream(self, slot: str) -> TTSStream:
        """Open a live session on a streaming-capable slot."""
        backend = self._slots.get(slot)
        if backend is None or not hasattr(backend, "open_stream"):
            raise RuntimeError(f"slot {slot} has no streaming backend")
        stream: TTSStream = await backend.open_stream()
        return stream

    def live(self) -> dict[str, Any]:
        """Per slot: the last call, medians, calls and errors in the last hour (in memory)."""
        return {"slots": self.calls.summary(), "bound": self.slots()}


TTSSession.shared = TTSSession()
