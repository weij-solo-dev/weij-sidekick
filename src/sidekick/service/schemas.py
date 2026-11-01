"""sidekick.service.schemas — the service's states, the steps of a start or stop and their items

Overview
    `ServiceStep` is one line of the start dialog: a module (or the configuration / model check
    that comes first), its state while the transition runs, a one-line detail, the module's own
    check items under it and how long it took. `ServiceTransition` is one start or stop: who
    asked, its steps, whether it went through and why not. `ServiceBusy` is raised when a request
    arrives while a transition runs.
Design
    Plain dataclasses with `as_dict()` for the routes; the item dicts come straight from each
    module's `check()` (`id`, `title`, `level` ok / warn / bad, `detail`) with the module's tab
    added. A step's state is the worst level of its items once the module has started, so the
    dialog's tick, warning or cross follows the module's own judgement of its failures; a module
    whose every item is `off` (nothing configured, e.g. no channel token) shows a dash.
Depends on
    stdlib only.

See Also
--------
    AGENTS.md "Service", PLAN.md blocks "[2026-10-30 #85]" … "[2026-10-30 #87]".

"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

STATES = ("stopped", "starting", "running", "stopping")
STEP_STATES = ("pending", "running", "ok", "warn", "bad", "skipped")
# A check item's level; `off` = not configured (a dash in the dialog, never a problem).
LEVEL_RANK = {"off": -1, "ok": 0, "warn": 1, "bad": 2}

# What the dialog calls each step, and the dashboard tab that fixes a module's items.
STEP_TITLES = {
    "config": "Configuration",
    "models": "Models",
    "body": "Robot",
    "contacts": "Contacts",
    "channels": "Channels",
    "interaction": "Voice",
    "agent": "Agent",
    "automation": "Automation",
    "perception": "Perception",
    "record": "Recording",
    "extensions": "Extensions",
}
MODULE_TABS = {
    "config": "system",
    "models": "voice",
    "body": "body",
    "contacts": "contact",
    "channels": "channel",
    "interaction": "voice",
    "agent": "agent",
    "automation": "automation",
    "perception": "live",
    "record": "record",
    "extensions": "extension",
}


class ServiceBusy(RuntimeError):
    """A start or stop is already running."""


def worst_level(items: list[dict[str, Any]]) -> str:
    """The worst level among check items: `ok` for none, `off` only when every item is off."""
    if not items:
        return "ok"
    level = "off"
    for item in items:
        candidate = str(item.get("level", "ok"))
        if LEVEL_RANK.get(candidate, 0) > LEVEL_RANK[level]:
            level = candidate
    return level


@dataclass(slots=True)
class ServiceStep:
    """One line of a start (or stop)."""

    id: str
    title: str
    state: str = "pending"
    detail: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    started: float | None = None
    ms: float | None = None

    def begin(self, detail: str = "") -> None:
        """Mark it running."""
        self.state = "running"
        self.detail = detail
        self.started = time.monotonic()

    def finish(self, state: str, detail: str | None = None) -> None:
        """Mark it done with `state` (`ok` / `warn` / `bad` / `skipped`)."""
        self.state = state
        if detail is not None:
            self.detail = detail
        if self.started is not None:
            self.ms = (time.monotonic() - self.started) * 1000.0

    def as_dict(self) -> dict[str, Any]:
        """JSON form."""
        return {
            "id": self.id,
            "title": self.title,
            "state": self.state,
            "detail": self.detail,
            "items": self.items,
            "ms": None if self.ms is None else round(self.ms),
            "tab": MODULE_TABS.get(self.id, "system"),
        }


@dataclass(slots=True)
class ServiceTransition:
    """One start or stop."""

    action: str
    by: str
    steps: list[ServiceStep]
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    ok: bool | None = None
    error: str = ""

    def step(self, step_id: str) -> ServiceStep:
        """The step with this id."""
        return next(step for step in self.steps if step.id == step_id)

    def as_dict(self) -> dict[str, Any]:
        """JSON form."""
        return {
            "action": self.action,
            "by": self.by,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "ok": self.ok,
            "error": self.error,
            "steps": [step.as_dict() for step in self.steps],
        }
