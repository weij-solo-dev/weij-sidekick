"""sidekick.perception.schemas — typed events, severities and the presence snapshot

Overview
    `PerceptionEvent` is what every source emits onto the bus: a dotted `type`
    (`presence.enter`, `face.seen`, `audio.speech`, `feed.update`, `job.done`, …), a severity,
    free-form `data` and a timestamp. `Presence` is the snapshot the delivery policy and the
    engagement machine read.
Design
    Frozen dataclasses; severity is an ordered enum so persistence thresholds compare cleanly.
Depends on
    stdlib only.

See Also
--------
    AGENTS.md "Perception".

"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class Severity(IntEnum):
    """Ordered so `>=` works."""

    DEBUG = 0
    INFO = 1
    NOTICE = 2
    WARNING = 3
    ALERT = 4

    @classmethod
    def parse(cls, value: str | int) -> Severity:
        """From a config string."""
        if isinstance(value, int):
            return cls(value)
        return cls[value.upper()]


@dataclass(frozen=True, slots=True)
class PerceptionEvent:
    """One observation."""

    type: str
    severity: Severity = Severity.INFO
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    source: str = "perception"

    def matches(self, type_pattern: str, filters: dict[str, Any] | None = None) -> bool:
        """`presence.*` style patterns plus equality filters on `data`."""
        if type_pattern.endswith(".*"):
            if not self.type.startswith(type_pattern[:-1]):
                return False
        elif type_pattern != "*" and type_pattern != self.type:
            return False
        for key, expected in (filters or {}).items():
            if self.data.get(key) != expected:
                return False
        return True


@dataclass(frozen=True, slots=True)
class Presence:
    """Who is around, as far as the body can tell."""

    someone_present: bool = False
    face_visible: bool = False
    frontal: bool = False
    since_ts: float | None = None
    last_seen_ts: float | None = None
    speech_direction: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """For the dashboard."""
        return {
            "someone_present": self.someone_present,
            "face_visible": self.face_visible,
            "frontal": self.frontal,
            "since_ts": self.since_ts,
            "last_seen_ts": self.last_seen_ts,
            "speech_direction": self.speech_direction,
        }
