"""sidekick.contact — household contacts with voice and face identification."""

from .contact import ContactSession
from .face import DetectedFace, FaceConfiguration, FaceIdentifier, brighten_frame
from .schemas import (
    OWNER_ALIAS,
    PERSON_PREFIX,
    SELF_ID,
    Contact,
    Embedding,
    Identification,
    Person,
    cosine,
    is_person,
    normalized,
    slugify,
)
from .store import ContactStore
from .voice import VoiceConfiguration, VoiceIdentifier

__all__ = [
    "OWNER_ALIAS",
    "PERSON_PREFIX",
    "SELF_ID",
    "Contact",
    "ContactSession",
    "ContactStore",
    "DetectedFace",
    "Embedding",
    "FaceConfiguration",
    "FaceIdentifier",
    "Identification",
    "Person",
    "VoiceConfiguration",
    "VoiceIdentifier",
    "brighten_frame",
    "cosine",
    "is_person",
    "normalized",
    "slugify",
]
