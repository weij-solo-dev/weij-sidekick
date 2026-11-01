"""sidekick.perception.watcher — base class for periodic event sources (core and extensions)

Overview
    A watcher polls something at an interval and emits events through a callback. Core sources
    (camera presence, audio) and extension watchers (feeds, downloads, Home Assistant) share this
    shape so `PerceptionSession` can start, stop and report them uniformly.
Design
    Subclasses implement `async poll() -> list[PerceptionEvent]`; the base class owns the task,
    the interval, error back-off and counters. Synchronous work belongs in `asyncio.to_thread`.
Depends on
    sidekick.log.

See Also
--------
    AGENTS.md "Perception", "Extensions" (watchers).

"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from sidekick.log import Log

from .schemas import PerceptionEvent

Emit = Callable[[PerceptionEvent], Awaitable[None]]


class Watcher:
    """Periodic poller."""

    name = "watcher"

    def __init__(self, interval_s: float = 1.0) -> None:
        self.interval_s = interval_s
        self._task: asyncio.Task[None] | None = None
        self._emit: Emit | None = None
        self.polls = 0
        self.errors = 0
        self.last_poll_ts: float | None = None
        self.last_error: str | None = None

    async def poll(self) -> list[PerceptionEvent]:
        """Override: observe once."""
        return []

    @property
    def running(self) -> bool:
        """Whether the poll loop runs."""
        return self._task is not None and not self._task.done()

    async def start(self, emit: Emit) -> None:
        """Begin polling."""
        self._emit = emit
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name=f"watcher-{self.name}")

    async def stop(self) -> None:
        """Stop polling."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def tick(self) -> int:
        """One poll + emit; returns how many events were emitted."""
        self.polls += 1
        self.last_poll_ts = time.time()
        try:
            events = await self.poll()
        except Exception as exc:
            self.errors += 1
            self.last_error = repr(exc)
            Log.warning(f"watcher {self.name}: {exc!r}")
            return 0
        for event in events:
            if self._emit is not None:
                await self._emit(event)
        return len(events)

    async def _loop(self) -> None:
        Log.info0(f"{self.name} every {self.interval_s}s")
        while True:
            await self.tick()
            await asyncio.sleep(self.interval_s * (4 if self.last_error else 1))
            if self.polls % 50 == 0 and self.last_error:
                self.last_error = None
