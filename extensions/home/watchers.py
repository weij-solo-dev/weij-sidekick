"""extensions.home.watchers — `ha.state` events for watched entities

Overview
    Polls `/api/states` and emits `ha.state` (notice) when a watched entity's state changes,
    with the old and new values; the first poll only primes the cache.
Design
    Stateless HTTP per poll; skips when not configured or no entities are watched.
Depends on
    sidekick.log, sidekick.perception, sidekick.extension, httpx.
"""

from __future__ import annotations

from typing import Any

from sidekick.extension import ExtensionContext
from sidekick.log import Log
from sidekick.perception import PerceptionEvent, Severity, Watcher

from .tools import fetch_states  # type: ignore[import-not-found]


class StateWatcher(Watcher):
    """Entity state changes."""

    name = "states"

    def __init__(self, ctx: ExtensionContext) -> None:
        super().__init__(float(ctx.setting("poll_seconds", 15) or 15))
        self.ctx = ctx
        self.last: dict[str, Any] = {}

    async def poll(self) -> list[PerceptionEvent]:
        """Diff watched entities."""
        watched = set(self.ctx.setting("watch_entities", []) or [])
        if not watched or not self.ctx.setting("url", ""):
            return []
        try:
            states = await fetch_states(self.ctx)
        except Exception as exc:
            Log.debug(f"home watcher: {exc!r}")
            return []
        events: list[PerceptionEvent] = []
        primed = bool(self.last)
        for state in states:
            entity = state.get("entity_id")
            if entity not in watched:
                continue
            value = state.get("state")
            previous = self.last.get(entity)
            self.last[entity] = value
            if primed and previous is not None and previous != value:
                events.append(
                    PerceptionEvent(
                        "ha.state",
                        Severity.NOTICE,
                        {
                            "entity_id": entity,
                            "from": previous,
                            "to": value,
                            "name": state.get("attributes", {}).get("friendly_name"),
                        },
                        source="extension:home",
                    )
                )
        return events


def WATCHERS(ctx: ExtensionContext) -> list[Watcher]:
    """The state watcher."""
    return [StateWatcher(ctx)]
