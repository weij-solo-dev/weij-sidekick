"""sidekick.automation.jobs — the job store and the cron matcher

Overview
    `JobStore` keeps every job in `automation_v1.db`; `cron_matches` / `next_cron` / `parse_at` /
    `compute_next` decide when a job runs next. Natural language ("八點提我食藥") becomes a job
    through the `schedule` tool; built-in jobs come from code (`ensure_builtin`, the heartbeat).
Design
    The 5-field cron matcher supports `*`, `*/n`, `a-b`, lists and names-free numbers at minute
    resolution; `next_run_ts` is precomputed on every save so `due()` is an index lookup. A
    one-shot (`at`) job is `done` after its run; `event` jobs have no next run, the perception
    bus fires them. The table's `agent` column is written as `main` (jobs always run on the
    main agent, invariant 22) and never read.
Depends on
    sidekick.log, sidekick.storage.

See Also
--------
    AGENTS.md "Automations, heartbeat, delivery".

"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sidekick.log import Log
from sidekick.storage import Database

from .schemas import Delivery, Job, JobState, new_id

MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, trigger_kind TEXT NOT NULL, trigger TEXT NOT NULL,
        prompt TEXT NOT NULL, agent TEXT NOT NULL, delivery TEXT NOT NULL, owner TEXT NOT NULL,
        channel TEXT, state TEXT NOT NULL, created_ts REAL NOT NULL, last_run_ts REAL,
        next_run_ts REAL, runs INTEGER NOT NULL, event_filter TEXT, builtin INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS jobs_next ON jobs(state, next_run_ts);
    """
]


# ------------------------------------------------------------------------------ cron


def _field_matches(expr: str, value: int, low: int, high: int) -> bool:
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = max(1, int(step_s))
        if part == "*":
            start, end = low, high
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
            if step > 1:
                end = high
        if start <= value <= end and (value - start) % step == 0:
            return True
    return False


def cron_matches(expr: str, when: datetime) -> bool:
    """Whether a 5-field cron expression matches a minute."""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"cron needs 5 fields: {expr!r}")
    minute, hour, dom, month, dow = fields
    weekday = (when.weekday() + 1) % 7  # cron: 0 = Sunday
    return (
        _field_matches(minute, when.minute, 0, 59)
        and _field_matches(hour, when.hour, 0, 23)
        and _field_matches(dom, when.day, 1, 31)
        and _field_matches(month, when.month, 1, 12)
        and (_field_matches(dow, weekday, 0, 6) or (weekday == 0 and _field_matches(dow, 7, 0, 7)))
    )


def next_cron(expr: str, after: datetime, horizon_days: int = 366) -> datetime | None:
    """First matching minute strictly after `after`."""
    cron_matches(expr, after)  # validate
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = after + timedelta(days=horizon_days)
    while candidate <= end:
        if cron_matches(expr, candidate):
            return candidate
        candidate += timedelta(minutes=1)
    return None


def parse_at(value: str) -> datetime:
    """ISO local time, or `HH:MM` meaning today (tomorrow when past)."""
    value = value.strip()
    if len(value) in (4, 5) and ":" in value:
        hour, minute = value.split(":")
        now = datetime.now()
        target = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target
    return datetime.fromisoformat(value)


def compute_next(job: Job, now: datetime | None = None) -> float | None:
    """Next run timestamp for a job (None when it will not run again)."""
    now = now or datetime.now()
    if job.state != "active":
        return None
    if job.trigger_kind == "cron":
        following = next_cron(job.trigger, now)
        return following.timestamp() if following else None
    if job.trigger_kind == "at":
        target = parse_at(job.trigger)
        return target.timestamp() if job.runs == 0 else None
    return None  # event jobs are fired externally


# ----------------------------------------------------------------------------- store


class JobStore:
    """CRUD over jobs."""

    def __init__(self, path: Path) -> None:
        self.db = Database(path, MIGRATIONS)

    @staticmethod
    def _row(row: Any) -> Job:
        return Job(
            name=row["name"],
            trigger_kind=row["trigger_kind"],
            trigger=row["trigger"],
            prompt=row["prompt"],
            id=row["id"],
            delivery=row["delivery"],
            owner=row["owner"],
            channel=row["channel"],
            state=row["state"],
            created_ts=row["created_ts"],
            last_run_ts=row["last_run_ts"],
            next_run_ts=row["next_run_ts"],
            runs=row["runs"],
            event_filter=json.loads(row["event_filter"] or "{}"),
            builtin=bool(row["builtin"]),
        )

    def save(self, job: Job) -> Job:
        """Insert or replace, recomputing `next_run_ts`."""
        next_ts = compute_next(job)
        self.db.execute(
            "INSERT INTO jobs (id, name, trigger_kind, trigger, prompt, agent, delivery, owner, channel, state,"
            " created_ts, last_run_ts, next_run_ts, runs, event_filter, builtin)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET"
            " name = excluded.name, trigger_kind = excluded.trigger_kind, trigger = excluded.trigger,"
            " prompt = excluded.prompt, agent = excluded.agent, delivery = excluded.delivery,"
            " owner = excluded.owner, channel = excluded.channel, state = excluded.state,"
            " last_run_ts = excluded.last_run_ts, next_run_ts = excluded.next_run_ts, runs = excluded.runs,"
            " event_filter = excluded.event_filter, builtin = excluded.builtin",
            (
                job.id,
                job.name,
                job.trigger_kind,
                job.trigger,
                job.prompt,
                "main",
                job.delivery,
                job.owner,
                job.channel,
                job.state,
                job.created_ts,
                job.last_run_ts,
                next_ts,
                job.runs,
                json.dumps(job.event_filter, ensure_ascii=False),
                int(job.builtin),
            ),
        )
        return self.get(job.id) or job

    def get(self, job_id: str) -> Job | None:
        """One job."""
        rows = self.db.query("SELECT * FROM jobs WHERE id = ?", (job_id,))
        return self._row(rows[0]) if rows else None

    def by_name(self, name: str) -> Job | None:
        """First job with that name."""
        rows = self.db.query(
            "SELECT * FROM jobs WHERE name = ? ORDER BY created_ts LIMIT 1", (name,)
        )
        return self._row(rows[0]) if rows else None

    def list_jobs(self, include_done: bool = False, owner: str | None = None) -> list[Job]:
        """Jobs, soonest first."""
        sql = "SELECT * FROM jobs WHERE 1 = 1"
        params: list[Any] = []
        if not include_done:
            sql += " AND state != 'done'"
        if owner:
            sql += " AND owner = ?"
            params.append(owner)
        sql += " ORDER BY COALESCE(next_run_ts, 1e18), created_ts"
        return [self._row(r) for r in self.db.query(sql, tuple(params))]

    def upcoming(self, limit: int = 3) -> list[Job]:
        """The next active timed jobs, soonest first (the Live page's countdown)."""
        rows = self.db.query(
            "SELECT * FROM jobs WHERE state = 'active' AND next_run_ts IS NOT NULL"
            " ORDER BY next_run_ts LIMIT ?",
            (limit,),
        )
        return [self._row(r) for r in rows]

    def due(self, now_ts: float | None = None) -> list[Job]:
        """Active jobs whose next run is in the past."""
        now_ts = now_ts or time.time()
        rows = self.db.query(
            "SELECT * FROM jobs WHERE state = 'active' AND next_run_ts IS NOT NULL AND next_run_ts <= ?"
            " ORDER BY next_run_ts",
            (now_ts,),
        )
        return [self._row(r) for r in rows]

    def mark_run(self, job: Job, now_ts: float | None = None) -> Job:
        """Record a run and advance (or finish one-shot jobs)."""
        now_ts = now_ts or time.time()
        state: JobState = "done" if job.trigger_kind == "at" else job.state
        return self.save(
            replace(job, state=state, last_run_ts=now_ts, next_run_ts=None, runs=job.runs + 1)
        )

    def set_state(self, job_id: str, state: JobState) -> Job | None:
        """Pause / resume / finish."""
        job = self.get(job_id)
        return self.save(replace(job, state=state, next_run_ts=None)) if job else None

    def delete(self, job_id: str) -> bool:
        """Remove."""
        return self.db.execute("DELETE FROM jobs WHERE id = ?", (job_id,)) > 0

    def ensure_builtin(
        self,
        name: str,
        event: str,
        prompt: str,
        *,
        delivery: Delivery = "auto",
        event_filter: dict[str, Any] | None = None,
        origin: str | None = None,
    ) -> Job:
        """Create or refresh a built-in event job (an extension's contribution)."""
        existing = self.by_name(name)
        job = Job(
            name,
            "event",
            event,
            prompt,
            id=existing.id if existing else new_id(),
            delivery=delivery,
            state=existing.state if existing and existing.state == "paused" else "active",
            created_ts=existing.created_ts if existing else time.time(),
            last_run_ts=existing.last_run_ts if existing else None,
            runs=existing.runs if existing else 0,
            event_filter=dict(event_filter or {}),
            builtin=True,
        )
        Log.info(f"built-in event job {name!r} on {event} ({origin or 'core'})")
        return self.save(job)

    def delete_builtin(self, name: str) -> bool:
        """Remove a built-in job by name (extension disabled)."""
        existing = self.by_name(name)
        return self.delete(existing.id) if existing is not None and existing.builtin else False
