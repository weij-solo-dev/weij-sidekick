"""sidekick.body.touch — antenna push detection from commanded-versus-measured joint angles

Overview
    The Lite has no touch sensor, so a "touch" is an antenna pushed away from where the motion
    owner commanded it. This detector turns the per-tick (commanded, present) pairs into one
    `BodyTouch` event per press with hysteresis and a debounce, and arms itself only after the
    antenna has settled near its target so our own antenna motions never count as touches.
Design
    Press when |present − commanded| ≥ `press_rad` (0.3 rad, the platform's own threshold);
    release when it drops below `release_rad`. A press fires once per side until release. The
    detector is paused by the owner while an emotion or antenna gesture moves the antennas,
    because the commanded value is then not what the daemon is tracking. After a pause each
    side arms only once its **measured** angle has come within `release_rad` of the command: a
    touch is an antenna pushed away from where it was, so one that never got there — blocked
    when the head looks up (the left one stopped at +10° of +43° on 2026-10-30) or still held
    by a hand — never fires; before this, every re-arm read the blocked antenna as a new press,
    and the press's acknowledgement moved the antennas and re-armed it again, once a second
    (block #80).
Depends on
    stdlib only.

See Also
--------
    AGENTS.md "Interaction" trigger 3 (`touch`), PLAN.md block "[2026-10-26 #9]".

"""

from __future__ import annotations

import time

from .schemas import ANTENNA_PRESS_RAD, ANTENNA_RELEASE_RAD, BodyTouch

SIDES = ("right", "left")


class TouchDetector:
    """Hysteresis detector for the two antennas."""

    def __init__(
        self,
        press_rad: float = ANTENNA_PRESS_RAD,
        release_rad: float = ANTENNA_RELEASE_RAD,
        debounce_s: float = 0.3,
        settle_s: float = 0.4,
    ) -> None:
        self.press_rad = press_rad
        self.release_rad = release_rad
        self.debounce_s = debounce_s
        self.settle_s = settle_s
        self._pressed = dict.fromkeys(SIDES, False)
        self._settled = dict.fromkeys(SIDES, False)
        self._armed_at = 0.0
        self._last_fire = float("-inf")
        self._paused = False

    def pause(self, now: float | None = None) -> None:
        """Stop detecting while the antennas are being animated."""
        self._paused = True
        self._pressed = dict.fromkeys(SIDES, False)
        self._settled = dict.fromkeys(SIDES, False)

    def resume(self, now: float | None = None) -> None:
        """Re-arm after `settle_s`."""
        self._paused = False
        self._armed_at = (now if now is not None else time.monotonic()) + self.settle_s

    @property
    def paused(self) -> bool:
        """Whether detection is suspended."""
        return self._paused

    def update(
        self,
        commanded: tuple[float, float],
        present: tuple[float, float],
        now: float | None = None,
    ) -> BodyTouch | None:
        """Feed one tick; returns a touch event at most once per press."""
        now = time.monotonic() if now is None else now
        if self._paused or now < self._armed_at:
            return None
        event: BodyTouch | None = None
        for index, side in enumerate(SIDES):
            delta = abs(present[index] - commanded[index])
            if not self._settled[side]:
                self._settled[side] = delta < self.release_rad
                continue
            if self._pressed[side]:
                if delta < self.release_rad:
                    self._pressed[side] = False
                continue
            if delta >= self.press_rad and now - self._last_fire >= self.debounce_s:
                self._pressed[side] = True
                if event is None:
                    self._last_fire = now
                    event = BodyTouch("antenna", side, delta, now)
        return event
