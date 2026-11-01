"""Who is speaking from one day to the next (block #80).

The owner was befriended one night from three utterances and scored 0.41–0.54 against them the
next morning: a new `person:25` took their voice, and a short "Bobby" made `person:26`. These
tests pin the rules that keep one voice one identity: a contact at the threshold beats a closer
unnamed person, the uncertain band is not a stranger, contacts keep learning, a split voice is
merged back, and an utterance too short to tell is neither identified nor a new person.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

import numpy as np

from sidekick.audio import AudioClip
from sidekick.contact import ContactSession, ContactStore
from sidekick.contact.voice import MODEL_NAME, VoiceConfiguration, VoiceIdentifier
from sidekick.interaction import InteractionSession


def _unit(*parts: float, dim: int = 8) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[: len(parts)] = parts
    return (v / np.linalg.norm(v)).astype(np.float32)


def _toward(cos: float, axis: int, dim: int = 8) -> np.ndarray:
    """A unit vector at cosine `cos` from e0, leaning toward `axis`."""
    v = np.zeros(dim, dtype=np.float32)
    v[0] = cos
    v[axis] = math.sqrt(max(0.0, 1.0 - cos * cos))
    return v


class _Contacts(ContactSession):
    """A real contact session whose voice model is replaced by a table of vectors."""

    @property
    def ready(self) -> bool:
        return True


def _contacts(tmp_path: Path, voices: dict[float, np.ndarray] | None = None) -> _Contacts:
    contacts = _Contacts()
    contacts.store = ContactStore(tmp_path / "contact_v1.db")
    identifier = VoiceIdentifier(VoiceConfiguration(tmp_path / MODEL_NAME))
    table = voices or {}

    def embed(clip: AudioClip) -> np.ndarray:
        spectrum = np.abs(np.fft.rfft(clip.samples[:8000]))
        freq = float(np.argmax(spectrum)) * clip.sample_rate / 8000
        return table[min(table, key=lambda f: abs(f - freq))]

    identifier.embed = embed  # type: ignore[method-assign]
    contacts.voice = identifier
    return contacts


def _model(contacts: ContactSession) -> str:
    assert contacts.voice is not None
    return contacts.voice.model


def _tone(freq: float, seconds: float = 2.0) -> AudioClip:
    t = np.arange(int(16000 * seconds)) / 16000.0
    return AudioClip((0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32), 16000)


def _enroll(contacts: ContactSession, contact_id: str, vector: np.ndarray, samples: int) -> None:
    contacts.create(contact_id)
    for _ in range(samples):
        contacts.store.add_sample(contact_id, "voice", _model(contacts), vector)  # type: ignore[union-attr]


def test_a_contact_at_the_threshold_beats_a_closer_unnamed_person(tmp_path):
    contacts = _contacts(tmp_path)
    _enroll(contacts, "发瘟鸡", _unit(1), 3)
    person = contacts.new_person(_unit(0.5, 0.866))  # this morning's fragment of the same voice
    morning = _unit(0.6, 0.8)  # 0.6 to the contact, 0.99 to the fragment
    result = contacts.identify_vector(morning)
    assert result.contact_id == "发瘟鸡" and abs(result.score - 0.6) < 0.01
    assert result.candidates[0][0] == person  # the fragment is still the closest
    # the uncertain band: not identified, not a stranger
    unsure = contacts.identify_vector(_toward(0.42, 2))
    assert unsure.contact_id is None and unsure.near == "发瘟鸡"
    stranger = contacts.identify_vector(_toward(0.2, 3))
    assert stranger.contact_id is None and stranger.near is None
    # the robot's own voice is a named voice too
    contacts.store.add_sample("self", "voice", _model(contacts), _unit(0, 0, 0, 0, 1))  # type: ignore[union-attr]
    assert contacts.identify_vector(_unit(0, 0, 0, 0, 1)).is_self


def test_contacts_keep_learning_with_a_capped_weight(tmp_path):
    contacts = _contacts(tmp_path)
    _enroll(contacts, "发瘟鸡", _unit(1), 60)
    store = contacts.store
    assert store is not None
    assert contacts.learn_voice("发瘟鸡", _unit(0, 1))
    learned = store.embeddings("voice", _model(contacts), "发瘟鸡")[0]
    assert learned.samples == 61  # the true count
    moved = float(learned.vector[1] / learned.vector[0])
    assert abs(moved - 1 / 50) < 0.002  # weighted as 50, not 60: it keeps learning
    assert not contacts.learn_voice("self", _unit(1))
    assert not contacts.learn_voice("person:1", _unit(1))
    assert not contacts.learn_voice("nobody", _unit(1))


def test_a_split_voice_is_merged_back_into_its_contact(tmp_path):
    contacts = _contacts(tmp_path)
    _enroll(contacts, "发瘟鸡", _unit(1), 3)
    _enroll(contacts, "阿明", _unit(0, 0, 0, 0, 0, 0, 1), 3)
    morning = contacts.new_person(_toward(0.6, 1))
    for _ in range(2):
        contacts.fold_person(morning, voice=_toward(0.6, 1), session="a")
    assert contacts.merge_person(morning) is None  # three utterances are not enough
    contacts.fold_person(morning, voice=_toward(0.6, 1), session="a")
    assert contacts.merge_person(morning) == "发瘟鸡"
    assert contacts.person(morning) is None
    assert contacts.resolve_speaker(morning) == "发瘟鸡"
    store = contacts.store
    assert store is not None
    assert store.embeddings("voice", _model(contacts), "发瘟鸡")[0].samples == 7
    # a different voice stays a person; one between two contacts is not guessed
    other = contacts.new_person(_toward(0.3, 2))
    between = contacts.new_person(_unit(1, 0, 0, 0, 0, 0, 1))
    for _ in range(4):
        contacts.fold_person(other, voice=_toward(0.3, 2), session="b")
        contacts.fold_person(between, voice=_unit(1, 0, 0, 0, 0, 0, 1), session="b")
    assert contacts.merge_people() == []
    assert {p.id for p in contacts.people()} == {other, between}


def test_short_or_uncertain_speech_never_starts_a_new_person(tmp_path):
    voices = {440.0: _toward(0.42, 2), 880.0: _toward(0.1, 3), 1320.0: _toward(0.6, 1)}
    contacts = _contacts(tmp_path, voices)
    _enroll(contacts, "发瘟鸡", _unit(1), 3)
    session = InteractionSession()
    session.contacts = contacts
    # a 0.7 s "Bobby" is not identified at all
    short = asyncio.run(session._identify(_tone(1320), 0.7))
    assert short.speaker is None and short.vector is None
    assert asyncio.run(session._person_for(_tone(1320), None, short, 0.7)) == (None, None)
    # the uncertain band of a contact is not a stranger
    unsure = asyncio.run(session._identify(_tone(440), 2.0))
    assert unsure.speaker is None and unsure.near == "发瘟鸡"
    assert asyncio.run(session._person_for(_tone(440), None, unsure, 2.0)) == (None, None)
    # a real stranger with enough speech still becomes a person
    stranger = asyncio.run(session._identify(_tone(880), 2.0))
    person, _ = asyncio.run(session._person_for(_tone(880), None, stranger, 2.0))
    assert person == "person:1"
    # identified at the threshold: learned into the contact
    known = asyncio.run(session._identify(_tone(1320), 2.0))
    assert known.speaker == "发瘟鸡"
    store = contacts.store
    assert store is not None
    before = store.embeddings("voice", _model(contacts), "发瘟鸡")[0].samples
    asyncio.run(session._learn(known, "发瘟鸡"))
    assert store.embeddings("voice", _model(contacts), "发瘟鸡")[0].samples == before + 1
