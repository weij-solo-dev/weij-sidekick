"""sidekick.interaction.schemas — states, events, decisions and timings of the voice front end

Overview
    The vocabulary shared by the engagement machine, the barge-in controller, the audio front
    end, the pipeline and the façade: `InteractionState`, `FrontEndEvent` (what the audio thread
    reports), `EngagementSession` / `EngagementDecision`, `NameMatch`, `BargeInDecision`,
    `TurnTiming` / `TurnResult`, and the `Responder` protocol the agent implements.
Design
    Frozen dataclasses for everything crossing a thread boundary; the mutable
    `EngagementSession` lives only inside the machine. Timing marks are monotonic seconds so
    deltas can be reported in milliseconds on the dashboard and in `PLAN.md`.
Depends on
    sidekick.audio, sidekick.body, sidekick.channel, sidekick.vad.

See Also
--------
    AGENTS.md "Interaction: engagement, interruption, languages".

"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol

from sidekick.body import BodyDoA
from sidekick.channel import ChannelMessage
from sidekick.vad import VADSegment


class InteractionState(StrEnum):
    """Engagement states (AGENTS.md diagram)."""

    SLEEPING = "sleeping"
    IDLE = "idle"
    ENGAGED = "engaged"
    SPEAKING = "speaking"


@dataclass(frozen=True, slots=True)
class FrontEndEvent:
    """What the audio thread reports to the asyncio side."""

    kind: Literal[
        "speech_start",
        "speech_ongoing",
        "pause",
        "speech_end",
        "touch",
        "body_state",
        "level",
        "keyword",
    ]
    ts: float
    duration_s: float = 0.0
    segment: VADSegment | None = None
    doa: BodyDoA | None = None
    level_dbfs: float | None = None
    side: str | None = None
    awake: bool | None = None
    self_motion: bool = False  # speech that began (and, for `speech_end`, ended) while we moved


@dataclass(frozen=True, slots=True)
class NameMatch:
    """Result of wake-name spotting on a transcript."""

    hit: bool
    score: float
    alias: str | None
    remainder: str
    text: str


@dataclass(slots=True)
class EngagementSession:
    """An open conversation with one addressee."""

    addressee: str
    trigger: str
    started_at: float
    last_activity: float
    doa_yaw: float | None = None
    speaker: str | None = None
    turns: int = 0
    no_reply_streak: int = 0
    asked: bool = False  # Banana's last reply ended with a question: wait longer for the answer


@dataclass(frozen=True, slots=True)
class EngagementDecision:
    """What the machine decided about one event."""

    accept: bool
    reason: str
    next_state: InteractionState
    trigger: str | None = None
    text: str | None = None
    name_score: float | None = None
    end_session: bool = False


@dataclass(frozen=True, slots=True)
class BargeInDecision:
    """Stage-1 / stage-2 outcome for speech during robot playback."""

    action: Literal["duck", "stop", "resume", "ignore"]
    reason: str


@dataclass(slots=True)
class TurnTiming:
    """Monotonic marks of one turn; properties give the usual latencies."""

    speech_end: float | None = None
    asr_done: float | None = None
    first_token: float | None = None
    first_sentence: float | None = None
    first_tts_audio: float | None = None
    first_audio_out: float | None = None
    turn_end: float | None = None

    @staticmethod
    def _ms(a: float | None, b: float | None) -> float | None:
        return None if a is None or b is None else (b - a) * 1000.0

    @property
    def asr_ms(self) -> float | None:
        """Speech end → transcript."""
        return self._ms(self.speech_end, self.asr_done)

    @property
    def first_token_ms(self) -> float | None:
        """Transcript → first LLM token."""
        return self._ms(self.asr_done, self.first_token)

    @property
    def first_audio_ms(self) -> float | None:
        """Speech end → first audio pushed to the speaker (the number that matters)."""
        return self._ms(self.speech_end, self.first_audio_out)

    @property
    def total_ms(self) -> float | None:
        """Speech end → speaker quiet."""
        return self._ms(self.speech_end, self.turn_end)

    def as_dict(self) -> dict[str, float | None]:
        """For traces and the dashboard."""
        return {
            "asr_ms": self.asr_ms,
            "first_token_ms": self.first_token_ms,
            "first_audio_ms": self.first_audio_ms,
            "total_ms": self.total_ms,
        }

    def marks(self, first_audio_out: float | None = None) -> dict[str, int | None]:
        """Each mark in ms after the end of speech: the Live Turn card's waterfall.

        Without speech (`say`) the transcript mark is the origin; `first_audio_out` stands in
        for a turn still running (the body knows when its first frame went out).
        """
        origin = self.speech_end if self.speech_end is not None else self.asr_done

        def at(mark: float | None) -> int | None:
            return None if origin is None or mark is None else round((mark - origin) * 1000.0)

        return {
            "asr": at(self.asr_done) if self.speech_end is not None else None,
            "first_token": at(self.first_token),
            "first_sentence": at(self.first_sentence),
            "first_audio": at(self.first_audio_out or first_audio_out),
            "end": at(self.turn_end),
        }


@dataclass(frozen=True, slots=True)
class TurnResult:
    """Outcome of one turn."""

    ok: bool
    text_in: str = ""
    text_out: str = ""
    language: str | None = None
    timing: TurnTiming = field(default_factory=TurnTiming)
    interrupted: bool = False
    no_reply: bool = False
    error: str | None = None


class Responder(Protocol):
    """What answers a turn: the agent (any object yielding text deltas)."""

    def respond(self, message: ChannelMessage) -> AsyncIterator[str]:
        """Stream reply text for one inbound message."""
        ...
