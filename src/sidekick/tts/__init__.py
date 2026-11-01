"""sidekick.tts — text-to-speech service: slots, backend protocols, MiniMax HTTP and WebSocket."""

from .minimax_sync import TTSMiniMaxSyncBackend, TTSMiniMaxSyncConfiguration
from .minimax_ws import TTSMiniMaxWSBackend, TTSMiniMaxWSConfiguration, TTSMiniMaxWSStream
from .schemas import TTSBackend, TTSResult, TTSStream, TTSStreamEvent, TTSStreamingBackend
from .tts import TTSSession

__all__ = [
    "TTSBackend",
    "TTSMiniMaxSyncBackend",
    "TTSMiniMaxSyncConfiguration",
    "TTSMiniMaxWSBackend",
    "TTSMiniMaxWSConfiguration",
    "TTSMiniMaxWSStream",
    "TTSResult",
    "TTSSession",
    "TTSStream",
    "TTSStreamEvent",
    "TTSStreamingBackend",
]
