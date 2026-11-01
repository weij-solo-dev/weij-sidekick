"""sidekick.vad — voice activity detection service: slots, backend protocol, silero via sherpa-onnx."""

from .schemas import VADBackend, VADFactory, VADSegment
from .silero_sherpa import VADSileroBackend, VADSileroConfiguration, VADSileroFactory
from .vad import VADSession

__all__ = [
    "VADBackend",
    "VADFactory",
    "VADSegment",
    "VADSession",
    "VADSileroBackend",
    "VADSileroConfiguration",
    "VADSileroFactory",
]
