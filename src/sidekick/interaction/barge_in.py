"""sidekick.interaction.barge_in — two-stage interruption while the robot speaks (invariant 20)

Overview
    Speech from a qualifying source first ducks playback (stage 1, within ~100 ms of onset);
    a hard stop (stage 2) needs sustained speech, a stop word, the wake name or an antenna
    touch. Short backchannels restore the volume and the robot carries on.
Design
    Pure decision logic driven by the front end's `speech_start` / `speech_ongoing` /
    `speech_end` events and optional local transcripts. "Qualifying" is decided by the caller
    (addressee match or unknown-speaker direction match) because it needs session state; stop
    words and the wake name are checked here on the local transcript of the interrupting
    segment, which is also what rules a backchannel out.
Depends on
    sidekick.interaction.namespot (normalisation + name matching).

See Also
--------
    AGENTS.md "Interruption (two-stage barge-in, invariant 20)", PLAN.md block #8.

"""

from __future__ import annotations

from collections.abc import Iterable

from .namespot import NameSpotter, normalize
from .schemas import BargeInDecision


class BargeInController:
    """Duck → confirm → stop | resume."""

    def __init__(
        self,
        name_spotter: NameSpotter,
        stop_words: Iterable[str] = (),
        backchannels: Iterable[str] = (),
        duck_db: float = -12.0,
        hard_stop_speech_s: float = 0.7,
    ) -> None:
        self.names = name_spotter
        self.stop_words = [normalize(word) for word in stop_words if normalize(word)]
        self.backchannels = [normalize(word) for word in backchannels if normalize(word)]
        self.duck_db = duck_db
        self.hard_stop_speech_s = hard_stop_speech_s
        self.ducked = False
        self.onset: float | None = None
        self.stopped = False

    def reset(self) -> None:
        """New playback turn."""
        self.ducked = False
        self.onset = None
        self.stopped = False

    def is_stop_word(self, text: str) -> bool:
        """Whether the transcript is (or starts with) a stop word."""
        norm = normalize(text)
        return bool(norm) and any(norm == word or norm.startswith(word) for word in self.stop_words)

    def only_stop_word(self, text: str) -> bool:
        """The whole utterance is a stop word (nothing to answer afterwards)."""
        norm = normalize(text)
        return bool(norm) and norm in self.stop_words

    def is_backchannel(self, text: str) -> bool:
        """Short acknowledgements that must never stop the robot."""
        norm = normalize(text)
        if not norm:
            return True
        if len(norm) <= 2 and any(norm.startswith(word) for word in self.backchannels):
            return True
        return norm in self.backchannels

    def on_speech_start(self, now: float, qualifying: bool) -> BargeInDecision:
        """Stage 1."""
        if self.stopped:
            return BargeInDecision("ignore", "already stopped")
        if not qualifying:
            return BargeInDecision("ignore", "source not qualifying")
        self.onset = now
        if self.ducked:
            return BargeInDecision("ignore", "already ducked")
        self.ducked = True
        return BargeInDecision("duck", "qualifying speech onset")

    def on_speech_ongoing(self, now: float, duration_s: float) -> BargeInDecision:
        """Stage 2 by duration."""
        if self.stopped or not self.ducked:
            return BargeInDecision("ignore", "not ducked")
        if duration_s >= self.hard_stop_speech_s:
            self.stopped = True
            return BargeInDecision(
                "stop", f"speech {duration_s:.2f}s >= {self.hard_stop_speech_s}s"
            )
        return BargeInDecision("ignore", "speech too short so far")

    def on_speech_end(self, now: float, duration_s: float, text: str | None) -> BargeInDecision:
        """Stage 2 by content, else resume."""
        if self.stopped:
            return BargeInDecision("ignore", "already stopped")
        if not self.ducked:
            return BargeInDecision("ignore", "not ducked")
        if text is not None:
            if self.is_stop_word(text):
                self.stopped = True
                return BargeInDecision("stop", "stop word")
            if self.names.match(text).hit:
                self.stopped = True
                return BargeInDecision("stop", "wake name")
        if duration_s >= self.hard_stop_speech_s and not (
            text is not None and self.is_backchannel(text)
        ):
            self.stopped = True
            return BargeInDecision("stop", f"speech {duration_s:.2f}s")
        self.ducked = False
        self.onset = None
        return BargeInDecision("resume", "backchannel" if text else "short speech")

    def on_touch(self) -> BargeInDecision:
        """Antenna: always a hard stop."""
        self.stopped = True
        return BargeInDecision("stop", "touch")
