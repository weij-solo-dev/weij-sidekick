"""sidekick.interaction.initiative — the hard rules behind Banana speaking first

Overview
    The attention layer (`attention.py`, `perception.camera`) only looks; this submodule decides
    whether an attention event may become speech. It turns a `gaze.mutual` observation into a
    `greet.due` event when — and only when — a **known** contact has made eye contact for the
    first time after being away long enough, outside quiet hours and under a daily cap. The
    agent then decides *what* to say (the robot extension's `greet` automation) and may still
    answer `NO_REPLY`. Unknown people never qualify (befriending has its own path), sounds never
    qualify (orient only), and the only planned exceptions are safety events.
Design
    Pure rules over timestamps so they are unit-tested with a fake contact session. The
    `sociability` level from `ConfigInteraction` sets the absence threshold and the daily cap:
    `quiet` never speaks first, `normal` greets after 2 h away (6 greetings a day), `chatty`
    after 30 min (12 a day). "Away" is measured from the contact's `last_seen_ts`, which voice
    and face identification refresh (`ContactSession.touch`); a contact never seen before counts
    as away. A greeting is counted when it is *offered* to the agent, not when it is spoken, so a
    `NO_REPLY` does not lead to nagging. Quiet hours are the automation section's (`23:00` →
    `07:30` by default), handed in by `app.py` as plain strings.
Depends on
    sidekick.contact (duck-typed), sidekick.log.

See Also
--------
    AGENTS.md "Interaction" (attention and initiative), PLAN.md block "[2026-10-27 #38]".

"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from sidekick.contact import is_person
from sidekick.log import Log

GREET_AFTER_H: dict[str, float | None] = {"quiet": None, "normal": 2.0, "chatty": 0.5}
GREET_DAILY_CAP: dict[str, int] = {"quiet": 0, "normal": 6, "chatty": 12}
GREET_REPEAT_GAP_S = 3600.0  # never offer a greeting for the same person twice within an hour


def in_quiet_hours(quiet_hours: tuple[str, str] | list[str] | None, now: datetime) -> bool:
    """`("23:00", "07:30")` style window, possibly crossing midnight."""
    if not quiet_hours or len(quiet_hours) != 2:
        return False
    start_h, start_m = (int(x) for x in quiet_hours[0].split(":"))
    end_h, end_m = (int(x) for x in quiet_hours[1].split(":"))
    minutes = now.hour * 60 + now.minute
    start, end = start_h * 60 + start_m, end_h * 60 + end_m
    return start <= minutes < end if start <= end else minutes >= start or minutes < end


class Initiative:
    """Decides when a known person's mutual gaze earns a greeting."""

    def __init__(
        self,
        contacts: Any,
        sociability: str = "normal",
        quiet_hours: tuple[str, str] | list[str] | None = None,
    ) -> None:
        self.contacts = contacts
        self.sociability = sociability if sociability in GREET_AFTER_H else "normal"
        self.quiet_hours = quiet_hours
        self.greeted: dict[str, float] = {}
        self.offered_today = 0
        self._today = ""
        self.last: dict[str, Any] | None = None
        self.last_reason = ""

    def configure(self, config: Any) -> None:
        """Take the level from `ConfigInteraction` (also after a Settings change)."""
        level = str(getattr(config, "sociability", self.sociability))
        if level in GREET_AFTER_H and level != self.sociability:
            Log.info(f"sociability {self.sociability} -> {level}")
            self.sociability = level

    def _roll_day(self, now: float) -> None:
        day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        if day != self._today:
            self._today, self.offered_today = day, 0

    def on_mutual_gaze(
        self, contact_id: str | None, now: float | None = None
    ) -> dict[str, Any] | None:
        """A mutual gaze happened; returns the `greet.due` data when a greeting is due."""
        now = time.time() if now is None else now
        self._roll_day(now)
        after_h = GREET_AFTER_H.get(self.sociability)
        if after_h is None:
            return self._no("sociability quiet")
        if not contact_id or is_person(contact_id) or contact_id == "self":
            return self._no("unknown person")
        contact = self.contacts.get(contact_id) if self.contacts is not None else None
        if contact is None:
            return self._no("no such contact")
        if in_quiet_hours(self.quiet_hours, datetime.fromtimestamp(now)):
            return self._no("quiet hours")
        if self.offered_today >= GREET_DAILY_CAP.get(self.sociability, 0):
            return self._no("daily cap")
        last_greet = self.greeted.get(contact_id)
        if last_greet is not None and now - last_greet < GREET_REPEAT_GAP_S:
            return self._no("greeted recently")
        last_seen = getattr(contact, "last_seen_ts", None)
        absent_h = None if last_seen is None else (now - float(last_seen)) / 3600.0
        if absent_h is not None and absent_h < after_h:
            return self._no(f"seen {absent_h * 60:.0f} min ago")
        self.greeted[contact_id] = now
        self.offered_today += 1
        touch = getattr(self.contacts, "touch", None)
        if callable(touch):
            touch(contact_id, now, force=True)
        self.last = {
            "contact": contact_id,
            "name": getattr(contact, "name", contact_id),
            "language": getattr(contact, "language", None),
            "absent_h": None if absent_h is None else round(absent_h, 1),
            "sociability": self.sociability,
        }
        self.last_reason = "greet"
        Log.info(f"initiative: greet {contact_id} (away {self.last['absent_h']} h)")
        return dict(self.last)

    def _no(self, reason: str) -> dict[str, Any] | None:
        self.last_reason = reason
        return None

    def snapshot(self) -> dict[str, Any]:
        """For the rail and `/api/interaction`."""
        return {
            "sociability": self.sociability,
            "offered_today": self.offered_today,
            "last": self.last,
            "last_reason": self.last_reason,
        }
