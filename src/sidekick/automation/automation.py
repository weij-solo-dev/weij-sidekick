"""sidekick.automation.automation — AutomationSession: jobs, the scheduler, event jobs, heartbeat

Overview
    Everything that makes Bobby act at a time or on an event: reminders and recurring tasks
    (`cron` / `at` jobs), `event` jobs fired by the perception bus (an extension's `befriend` on
    `person.ready`, `greet` on `greet.due`, a user's "when someone comes home, tell me"), and
    the heartbeat. A due job becomes one main-agent turn whose answer is delivered by policy —
    or nothing, when the agent answers `NO_REPLY`. Its tools (`schedule`, `jobs_list`,
    `job_cancel`) let the main agent turn a request into a job.
Design
    A core module above the agent (layer 4, beside `extension`), wired by its own `setup`
    (invariant 21): it receives the `AgentSession` and the perception bus, registers its
    `main_only` tools into the agent and subscribes `on_event` to the bus; the agent never
    imports it and reaches it only through the tool protocol. Only the main agent creates,
    cancels and runs jobs (invariant 22): every job runs through `agent.run_job_turn()`, and the
    heartbeat's "already said" list comes from `agent.delivered_since()`. The prompt a job is
    run with is framed here: a due job says it is due, a fired event carries the event, the
    heartbeat gets its own prompt (`heartbeat.py`). `automation.enabled` is the master switch
    (block #55): off stops the scheduler, ignores events, pauses the heartbeat and withdraws the
    tools, so the agent never promises a reminder nothing will speak; quiet hours silence the
    heartbeat, never a user's reminder. Changes from the dashboard apply live (`set_config`).
    Jobs that fell due while Bobby's service was stopped run at the first tick after a start,
    a late one with its original time in the prompt (block #87); a task that only made sense at
    its time — a wake-up call three hours late — is reported as missed instead (block #89).
    `check()` reports the scheduler and how many were sent.
Depends on
    sidekick.log, sidekick.storage, sidekick.agent (the session it runs jobs on and the tool
    protocol), sidekick.perception (the bus it listens to).

See Also
--------
    AGENTS.md "Automations, heartbeat, delivery"; PLAN.md blocks "[2026-10-29 #55]",
    "[2026-10-29 #56]", "[2026-10-29 #57]".

"""

from __future__ import annotations

import collections
import json
import time
from pathlib import Path
from typing import Any, ClassVar

from sidekick.agent import AgentSession
from sidekick.log import Log
from sidekick.perception import PerceptionSession

from .heartbeat import HEARTBEAT_LOOKBACK_S, ensure_heartbeat, heartbeat_prompt, is_heartbeat
from .jobs import JobStore
from .scheduler import Scheduler
from .schemas import Job
from .tools import ORIGIN, automation_tools

LATE_S = 120.0  # a job run this long after its time was missed (Bobby was stopped): said so


class AutomationSession:
    """Jobs, the scheduler and the event jobs, run on the main agent."""

    shared: ClassVar[AutomationSession]

    def __init__(self) -> None:
        self.jobs: JobStore | None = None
        self.scheduler: Scheduler | None = None
        self.agent: AgentSession | None = None
        self.enabled = True
        self._tools_registered = False
        self._running = False
        self.missed = 0  # jobs that fell due while stopped, run at the last start
        # The Live page (block #69): the job running now, the newest runs, today's count.
        self.running_job: dict[str, Any] | None = None
        self.recent_runs: collections.deque[dict[str, Any]] = collections.deque(maxlen=50)
        self._today = ("", 0)

    # ------------------------------------------------------------------- setup

    def setup(
        self,
        db_path: Path,
        config: Any,
        agent: AgentSession,
        perception: PerceptionSession | None = None,
    ) -> None:
        """Open the store, register the tools into the agent, listen to the bus."""
        self.jobs = JobStore(db_path)
        self.agent = agent
        self.scheduler = Scheduler(
            self.jobs,
            self.run_job,
            float(getattr(config, "tick_s", 15.0)),
            silent_in_quiet_hours=is_heartbeat,
        )
        self.set_config(config)
        if perception is not None:
            perception.subscribe("*", self.on_event)

    def set_config(self, config: Any) -> None:
        """Apply `ConfigAutomation`: switch, quiet hours, tick, heartbeat period (live)."""
        assert self.jobs is not None and self.scheduler is not None and self.agent is not None
        self.enabled = bool(getattr(config, "enabled", True))
        quiet = getattr(config, "quiet_hours", None)
        self.scheduler.quiet_hours = tuple(quiet) if quiet else None
        self.scheduler.tick_s = float(getattr(config, "tick_s", self.scheduler.tick_s))
        minutes = int(getattr(config, "heartbeat_minutes", 30)) if self.enabled else 0
        ensure_heartbeat(self.jobs, minutes)
        if self.enabled:  # again on every setup: the tools hold the store of this setup
            self.agent.register_tools(automation_tools(self.jobs))
            self._tools_registered = True
        elif not self.enabled and self._tools_registered:
            self.agent.unregister_origin(ORIGIN)
            self._tools_registered = False
        Log.info(
            f"automation {'on' if self.enabled else 'off'}: quiet={self.scheduler.quiet_hours} "
            f"tick={self.scheduler.tick_s}s heartbeat={minutes} min"
        )

    # --------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Start ticking (when on); jobs that fell due while stopped run at the first tick."""
        self.missed = len(self.jobs.due()) if self.jobs is not None and self.enabled else 0
        self._running = True
        await self._sync_scheduler()

    async def stop(self) -> None:
        """Stop ticking."""
        self._running = False
        if self.scheduler is not None:
            await self.scheduler.stop()

    def check(self) -> list[dict[str, Any]]:
        """Readiness items: the scheduler, and the jobs that fell due while Bobby was stopped."""
        if not self.enabled:
            return [{"id": "scheduler", "title": "automation", "level": "off", "detail": "off"}]
        running = self.scheduler is not None and self.scheduler.running
        detail = "scheduler running" if running else "scheduler not running"
        if self.missed:
            detail += f" · {self.missed} job(s) due while stopped, sent now"
        return [
            {
                "id": "scheduler",
                "title": "scheduler",
                "level": "ok" if running else "warn",
                "detail": detail,
            }
        ]

    async def apply(self, config: Any) -> None:
        """`set_config` plus starting or stopping the scheduler to match the switch."""
        self.set_config(config)
        await self._sync_scheduler()

    async def _sync_scheduler(self) -> None:
        if self.scheduler is None:
            return
        if self._running and self.enabled:
            await self.scheduler.start()
        else:
            await self.scheduler.stop()

    # -------------------------------------------------------------------- runs

    async def on_event(self, event: Any) -> None:
        """Perception bus subscriber: run the active `event` jobs whose type and filter match."""
        if not self.enabled or self.jobs is None:
            return
        event_type = str(getattr(event, "type", ""))
        data = dict(getattr(event, "data", {}) or {})
        matches = getattr(event, "matches", None)
        for job in self.jobs.list_jobs():
            if job.trigger_kind != "event" or job.state != "active":
                continue
            hit = (
                matches(job.trigger, job.event_filter)
                if callable(matches)
                else job.trigger == event_type
            )
            if not hit:
                continue
            Log.info(f"event {event_type} fires job {job.name}")
            self.jobs.mark_run(job)
            try:
                await self.run_job(job, event={"type": event_type, **data})
            except Exception as exc:
                Log.error(f"event job {job.name} failed: {exc!r}")

    async def run_job(self, job: Job, event: dict[str, Any] | None = None) -> None:
        """One main-agent turn with the job's prompt, then delivery (the scheduler's runner)."""
        assert self.agent is not None
        if event is not None:
            prompt = (
                f"[event {event.get('type')} happened: {json.dumps(event, ensure_ascii=False)[:300]}] "
                f"{job.prompt}\nRespond as the task says, briefly."
            )
        elif is_heartbeat(job):
            said = self.agent.delivered_since(time.time() - HEARTBEAT_LOOKBACK_S)
            prompt = heartbeat_prompt(job, said)
        elif job.next_run_ts is not None and time.time() - job.next_run_ts > LATE_S:
            due = time.strftime("%H:%M", time.localtime(job.next_run_ts))
            prompt = (
                f"[scheduled task {job.name!r} was due at {due} but Bobby was stopped then; it"
                f" runs now] {job.prompt}\n"
                "Say what the person asked for and that it comes late, briefly. If it only made"
                " sense at that time (a wake-up call, a timer, 'leave now'), do not do it now:"
                " say briefly that you missed it."
            )
        else:
            prompt = (
                f"[scheduled task {job.name!r} is due now] {job.prompt}\n"
                "Say what the person asked for (a reminder is spoken as a reminder), briefly."
            )
        started = time.time()
        self.running_job = {"name": job.name, "kind": job.trigger_kind, "started": started}
        said_now: str | None = None
        error: str | None = None
        try:
            said_now = await self.agent.run_job_turn(
                prompt, job.owner, job.channel or "voice", job.delivery, job.id
            )
        except Exception as exc:
            error = repr(exc)
            raise
        finally:
            self.running_job = None
            day = time.strftime("%Y-%m-%d")
            self._today = (day, (self._today[1] if self._today[0] == day else 0) + 1)
            self.recent_runs.append(
                {
                    "ts": time.time(),
                    "name": job.name,
                    "kind": job.trigger_kind,
                    "heartbeat": is_heartbeat(job),
                    "said": (said_now or "")[:80] or None,
                    "error": error,
                    "ms": round((time.time() - started) * 1000),
                }
            )
        if said_now is None:
            Log.info(f"job {job.name}: nothing to say")

    # --------------------------------------------------------------- reporting

    def live(self) -> dict[str, Any]:
        """Vital signs for the Live page, from memory only (block #69).

        The job running now, the next timed jobs with their countdown (refreshed each scheduler
        tick), the heartbeat's next run and last result, quiet hours, runs today.
        """
        scheduler = self.scheduler
        now = time.time()
        upcoming = scheduler.upcoming if scheduler is not None else []
        heartbeat = next((j for j in upcoming if is_heartbeat(j)), None)
        last_beat = next((r for r in reversed(self.recent_runs) if r["heartbeat"]), None)
        return {
            "enabled": self.enabled,
            "running": bool(scheduler is not None and scheduler.running),
            "quiet": scheduler.in_quiet_hours() if scheduler is not None else False,
            "job": None
            if self.running_job is None
            else {**self.running_job, "age_s": round(now - self.running_job["started"], 1)},
            "next": [
                {
                    "name": j.name,
                    "kind": j.trigger_kind,
                    "heartbeat": is_heartbeat(j),
                    "in_s": round((j.next_run_ts or now) - now),
                }
                for j in upcoming
                if not is_heartbeat(j)
            ][:2],
            "heartbeat": None
            if heartbeat is None and last_beat is None
            else {
                "in_s": round((heartbeat.next_run_ts or now) - now) if heartbeat else None,
                "last": last_beat,
            },
            "runs_today": self._today[1] if self._today[0] == time.strftime("%Y-%m-%d") else 0,
            "last_tick_s": round(now - scheduler.last_tick, 1)
            if scheduler is not None and scheduler.last_tick
            else None,
        }

    def activity(self, since: float = 0.0, limit: int = 30) -> list[dict[str, Any]]:
        """Job runs as activity rows, newest first."""
        rows = []
        for run in reversed(self.recent_runs):
            if run["ts"] <= since:
                break
            outcome = "error" if run["error"] else "said" if run["said"] else "nothing to say"
            rows.append(
                {
                    "ts": run["ts"],
                    "module": "automation",
                    "text": f"{run['name']} ({run['kind']}): {outcome}"
                    + (f" — {run['said']}" if run["said"] else ""),
                    "level": "warn" if run["error"] else "info",
                }
            )
        return rows[:limit]

    def status(self) -> dict[str, Any]:
        """Dashboard state."""
        scheduler = self.scheduler
        return {
            "enabled": self.enabled,
            "running": bool(scheduler is not None and scheduler.running),
            "runs": scheduler.runs if scheduler is not None else 0,
            "last_tick": scheduler.last_tick if scheduler is not None else 0.0,
            "quiet": scheduler.in_quiet_hours() if scheduler is not None else False,
            "jobs": len(self.jobs.list_jobs()) if self.jobs is not None else 0,
            "tools": ["schedule", "jobs_list", "job_cancel"] if self._tools_registered else [],
        }


AutomationSession.shared = AutomationSession()
