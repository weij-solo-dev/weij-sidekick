"""sidekick.perception.audio — speech-direction events from the microphone array

Overview
    Emits `audio.speech` when the array reports speech after silence (with the direction) and
    keeps the last speech direction in the presence snapshot. Alarm / cry classification is a
    later addition on the same watcher.
Design
    Reads `BodySession.doa()` (cached from the daemon); an event fires on the rising edge of the
    `speech` flag, at most once per second.
Depends on
    sidekick.log, sidekick.body.

See Also
--------
    AGENTS.md "Perception".

"""

from __future__ import annotations

import time

from sidekick.body import BodyDoA, BodySession, doa_to_yaw

from .schemas import PerceptionEvent, Severity
from .watcher import Watcher


class AudioWatcher(Watcher):
    """Speech onset events."""

    name = "audio"

    def __init__(self, body: BodySession, poll_hz: float = 5.0) -> None:
        super().__init__(1.0 / poll_hz)
        self.body = body
        self._was_speech = False
        self._last_event = float("-inf")
        self.last_direction: float | None = None

    def observe(self, doa: BodyDoA | None, now: float | None = None) -> list[PerceptionEvent]:
        """Feed one reading."""
        now = time.time() if now is None else now
        if doa is None:
            self._was_speech = False
            return []
        events: list[PerceptionEvent] = []
        if doa.speech:
            self.last_direction = doa_to_yaw(doa.angle)
            if not self._was_speech and now - self._last_event >= 1.0:
                self._last_event = now
                events.append(
                    PerceptionEvent(
                        "audio.speech",
                        Severity.DEBUG,
                        {"yaw": round(self.last_direction, 2), "angle": round(doa.angle, 2)},
                        now,
                    )
                )
        self._was_speech = doa.speech
        return events

    async def poll(self) -> list[PerceptionEvent]:
        """Read the array."""
        return self.observe(self.body.doa())
