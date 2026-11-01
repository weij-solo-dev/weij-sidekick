"""sidekick.automation.schemas — the job

Overview
    `Job` is one automation: a trigger (`cron`, `at` or `event`), the prompt the main agent
    answers when it fires, who asked for it (`owner`) and where the request came from
    (`channel`), the delivery policy and its run bookkeeping.
Design
    A frozen dataclass. Jobs always run on the main agent (invariant 22), so a job names no
    agent; the `agent` column of `automation_v1.db` is still written (`main`) so the table keeps
    its shape. Built-in jobs (`builtin`) are made by code — the heartbeat and the extensions'
    event jobs — and the agent's tools never list or cancel them.
Depends on
    sidekick.agent (`HOUSEHOLD`, the owner of a job nobody in particular asked for).

See Also
--------
    AGENTS.md "Automations, heartbeat, delivery".

"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from sidekick.agent import HOUSEHOLD

Delivery = Literal["in_person", "remote", "both", "auto"]
JobState = Literal["active", "paused", "done"]


def new_id() -> str:
    """Random row id."""
    return uuid.uuid4().hex


@dataclass(frozen=True, slots=True)
class Job:
    """An automation."""

    name: str
    trigger_kind: Literal["cron", "at", "event"]
    trigger: str
    prompt: str
    id: str = field(default_factory=new_id)
    delivery: Delivery = "auto"
    owner: str = HOUSEHOLD
    channel: str | None = None
    state: JobState = "active"
    created_ts: float = field(default_factory=time.time)
    last_run_ts: float | None = None
    next_run_ts: float | None = None
    runs: int = 0
    event_filter: dict[str, Any] = field(default_factory=dict)
    builtin: bool = False
