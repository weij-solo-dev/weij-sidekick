"""sidekick.interaction.engagement — the SLEEPING → IDLE → ENGAGED ↔ SPEAKING machine

Overview
    Decides, for every speech segment and touch, whether the robot is being talked to
    (invariant 17: nothing reaches cloud ASR before this says yes) and when a conversation ends
    (silence timeout, closing phrase, repeated `NO_REPLY`). It is pure logic over timestamps so
    it is unit-tested without audio. The silence is counted from the moment Bobby stops talking;
    after a reply that ends with a question it is `answer_timeout_s` instead of
    `session_timeout_s` — a child thinking about 「你估下…？」 at the end of a story needs more
    than 8 s (block #89). Speech that began before the silence ran out is not silence: the
    session waits for its segment (it used to close under people mid-sentence, block #92).
Design
    Triggers from AGENTS.md: `wake_name` (open to everyone), `touch` (antenna), `gaze` (enrolled
    voices only — wired in Phase 4 when `contact` identifies speakers), `robot_initiated`. In
    ENGAGED, a segment matches the session when the speaker id matches; two different known
    contacts are `other speaker`; anything else — no identity, an unnamed person on either side
    — is decided by the direction of arrival within the configured sector tolerance, and a
    known voice then replaces an unknown or unnamed session speaker (block #80: the session's
    speaker used to be whoever the short "Bobby" clip was taken for, so every later sentence of
    the same person was "someone else" and fell to a direction read in the silence after it).
    A segment that carries the name adopts its voice the same way: a session opened by the
    keyword stream has no speaker, and a stop by name used to be credited to a fresh guest.
    Speech from the TV sector never triggers without the wake name. The machine never touches
    the body; the façade acts on its decisions.
Depends on
    sidekick.body (yaw math).

See Also
--------
    AGENTS.md "Interaction: engagement, interruption, languages", PLAN.md blocks #7, #8.

"""

from __future__ import annotations

import re
from typing import Any

from sidekick.body import yaw_distance
from sidekick.contact import is_person

from .namespot import normalize
from .schemas import EngagementDecision, EngagementSession, InteractionState, NameMatch

# A reply that ends with a question (closing quotes, an expression tag or an emoji may follow).
_ASKS = re.compile(r"[？?][\s」』”’）)\]]*(?:\[[^\]]*\][\s]*)*\W*$")


def asks(reply: str) -> bool:
    """Whether Bobby's reply ended by asking something."""
    return bool(reply) and bool(_ASKS.search(reply.strip()))


class EngagementMachine:
    """State + session; every method returns a decision the façade applies."""

    def __init__(self, config: Any, awake: bool = True) -> None:
        self.config = config
        self.state = InteractionState.IDLE if awake else InteractionState.SLEEPING
        self.session: EngagementSession | None = None
        self.guest_counter = 0
        self.last_transition_reason = "init"

    # ----------------------------------------------------------------- helpers

    def trigger_enabled(self, name: str) -> bool:
        """Config switch for a trigger."""
        triggers = getattr(self.config, "triggers", {})
        return bool(triggers.get(name, False))

    def _in_tv_sector(self, doa_yaw: float | None) -> bool:
        sector = getattr(self.config, "tv_sector", None)
        if doa_yaw is None or not sector:
            return False
        tolerance = float(getattr(self.config, "tv_sector_tolerance_rad", 0.35))
        return any(yaw_distance(doa_yaw, float(yaw)) <= tolerance for yaw in sector)

    def is_closing(self, text: str) -> bool:
        """Whether an utterance ends the conversation."""
        norm = normalize(text)
        if not norm:
            return False
        return any(
            normalize(phrase) in norm for phrase in getattr(self.config, "closing_phrases", [])
        )

    def _new_guest(self) -> str:
        self.guest_counter += 1
        return f"guest:{self.guest_counter}"

    def _transition(self, state: InteractionState, reason: str) -> None:
        self.state = state
        self.last_transition_reason = reason

    # ------------------------------------------------------------- transitions

    def set_awake(self, awake: bool, now: float) -> EngagementDecision | None:
        """Mirror the body: asleep means we do not listen."""
        if not awake and self.state != InteractionState.SLEEPING:
            self.session = None
            self._transition(InteractionState.SLEEPING, "body asleep")
            return EngagementDecision(False, "body asleep", self.state, end_session=True)
        if awake and self.state == InteractionState.SLEEPING:
            self._transition(InteractionState.IDLE, "body awake")
            return EngagementDecision(False, "body awake", self.state)
        return None

    def begin_session(
        self,
        trigger: str,
        now: float,
        addressee: str | None = None,
        doa_yaw: float | None = None,
        speaker: str | None = None,
    ) -> EngagementSession:
        """Open a session (IDLE → ENGAGED)."""
        self.session = EngagementSession(
            addressee=addressee or speaker or self._new_guest(),
            trigger=trigger,
            started_at=now,
            last_activity=now,
            doa_yaw=doa_yaw,
            speaker=speaker,
        )
        self._transition(InteractionState.ENGAGED, f"trigger {trigger}")
        return self.session

    def end_session(self, reason: str, now: float) -> EngagementDecision:
        """Close the session (→ IDLE)."""
        self.session = None
        if self.state != InteractionState.SLEEPING:
            self._transition(InteractionState.IDLE, reason)
        return EngagementDecision(False, reason, self.state, end_session=True)

    def on_touch(self, now: float) -> EngagementDecision:
        """Antenna push: engage, extend, or (while speaking) stop."""
        if self.state == InteractionState.SLEEPING:
            return EngagementDecision(False, "asleep", self.state, trigger="touch")
        if not self.trigger_enabled("touch"):
            return EngagementDecision(False, "touch trigger off", self.state, trigger="touch")
        if self.state == InteractionState.IDLE or self.session is None:
            self.begin_session("touch", now)
            return EngagementDecision(True, "touch opened session", self.state, trigger="touch")
        self.session.last_activity = now
        if self.state == InteractionState.SPEAKING:
            self._transition(InteractionState.ENGAGED, "touch stop")
            return EngagementDecision(True, "touch stopped speech", self.state, trigger="touch")
        return EngagementDecision(True, "touch extended session", self.state, trigger="touch")

    def on_keyword(self, now: float, doa_yaw: float | None) -> EngagementDecision:
        """The streaming keyword spotter heard the name (independent of segmentation)."""
        if self.state == InteractionState.SLEEPING:
            return EngagementDecision(False, "asleep", self.state, trigger="wake_name")
        if not self.trigger_enabled("wake_name"):
            return EngagementDecision(
                False, "wake_name trigger off", self.state, trigger="wake_name"
            )
        if self._in_tv_sector(doa_yaw):
            return EngagementDecision(False, "tv sector", self.state, trigger="wake_name")
        if self.session is None or self.state == InteractionState.IDLE:
            self.begin_session("wake_name", now, doa_yaw=doa_yaw)
            return EngagementDecision(True, "wake name (stream)", self.state, trigger="wake_name")
        self.session.last_activity = now
        if doa_yaw is not None:
            self.session.doa_yaw = doa_yaw
        return EngagementDecision(
            True, "wake name in session (stream)", self.state, trigger="wake_name"
        )

    def on_segment(
        self,
        now: float,
        duration_s: float,
        doa_yaw: float | None,
        name: NameMatch | None,
        speaker: str | None = None,
        text: str | None = None,
    ) -> EngagementDecision:
        """A completed speech segment with its local analysis."""
        if self.state == InteractionState.SLEEPING:
            return EngagementDecision(False, "asleep", self.state)
        name_hit = bool(name and name.hit)
        score = name.score if name else None
        if self.state == InteractionState.IDLE or self.session is None:
            if self._in_tv_sector(doa_yaw) and not name_hit:
                return EngagementDecision(False, "tv sector", self.state, name_score=score)
            if name_hit and self.trigger_enabled("wake_name"):
                self.begin_session("wake_name", now, doa_yaw=doa_yaw, speaker=speaker)
                remainder = name.remainder if name else ""
                return EngagementDecision(
                    True,
                    "wake name",
                    self.state,
                    trigger="wake_name",
                    text=remainder,
                    name_score=score,
                )
            return EngagementDecision(False, "no wake name", self.state, name_score=score)
        session = self.session
        if name_hit:
            session.last_activity = now
            self._adopt(session, speaker)
            if doa_yaw is not None:
                session.doa_yaw = doa_yaw
            remainder = name.remainder if name else ""
            return EngagementDecision(
                True,
                "wake name in session",
                self.state,
                trigger="wake_name",
                text=remainder,
                name_score=score,
            )
        same = speaker is not None and speaker == session.speaker
        if (
            not same
            and speaker is not None
            and session.speaker is not None
            and not is_person(speaker)
            and not is_person(session.speaker)
        ):
            return EngagementDecision(False, "other speaker", self.state, name_score=score)
        if (
            not same
            and session.doa_yaw is not None
            and doa_yaw is not None
            and yaw_distance(doa_yaw, session.doa_yaw)
            > float(getattr(self.config, "doa_sector_tolerance_rad", 0.6))
        ):
            return EngagementDecision(False, "other direction", self.state, name_score=score)
        session.last_activity = now
        self._adopt(session, speaker)
        if doa_yaw is not None:
            session.doa_yaw = doa_yaw
        return EngagementDecision(
            True, "in session", self.state, trigger=session.trigger, text=text, name_score=score
        )

    @staticmethod
    def _adopt(session: EngagementSession, speaker: str | None) -> None:
        """A known voice replaces an unknown or unnamed session speaker (block #80)."""
        if speaker is not None and (
            session.speaker is None or (is_person(session.speaker) and not is_person(speaker))
        ):
            session.speaker = speaker
            session.addressee = speaker

    def on_robot_speaking(self, speaking: bool, now: float, doa_yaw: float | None = None) -> None:
        """ENGAGED ↔ SPEAKING."""
        if self.state == InteractionState.SLEEPING:
            return
        if speaking:
            if self.session is None:
                self.begin_session("robot_initiated", now, doa_yaw=doa_yaw)
            self._transition(InteractionState.SPEAKING, "robot speaking")
        elif self.state == InteractionState.SPEAKING:
            if self.session is not None:
                self.session.last_activity = now
            self._transition(InteractionState.ENGAGED, "robot quiet")

    def robot_initiated(self, now: float, addressee: str | None = None) -> bool:
        """An automation or heartbeat is about to speak to a present person."""
        if self.state == InteractionState.SLEEPING:
            return False
        if self.session is None:
            if not self.trigger_enabled("robot_initiated"):
                return True
            self.begin_session("robot_initiated", now, addressee=addressee)
        else:
            self.session.last_activity = now
        return True

    def on_turn_done(
        self, now: float, text_in: str, no_reply: bool, reply: str = ""
    ) -> EngagementDecision | None:
        """After a turn: count `NO_REPLY`s, detect closings; may end the session."""
        if self.session is None:
            return None
        self.session.turns += 1
        self.session.last_activity = now
        self.session.asked = asks(reply)
        if no_reply:
            self.session.no_reply_streak += 1
            if self.session.no_reply_streak >= int(getattr(self.config, "no_reply_limit", 2)):
                return self.end_session("no_reply limit", now)
        else:
            self.session.no_reply_streak = 0
        if self.is_closing(text_in):
            return self.end_session("closing phrase", now)
        return None

    def on_tick(self, now: float, speech_onset: float | None = None) -> EngagementDecision | None:
        """Silence timeout while ENGAGED (not while the robot speaks, not under a speaker).

        `speech_onset` is the start of the speech going on now, if any: speech that began
        before the silence ran out holds the session until its segment is decided (block #92).
        """
        if self.state != InteractionState.ENGAGED or self.session is None:
            return None
        timeout = float(getattr(self.config, "session_timeout_s", 8.0))
        if self.session.asked:
            timeout = max(timeout, float(getattr(self.config, "answer_timeout_s", timeout)))
        deadline = self.session.last_activity + timeout
        if now < deadline:
            return None
        if speech_onset is not None and speech_onset <= deadline:
            return None  # they began to talk in time: their sentence decides
        return self.end_session("timeout", now)

    def extend(self, now: float) -> None:
        """Keep the session alive (e.g. the addressee's face stays frontal)."""
        if self.session is not None:
            self.session.last_activity = now

    def snapshot(self) -> dict[str, Any]:
        """For the dashboard."""
        session = self.session
        return {
            "state": self.state.value,
            "reason": self.last_transition_reason,
            "session": None
            if session is None
            else {
                "addressee": session.addressee,
                "trigger": session.trigger,
                "turns": session.turns,
                "speaker": session.speaker,
                "doa_yaw": session.doa_yaw,
                "started_at": session.started_at,
                "last_activity": session.last_activity,
            },
        }
