"""sidekick.doctor.schemas — one readiness item and the report that holds them

Overview
    `DoctorItem` is one line of the readiness list: what was checked, how it went (`ok` /
    `warn` / `bad`), a detail the operator can act on, the dashboard tab where it is fixed and the
    layer that produced it. `DoctorReport` is the ordered collection with the verdict.
Design
    Frozen dataclasses with `as_dict()` for JSON; no pydantic because nothing here is user input.
    `ready` means "no blocking item": `warn` rows are advice (no member enrolled, no channel
    paired), `bad` rows stop a conversation (no LLM key, daemon down). `service` is the state of
    Banana's service (block #87): while it is not running the report holds only the
    prerequisites, and the summary says "stopped" with what must be fixed before a start. The tab names are the
    dashboard's `data-tab` values (the module directories: live, voice, body, agent, contact,
    channel, record, extension, system) so a row can carry its own jump link.
Depends on
    stdlib only.

See Also
--------
    AGENTS.md "Readiness", PLAN.md block "[2026-10-27 #44]".

"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

LEVELS = ("ok", "warn", "bad")
LAYERS = ("local", "probe", "loopback")
_RANK = {"ok": 0, "warn": 1, "bad": 2}


@dataclass(frozen=True, slots=True)
class DoctorItem:
    """One readiness row."""

    id: str
    title: str
    level: str
    detail: str = ""
    tab: str = "system"
    layer: str = "local"
    latency_ms: float | None = None

    @property
    def ok(self) -> bool:
        """Whether the row passed."""
        return self.level == "ok"

    def as_dict(self) -> dict[str, Any]:
        """JSON form."""
        return {
            "id": self.id,
            "title": self.title,
            "level": self.level,
            "detail": self.detail,
            "tab": self.tab,
            "layer": self.layer,
            "latency_ms": None if self.latency_ms is None else round(self.latency_ms, 1),
        }


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Every row of the last run, in layer order."""

    ts: float
    items: tuple[DoctorItem, ...]
    layers: tuple[str, ...] = ("local",)
    running: str | None = None  # the layer being run right now, if any
    service: str | None = None  # stopped / starting / running / stopping (None: not wired)

    @property
    def bad(self) -> int:
        """Blocking rows."""
        return sum(1 for item in self.items if item.level == "bad")

    @property
    def warn(self) -> int:
        """Advisory rows."""
        return sum(1 for item in self.items if item.level == "warn")

    @property
    def ready(self) -> bool:
        """No blocking row."""
        return self.bad == 0

    def summary(self) -> str:
        """One line for the rail and the log."""
        if self.running:
            return f"checking {self.running}…"
        if self.service in ("starting", "stopping"):
            return f"{self.service}…"
        if self.service == "stopped":
            return (
                "stopped · ready to start"
                if self.ready
                else f"stopped · {self.bad} to fix before starting"
            )
        if not self.items:
            return "not checked yet"
        if self.ready and self.warn == 0:
            return "ready"
        parts = []
        if self.bad:
            parts.append(f"{self.bad} blocking")
        if self.warn:
            parts.append(f"{self.warn} advisory")
        return ("ready · " if self.ready else "not ready · ") + " · ".join(parts)

    def worst_by_tab(self) -> dict[str, str]:
        """The worst level per dashboard tab (for the sidebar dots)."""
        out: dict[str, str] = {}
        for item in self.items:
            if _RANK[item.level] > _RANK.get(out.get(item.tab, "ok"), 0):
                out[item.tab] = item.level
        return {tab: level for tab, level in out.items() if level != "ok"}

    def as_dict(self, failing_only: bool = False) -> dict[str, Any]:
        """JSON form; `failing_only` keeps the rows that need attention (the rail card)."""
        rows = [item for item in self.items if not failing_only or not item.ok]
        return {
            "ts": self.ts,
            "ready": self.ready,
            "bad": self.bad,
            "warn": self.warn,
            "summary": self.summary(),
            "layers": list(self.layers),
            "running": self.running,
            "service": self.service,
            "tabs": self.worst_by_tab(),
            "items": [item.as_dict() for item in rows],
        }
