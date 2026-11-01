"""sidekick.automation.heartbeat — Bobby's periodic look for news the household has not heard yet

Overview
    The heartbeat (OpenClaw's word for it) is one built-in `cron` job of the scheduler: every
    `automation.heartbeat_minutes` (30 by default, 0 pauses it) the main agent gets one turn to
    say something new the household has not heard yet — a finished delegated task, for
    example — or to answer `NO_REPLY`, which is what it usually does. It is a consumer at the
    top of the stack, not a system tick: nothing subscribes to it and nothing depends on it.
    Periodic work registers as a scheduler job, event sources publish on the perception bus
    (PLAN.md block #52).
Design
    This file owns all of it: the job (`ensure_heartbeat`; 0 minutes pauses it rather than
    deleting it, so it keeps its id and run count), how it is recognised (`is_heartbeat`, which
    the façade hands to the scheduler as the quiet-hours rule — the heartbeat stays silent in
    quiet hours, user reminders do not) and its prompt (`heartbeat_prompt`). Reminders are
    spoken by their own jobs, never by the heartbeat. The timeline view carries no times, so the
    prompt states when the heartbeat last ran and lists what Bobby said on its own initiative in
    the last day, with times — the façade asks the agent for that list (`delivered_since`);
    without it the heartbeat re-announced a past reminder every half hour (block #47).
Depends on
    Nothing outside the module: the sibling submodules `jobs` (JobStore) and `schemas` (Job).

See Also
--------
    AGENTS.md "Automations, heartbeat, delivery"; PLAN.md blocks "[2026-10-28 #47]",
    "[2026-10-28 #52]", "[2026-10-28 #53]".

"""

from __future__ import annotations

import time
from collections.abc import Sequence

from .jobs import JobStore
from .schemas import Job, new_id

HEARTBEAT_NAME = "heartbeat"
HEARTBEAT_PROMPT = (
    "Heartbeat check. If the internal notes hold something new since your last heartbeat that "
    "the household has not heard yet (a finished delegated task, for example), say it in one or "
    "two sentences. Reminders and scheduled tasks are spoken by their own jobs at their time: "
    "never repeat, re-announce or invent one. Otherwise answer exactly NO_REPLY."
)
HEARTBEAT_LOOKBACK_S = 24 * 3600.0  # what the heartbeat is told it already said


def ensure_heartbeat(jobs: JobStore, minutes: int, prompt: str = HEARTBEAT_PROMPT) -> Job:
    """Create or update the built-in heartbeat job (paused at 0 minutes)."""
    cron = (
        f"*/{max(1, min(59, minutes))} * * * *"
        if minutes < 60
        else f"0 */{max(1, minutes // 60)} * * *"
    )
    existing = jobs.by_name(HEARTBEAT_NAME)
    job = Job(
        HEARTBEAT_NAME,
        "cron",
        cron,
        prompt,
        id=existing.id if existing else new_id(),
        delivery="auto",
        state="active" if minutes > 0 else "paused",
        created_ts=existing.created_ts if existing else time.time(),
        last_run_ts=existing.last_run_ts if existing else None,
        runs=existing.runs if existing else 0,
        builtin=True,
    )
    return jobs.save(job)


def is_heartbeat(job: Job) -> bool:
    """Whether a job is the built-in heartbeat."""
    return job.builtin and job.name == HEARTBEAT_NAME


def heartbeat_prompt(job: Job, said: Sequence[tuple[float, str]]) -> str:
    """The turn's prompt plus when it last ran and what Bobby already said unprompted."""
    lines = [job.prompt]
    if job.last_run_ts:
        lines.append(f"Your last heartbeat was at {_clock(job.last_run_ts)}.")
    newest: dict[str, float] = {}  # text → newest time it was delivered
    for ts, text in said:
        newest[text] = max(ts, newest.get(text, ts))
    if newest:
        lines.append("Already said on your own initiative (never repeat or rephrase any of it):")
        recent = sorted(newest.items(), key=lambda item: item[1])[-8:]
        lines += [f"- {_clock(ts)} {text[:160]}" for text, ts in recent]
    return "\n".join(lines)


def _clock(ts: float) -> str:
    """Local date and minute, as the agent's context states "now"."""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
