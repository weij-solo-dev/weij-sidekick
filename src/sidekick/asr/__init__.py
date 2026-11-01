"""sidekick.asr — speech-to-text service: slots, backend protocol, MiniMax and local backends."""

from .asr import ASRSession
from .minimax_speech_to_text import ASRMiniMaxBackend, ASRMiniMaxConfiguration
from .schemas import ASRBackend, ASRResult
from .sherpa_kws import ASRKeywordBackend, ASRKeywordConfiguration, KeywordStream
from .sherpa_sensevoice import ASRSenseVoiceBackend, ASRSenseVoiceConfiguration

__all__ = [
    "ASRBackend",
    "ASRKeywordBackend",
    "ASRKeywordConfiguration",
    "ASRMiniMaxBackend",
    "ASRMiniMaxConfiguration",
    "ASRResult",
    "ASRSenseVoiceBackend",
    "ASRSenseVoiceConfiguration",
    "ASRSession",
    "KeywordStream",
]
