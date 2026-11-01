"""sidekick.interaction — voice front end: VAD, wake name, engagement, barge-in, streaming turns."""

from .attention import Attention
from .barge_in import BargeInController
from .engagement import EngagementMachine
from .expression import ExpressionMapper
from .frontend import AudioFrontEnd
from .initiative import Initiative
from .interaction import InteractionSession
from .namespot import NameSpotter, is_filler, normalize
from .pipeline import SentenceSplitter, TTSStreamKeeper, TurnPipeline
from .schemas import (
    BargeInDecision,
    EngagementDecision,
    EngagementSession,
    FrontEndEvent,
    InteractionState,
    NameMatch,
    Responder,
    TurnResult,
    TurnTiming,
)
from .trace import InteractionTrace
from .voice_channel import VoiceChannel

__all__ = [
    "Attention",
    "AudioFrontEnd",
    "BargeInController",
    "BargeInDecision",
    "EngagementDecision",
    "EngagementMachine",
    "EngagementSession",
    "ExpressionMapper",
    "FrontEndEvent",
    "Initiative",
    "InteractionSession",
    "InteractionState",
    "InteractionTrace",
    "NameMatch",
    "NameSpotter",
    "Responder",
    "SentenceSplitter",
    "TTSStreamKeeper",
    "TurnPipeline",
    "TurnResult",
    "TurnTiming",
    "VoiceChannel",
    "is_filler",
    "normalize",
]
