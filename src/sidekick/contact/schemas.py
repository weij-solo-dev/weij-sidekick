"""sidekick.contact.schemas — contacts, embeddings and identification results

Overview
    A `Contact` is a household member (or the reserved `self` contact holding the robot's own
    voice): name, aliases, notes, preferred language, owner flag, remote ids per channel. An
    `Embedding` is one stored vector (voice or face) with the model that produced it.
    `Identification` is what `identify_voice` / `identify_face` return.
Design
    Frozen dataclasses; vectors are numpy float32 arrays stored as blobs. Contact ids are short
    slugs derived from the name (`dad`, `mum`, `self`) so they read well in the timeline and in
    memory scopes. No roles and no modes (AGENTS.md).
Depends on
    numpy.

See Also
--------
    AGENTS.md "Contact and identification".

"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import numpy.typing as npt

SELF_ID = "self"
OWNER_ALIAS = "owner"  # the dashboard's speaker for the owner; resolves to the owner contact
Vector = npt.NDArray[np.float32]


def slugify(name: str) -> str:
    """A short id from a display name (`爸爸` → `爸爸`, `Dad Wong` → `dad_wong`)."""
    text = unicodedata.normalize("NFKC", name).strip().lower()
    text = re.sub(r"[\s\-]+", "_", text)
    text = re.sub(r"[^\w]", "", text)
    return text[:32] or "contact"


@dataclass(frozen=True, slots=True)
class Contact:
    """A household member."""

    id: str
    name: str
    aliases: tuple[str, ...] = ()
    notes: str = ""
    language: str | None = None
    is_owner: bool = False
    remote_ids: dict[str, str] = field(default_factory=dict)
    created_ts: float = field(default_factory=time.time)
    last_seen_ts: float | None = None  # last voice / face identification (initiative rules)

    @property
    def is_self(self) -> bool:
        """The robot's own voice profile."""
        return self.id == SELF_ID


@dataclass(frozen=True, slots=True)
class Embedding:
    """One stored vector."""

    contact_id: str
    kind: Literal["voice", "face"]
    model: str
    vector: Vector
    id: int | None = None
    ts: float = field(default_factory=time.time)
    samples: int = 1


PERSON_PREFIX = "person:"


def is_person(speaker: str | None) -> bool:
    """Whether a speaker id names a person seen but not yet befriended (or a session guest)."""
    return bool(speaker) and (
        str(speaker).startswith(PERSON_PREFIX) or str(speaker).startswith("guest:")
    )


@dataclass(frozen=True, slots=True)
class Person:
    """Someone the robot has heard (and maybe seen) but not befriended yet."""

    id: str
    created_ts: float
    last_seen_ts: float
    sessions: int = 0
    utterances: int = 0
    voice_samples: int = 0
    face_samples: int = 0
    asked_ts: float | None = None
    declined_ts: float | None = None
    ready_ts: float | None = None
    last_session: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Dashboard / tool form."""
        return {
            "id": self.id,
            "created_ts": round(self.created_ts, 3),
            "last_seen_ts": round(self.last_seen_ts, 3),
            "sessions": self.sessions,
            "utterances": self.utterances,
            "voice_samples": self.voice_samples,
            "face_samples": self.face_samples,
            "asked_ts": self.asked_ts,
            "declined_ts": self.declined_ts,
            "ready_ts": self.ready_ts,
        }


@dataclass(frozen=True, slots=True)
class Identification:
    """Result of matching a clip or a frame against the enrolled contacts."""

    contact_id: str | None
    score: float
    kind: Literal["voice", "face"]
    threshold: float
    candidates: tuple[tuple[str, float], ...] = ()
    near: str | None = None  # unidentified, but within the uncertain band of this contact

    @property
    def known(self) -> bool:
        """Matched an enrolled contact."""
        return self.contact_id is not None

    @property
    def is_self(self) -> bool:
        """Matched the robot's own voice."""
        return self.contact_id == SELF_ID


def cosine(a: Vector, b: Vector) -> float:
    """Cosine similarity of two vectors."""
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def normalized(vector: Vector) -> Vector:
    """Unit-length copy."""
    norm = float(np.linalg.norm(vector))
    return vector.astype(np.float32) if norm == 0.0 else (vector / norm).astype(np.float32)
