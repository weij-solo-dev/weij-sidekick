"""sidekick.automation.scheduler — fires due jobs, one at a time

Overview
    Every `tick_s` the scheduler loads the due `cron` / `at` jobs from the store and hands each
    to its runner (the façade's `run_job`: one main-agent turn, then delivery).
Design
    It never runs two jobs concurrently, to keep the robot's attention coherent, and it knows no
    job by name: the façade gives it the quiet-hours rule as a predicate
    (`silent_in_quiet_hours`, the heartbeat). A silenced job is marked run, so it waits for its
    next slot instead of firing when the quiet hours end; user reminders are never silenced.
Depends on
    sidekick.log.

See Also
--------
    AGENTS.md "Automations, heartbeat, delivery".

"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime

from sidekick.log import Log

from .jobs import JobStore
from .schemas import Job

JobRunner = Callable[[Job], Awaitable[None]]


class Scheduler:
    """Fires due jobs one at a time."""

    def __init__(
        self,
        store: JobStore,
        runner: JobRunner,
        tick_s: float = 15.0,
        quiet_hours: tuple[str, str] | None = None,
        silent_in_quiet_hours: Callable[[Job], bool] | None = None,
    ) -> None:
        self.store = store
        self.runner = runner
        self.tick_s = tick_s
        self.quiet_hours = quiet_hours
        self.silent_in_quiet_hours = silent_in_quiet_hours
        self._task: asyncio.Task[None] | None = None
        self.last_tick = 0.0
        self.runs = 0
        self.upcoming: list[Job] = []  # refreshed every tick, read by the Live page

    @property
    def running(self) -> bool:
        """Whether the tick loop runs."""
        return self._task is not None

    def in_quiet_hours(self, now: datetime | None = None) -> bool:
        """Whether the clock is inside the household's quiet hours."""
        if not self.quiet_hours:
            return False
        now = now or datetime.now()
        start_h, start_m = (int(x) for x in self.quiet_hours[0].split(":"))
        end_h, end_m = (int(x) for x in self.quiet_hours[1].split(":"))
        minutes = now.hour * 60 + now.minute
        start, end = start_h * 60 + start_m, end_h * 60 + end_m
        return start <= minutes < end if start <= end else minutes >= start or minutes < end

    async def start(self) -> None:
        """Begin ticking."""
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="scheduler")

    async def stop(self) -> None:
        """Stop ticking."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _loop(self) -> None:
        Log.info0(f"tick={self.tick_s}s quiet={self.quiet_hours}")
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                Log.error(f"scheduler tick: {exc!r}")
            await asyncio.sleep(self.tick_s)

    async def tick(self, now_ts: float | None = None) -> int:
        """Run every due job once; returns how many ran."""
        now_ts = now_ts or time.time()
        self.last_tick = now_ts
        ran = 0
        silent = self.silent_in_quiet_hours
        for job in self.store.due(now_ts):
            if silent is not None and silent(job) and self.in_quiet_hours():
                self.store.mark_run(job, now_ts)
                continue
            Log.info(f"job due: {job.name} ({job.trigger_kind} {job.trigger})")
            self.store.mark_run(job, now_ts)
            try:
                await self.runner(job)
            except Exception as exc:
                Log.error(f"job {job.name} failed: {exc!r}")
            ran += 1
            self.runs += 1
        self.upcoming = self.store.upcoming()
        return ran
