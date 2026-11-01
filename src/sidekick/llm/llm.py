"""sidekick.llm.llm — LLMSession façade with named slots

Overview
    The agent never talks to a backend directly; it asks `LLMSession.shared` for a slot (`fast`
    for the main agent, `smart` for subagents) and every call is traced. `config.apply()` binds
    slots to backends; `app.py` points the trace at `.derived_data/llm_trace_v1.db`.
Design
    Slots are a plain dict; an unbound slot yields a failed `LLMResult` instead of raising so a
    misconfiguration shows up in traces and the dashboard rather than as a crash. Streaming is
    traced once, when the `done` event arrives; `calls` keeps the newest calls in memory for
    the Live page (`live()`: last call, medians, errors, calls in flight). `warm(slot)` asks a backend that pools its
    connections to open one now (a turn then skips the TLS handshake, block #71); a backend
    without `warm` is left alone.
    A **hedged** stream (`hedge_after_s`, block #78) sends the same request again when the
    provider has not started answering by then — MiniMax answered one call in twenty only after
    9–13 s while the median was 1.4 s — and streams whichever answers first (its `start`
    event, or its end); the other is cancelled and counted as `hedge lost`, not as an error.
    A request that ends without answering does not win while the other may still. Both legs are
    traced like any call, the second under `<task>.hedge`; `live()` counts hedges sent and won.
    A slot's `setup` closes the backend it replaces or unbinds (`aclose()` on the loop), so a
    restart of the service leaves no pooled connection behind (block #87).
Depends on
    sidekick.log, sidekick.storage (through .trace).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

from sidekick.log import Log
from sidekick.storage import RecentCalls, StorageSession

from .schemas import LLMBackend, LLMInferOptions, LLMMessage, LLMResult, LLMStreamEvent
from .trace import LLMTrace

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


class LLMSession:
    """Holds the active backends per slot and traces every call."""

    shared: ClassVar[LLMSession]

    def __init__(self) -> None:
        self._slots: dict[str, LLMBackend] = {}
        self._trace: LLMTrace | None = None
        self.calls = RecentCalls()
        self.hedges: dict[str, dict[str, int]] = {}  # slot → hedges sent, and won by the second

    @property
    def trace(self) -> LLMTrace:
        """The trace table (created under the storage home when none was configured)."""
        if self._trace is None:
            self._trace = LLMTrace(StorageSession.shared.layout.db_path("llm_trace"))
        return self._trace

    def configure_trace(self, path: Path | None) -> None:
        """Enable (or disable with None) persistence of call traces."""
        self._trace = LLMTrace(path) if path is not None else None

    def setup(self, slot: str, backend: LLMBackend | None) -> None:
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

    def backend(self, slot: str) -> LLMBackend | None:
        """The backend bound to a slot, if any."""
        return self._slots.get(slot)

    async def warm(self, slot: str, connections: int = 1) -> None:
        """Open pooled connections for a slot ahead of a call (no-op when it cannot pool).

        A hedged slot keeps two, so the second request needs no handshake either.
        """
        warm = getattr(self._slots.get(slot), "warm", None)
        if warm is not None:
            await (warm(connections) if connections > 1 else warm())

    async def infer(
        self,
        slot: str,
        messages: list[LLMMessage],
        options: LLMInferOptions = LLMInferOptions(),
        task: str | None = None,
    ) -> LLMResult:
        """Blocking completion on a slot, traced."""
        started = time.monotonic()
        backend = self._slots.get(slot)
        self.calls.begin(slot)
        if backend is None:
            Log.error(f"slot {slot} has no backend")
            result = LLMResult(
                False, None, "", "", "", "", error_message=f"no backend for slot {slot}"
            )
        else:
            try:
                result = await backend.infer(messages, options)
            except BaseException:
                self.calls.end(
                    slot, False, (time.monotonic() - started) * 1000.0, task, None, "raised"
                )
                raise
        self._record(slot, messages, result, started, task)
        return result

    async def stream(
        self,
        slot: str,
        messages: list[LLMMessage],
        options: LLMInferOptions = LLMInferOptions(),
        task: str | None = None,
        hedge_after_s: float | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        """Streaming completion on a slot, traced on completion.

        With `hedge_after_s`, a call the provider has not started answering by then is sent
        again and the first of the two to answer is streamed (block #78).
        """
        backend = self._slots.get(slot)
        if backend is None:
            started = time.monotonic()
            self.calls.begin(slot)
            Log.error(f"slot {slot} has no backend")
            result = LLMResult(
                False, None, "", "", "", "", error_message=f"no backend for slot {slot}"
            )
            self._record(slot, messages, result, started, task)
            yield LLMStreamEvent("done", result=result)
            return
        if not hedge_after_s or hedge_after_s <= 0:
            async for event in self._traced(slot, backend, messages, options, task):
                yield event
            return
        first = _Leg()
        first.run(self._traced(slot, backend, messages, options, task, first))
        legs = [first]
        winner = first
        try:
            if await _answered(legs, hedge_after_s) is None:
                second = _Leg()
                second.run(
                    self._traced(slot, backend, messages, options, f"{task or slot}.hedge", second)
                )
                legs.append(second)
                counts = self.hedges.setdefault(slot, {"sent": 0, "won": 0})
                counts["sent"] += 1
                Log.info(f"slot={slot} no answer after {hedge_after_s:.1f}s: asked again ({task})")
                waiting = list(legs)
                while True:
                    leg = await _answered(waiting, None)
                    assert leg is not None
                    if leg.failed and len(waiting) > 1:
                        waiting.remove(leg)  # it ended without answering; the other still may
                        continue
                    winner = leg
                    break
                if winner is second:
                    counts["won"] += 1
                for leg in legs:
                    if leg is not winner:
                        await leg.stop(lost=True)
            while (queued := await winner.queue.get()) is not None:
                yield queued
        finally:
            for leg in legs:
                await leg.stop()

    async def _traced(
        self,
        slot: str,
        backend: LLMBackend,
        messages: list[LLMMessage],
        options: LLMInferOptions,
        task: str | None,
        leg: _Leg | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        """One backend stream, traced when its `done` arrives."""
        started = time.monotonic()
        self.calls.begin(slot)
        recorded = False
        try:
            async for event in backend.stream(messages, options):
                if event.kind == "done" and event.result is not None:
                    self._record(slot, messages, event.result, started, task)
                    recorded = True
                yield event
        finally:
            if not recorded:  # cancelled mid-stream: no trace row, still counted, not an error
                note = "hedge lost" if leg is not None and leg.lost else "cancelled"
                self.calls.end(
                    slot,
                    False,
                    (time.monotonic() - started) * 1000.0,
                    task,
                    None,
                    note,
                    cancelled=True,
                )

    def live(self) -> dict[str, Any]:
        """Per slot: the last call, medians, calls and errors in the last hour, hedges (memory)."""
        slots = self.calls.summary()
        for slot, counts in self.hedges.items():
            if slot in slots:
                slots[slot]["hedged"] = counts["sent"]
                slots[slot]["hedge_won"] = counts["won"]
        return {"slots": slots, "bound": self.slots()}

    def _record(
        self,
        slot: str,
        messages: list[LLMMessage],
        result: LLMResult,
        started: float,
        task: str | None,
    ) -> None:
        duration = (time.monotonic() - started) * 1000.0
        Log.info(f"slot={slot} success={result.success} duration={duration:.0f}ms")
        self.calls.end(
            slot, result.success, duration, task, result.first_token_ms, result.error_message
        )
        if self._trace is not None:
            try:
                self._trace.record_result(slot, messages, result, duration, task)
            except Exception as exc:  # tracing must never break a call
                Log.error(f"trace failed: {exc!r}")


class _Leg:
    """One request of a hedged call: a task pumps its events into a queue."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[LLMStreamEvent | None] = asyncio.Queue()
        self.answered = asyncio.Event()  # its first event came: an answer, or the end
        self.failed = False  # it ended without answering
        self.lost = False  # cancelled because the other request answered first
        self.task: asyncio.Task[None] | None = None

    def run(self, source: AsyncIterator[LLMStreamEvent]) -> None:
        """Start pumping."""
        self.task = asyncio.ensure_future(self._pump(source))

    async def _pump(self, source: AsyncIterator[LLMStreamEvent]) -> None:
        try:
            async for event in source:
                if not self.answered.is_set():
                    self.failed = event.kind == "done" and not (
                        event.result is not None and event.result.success
                    )
                    self.answered.set()
                self.queue.put_nowait(event)
        finally:
            self.answered.set()
            self.queue.put_nowait(None)

    async def stop(self, lost: bool = False) -> None:
        """Cancel the request (a no-op once it is over)."""
        self.lost = self.lost or lost
        if self.task is not None and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass


async def _answered(legs: list[_Leg], timeout: float | None) -> _Leg | None:
    """The first leg to answer (already answered ones first), or None after `timeout`."""
    for leg in legs:
        if leg.answered.is_set():
            return leg
    waiters = {asyncio.ensure_future(leg.answered.wait()): leg for leg in legs}
    try:
        done, _ = await asyncio.wait(waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()
    return next((leg for waiter, leg in waiters.items() if waiter in done), None)


LLMSession.shared = LLMSession()
