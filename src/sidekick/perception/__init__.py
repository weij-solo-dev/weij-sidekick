"""sidekick.perception — event bus, presence from the camera, speech-direction events, watcher base."""

from .audio import AudioWatcher
from .camera import CameraWatcher
from .perception import PerceptionSession
from .schemas import PerceptionEvent, Presence, Severity
from .watcher import Watcher

__all__ = [
    "AudioWatcher",
    "CameraWatcher",
    "PerceptionEvent",
    "PerceptionSession",
    "Presence",
    "Severity",
    "Watcher",
]
