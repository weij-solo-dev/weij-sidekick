"""Befriending: people seen in the contact store, attribution + readiness, the robot tools, routes."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import numpy as np
import pytest

from sidekick.contact import ContactSession, ContactStore, Person, is_person
from sidekick.interaction import InteractionSession
from sidekick.perception import PerceptionEvent


def _vec(seed: int, dim: int = 8) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[seed % dim] = 1.0
    return v


def test_people_store_lifecycle(tmp_path):
    store = ContactStore(tmp_path / "contact_v1.db")
    a = store.next_person_id()
    b = store.next_person_id()
    assert a == "person:1" and b == "person:2" and is_person(a) and not is_person("owner")
    store.create_person(a)
    store.add_sample(a, "voice", "cam++", _vec(1))
    store.add_sample(a, "voice", "cam++", _vec(1))
    store.add_sample(a, "face", "sface", _vec(2))
    store.touch_person(a, utterance=True, session="s1")
    store.touch_person(a, utterance=True, session="s1")
    store.touch_person(a, utterance=True, session="s2")
    person = store.person(a)
    assert isinstance(person, Person)
    assert person.utterances == 3 and person.sessions == 2
    assert person.voice_samples == 2 and person.face_samples == 1
    assert [p.id for p in store.people()] == [a]
    store.mark_person(a, "asked_ts")
    assert store.person(a).asked_ts is not None
    with pytest.raises(ValueError):
        store.mark_person(a, "name")
    # promotion moves the centroids to the contact (merging with existing ones)
    from sidekick.contact import Contact

    store.upsert(Contact("ming", "阿明"))
    store.add_sample("ming", "voice", "cam++", _vec(3))
    moved = store.move_embeddings(a, "ming")
    store.delete_person(a, keep_embeddings=True)
    assert moved == 2 and store.person(a) is None
    voice = store.embeddings("voice", "cam++", "ming")[0]
    assert voice.samples == 3 and store.embeddings("face", "sface", "ming")[0].samples == 1
    assert store.embeddings("voice", "cam++", a) == []
    # pruning forgets people not seen for a while
    store.create_person(b, now=time.time() - 10 * 86400)
    store.add_sample(b, "voice", "cam++", _vec(4))
    assert store.prune_people(7) == 1 and store.people() == []
    assert store.embeddings("voice", "cam++", b) == []


class _Voice:
    model = "cam++"

    class configuration:
        min_clip_s = 0.1
        enroll_min_clip_s = 0.1
        threshold = 0.5

    @staticmethod
    def embed(clip):
        spectrum = np.abs(np.fft.rfft(clip.samples[:4000]))
        return _vec(int(np.argmax(spectrum)) // 100)


class _Face:
    model = "sface"

    class configuration:
        threshold = 0.363


class _Contacts(ContactSession):
    """A contact session with fake voice / face models (no ONNX needed)."""

    @property
    def ready(self) -> bool:
        return True


def _session(tmp_path) -> ContactSession:
    contacts = _Contacts()
    contacts.store = ContactStore(tmp_path / "contact_v1.db")
    contacts.voice = _Voice()  # type: ignore[assignment]
    contacts.face = _Face()  # type: ignore[assignment]
    return contacts


def _tone(freq, seconds=1.0):
    from sidekick.audio import AudioClip

    t = np.arange(int(16000 * seconds)) / 16000.0
    return AudioClip((0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32), 16000)


def test_contact_session_people_ready_and_promote(tmp_path):
    contacts = _session(tmp_path)
    pid = contacts.new_person(_vec(1))
    assert pid == "person:1" and contacts.person(pid).voice_samples == 1
    for _i in range(4):
        contacts.fold_person(pid, voice=_vec(1), session="a")
    assert not contacts.person_ready(pid)  # 5 utterances, 1 session
    for _i in range(2):
        contacts.fold_person(pid, voice=_vec(1), face=_vec(5), session="b")
    person = contacts.person(pid)
    assert person.utterances == 7 and person.sessions == 2 and person.face_samples == 2
    assert contacts.person_ready(pid)
    contacts.mark_person(pid, "ready")
    assert not contacts.person_ready(pid)  # asked at most once a day
    contacts.mark_person(pid, "declined")
    assert not contacts.person_ready(pid)
    contact = contacts.promote_person(pid, "阿明", "yue")
    assert contact is not None and contact.name == "阿明" and contacts.people() == []
    assert contacts.store.embeddings("voice", "cam++", contact.id)[0].samples == 7
    assert contacts.promote_person(pid, "again") is None
    assert contacts.display_name(contact.id) == "阿明"
    # eight utterances in one session are enough too
    other = contacts.new_person(_vec(2))
    for _ in range(7):
        contacts.fold_person(other, voice=_vec(2), session="c")
    assert contacts.person_ready(other)
    assert contacts.forget_person(other) and contacts.people() == []


class _Perception:
    """Faces from the detector plus a bus that records what interaction publishes."""

    def __init__(self):
        self.events: list[PerceptionEvent] = []
        self.face_rows = [{"x": 0.55, "y": 0.2, "w": 0.2, "h": 0.3, "score": 0.9, "contact": None}]
        self.vector = _vec(6)

    def faces(self):
        return self.face_rows

    def local_face_vector(self):
        return self.vector

    async def publish(self, event):
        self.events.append(event)


def test_interaction_attributes_voice_and_face_and_publishes_ready(tmp_path):
    contacts = _session(tmp_path)
    session = InteractionSession()
    session.contacts = contacts
    perception = _Perception()
    session.perception = perception
    # a new voice becomes a person at once; the same voice keeps the id
    pid, vector = asyncio.run(session._person_for(_tone(440), None))
    assert pid == "person:1" and vector is None
    same, vector = asyncio.run(session._person_for(_tone(440), "person:1"))
    assert same == "person:1" and vector is not None
    # the face straight ahead (x centre 0.65 → azimuth ≈ -13°) matches a DoA of -10°
    for _ in range(8):
        asyncio.run(session._attribute("person:1", vector, -0.17))
    person = contacts.person("person:1")
    assert person.utterances == 9 and person.face_samples == 8  # the revealing one + 8
    assert [e.type for e in perception.events] == ["person.ready"]
    assert perception.events[0].data["person_id"] == "person:1"
    # a face far from the sound direction is not attributed
    before = contacts.person("person:1").face_samples
    asyncio.run(session._attribute("person:1", vector, 1.0))
    assert contacts.person("person:1").face_samples == before
    # renaming after befriending follows the open session / caption
    session._heard = ("你好", time.time(), "person:1")
    session.rename_speaker("person:1", "ming")
    assert session._heard[2] == "ming"


def test_manifest_automations_and_robot_tools(tmp_path):
    from sidekick.extension import ExtensionManifest

    manifest = ExtensionManifest.model_validate(
        json.loads(Path("extensions/robot/extension.json").read_text())
    )
    assert [a.name for a in manifest.automations] == ["befriend", "greet"]
    assert manifest.automations[0].event == "person.ready"
    assert manifest.automations[0].delivery == "in_person"
    assert manifest.automations[1].event == "greet.due"
    assert manifest.automations[1].delivery == "in_person"
    assert "skill_befriending.md" in manifest.skills and "skill_initiative.md" in manifest.skills

    from sidekick.extension import ExtensionContext
    from sidekick.extension.loader import load_factory

    contacts = _session(tmp_path)
    pid = contacts.new_person(_vec(1))
    contacts.fold_person(pid, voice=_vec(1), session="a")
    ctx = ExtensionContext("robot", {}, tmp_path, contacts=contacts)
    tools = {
        t.name: t for t in load_factory(Path("extensions/robot"), "tools.py", "robot", "TOOLS")(ctx)
    }
    assert {"people_seen", "befriend", "decline_befriend"} <= set(tools)
    assert tools["befriend"].confirm is False

    from sidekick.agent import ToolContext
    from sidekick.channel import ChannelMessage

    tctx = ToolContext(ChannelMessage("voice", pid, "我叫阿明"), "main")
    seen = asyncio.run(tools["people_seen"].handler({}, tctx))
    assert seen.ok and pid in seen.content and "2 time(s)" in seen.content
    declined = asyncio.run(tools["decline_befriend"].handler({"person_id": pid}, tctx))
    assert declined.ok and contacts.person(pid).declined_ts is not None
    bad = asyncio.run(tools["befriend"].handler({"person_id": "owner", "name": "x"}, tctx))
    assert not bad.ok
    made = asyncio.run(tools["befriend"].handler({"name": "阿明", "language": "yue"}, tctx))
    assert made.ok and "阿明" in made.content and contacts.people() == []
    assert contacts.get("a-ming") or [c for c in contacts.contacts() if c.name == "阿明"]


def test_people_routes(tmp_path):
    from fastapi.testclient import TestClient

    from sidekick.config import ConfigSession
    from sidekick.dashboard import DashboardContext, build_app
    from sidekick.storage import StorageSession

    storage = StorageSession(tmp_path / "home")
    StorageSession.shared = storage
    storage.ensure_layout()
    config = ConfigSession(storage)
    spec = ConfigSession.default_spec()
    config.save(spec)
    contacts = _session(tmp_path)
    pid = contacts.new_person(_vec(1))
    ctx = DashboardContext(config, spec, contacts=contacts, interaction=InteractionSession())
    client = TestClient(build_app(ctx))
    people = client.get("/api/contacts/people").json()
    assert people[0]["id"] == pid and people[0]["voice_samples"] == 1
    assert client.get("/api/contacts").json()["people"][0]["id"] == pid
    promoted = client.post(f"/api/contacts/people/{pid}/promote", json={"name": "阿明"}).json()
    assert promoted["name"] == "阿明"
    assert client.post(f"/api/contacts/people/{pid}/promote", json={"name": "x"}).status_code == 404
    other = contacts.new_person(_vec(2))
    assert client.delete(f"/api/contacts/people/{other}").json()["ok"] is True
    assert client.get("/api/contacts/people").json() == []


def test_identities_never_merge_by_name(tmp_path):
    """A new contact takes a free id; `owner` and a befriended person resolve to contacts (#63)."""
    contacts = _session(tmp_path)
    dad = contacts.create("爸爸", is_owner=True)
    contacts.store.add_sample(dad.id, "voice", "cam++", _vec(1))
    pid = contacts.new_person(_vec(2))
    stranger = contacts.promote_person(pid, "爸爸")
    assert stranger is not None and stranger.id == "爸爸_2" and stranger.name == "爸爸"
    assert contacts.get(dad.id).is_owner  # the owner's profile was not overwritten
    assert contacts.store.embeddings("voice", "cam++", dad.id)[0].samples == 1  # nor merged
    assert contacts.create("Owner").id == "owner_2" and contacts.create("self").id == "self_2"
    assert contacts.resolve_speaker(pid) == stranger.id
    assert contacts.resolve_speaker("owner") == dad.id
    assert contacts.resolve_speaker("person:99") == "person:99"


class _Enrolling:
    """The interaction surface `enroll_voice` uses."""

    started = True

    def __init__(self, session_open: bool = True) -> None:
        self.session_open = session_open
        self.enrolling: tuple[str, int] | None = None
        self.renamed: list[tuple[str, str]] = []

    def start_enrollment(self, contact_id, count):
        if not self.session_open:
            return False
        self.enrolling = (contact_id, count)
        return True

    def rename_speaker(self, old, new):
        self.renamed.append((old, new))


def test_enroll_voice_befriends_or_learns_its_own_contact(tmp_path):
    """No voice is learned into someone else by name (the 發返雞 case, block #63)."""
    from sidekick.agent import ToolContext
    from sidekick.channel import ChannelMessage
    from sidekick.extension import ExtensionContext
    from sidekick.extension.loader import load_factory

    contacts = _session(tmp_path)
    pid = contacts.new_person(_vec(1))
    for _ in range(3):
        contacts.fold_person(pid, voice=_vec(1), session="a")
    dad = contacts.create("爸爸", is_owner=True)
    contacts.store.add_sample(dad.id, "voice", "cam++", _vec(3))
    interaction = _Enrolling()
    ctx = ExtensionContext("robot", {}, tmp_path, contacts=contacts, interaction=interaction)
    tools = {
        t.name: t for t in load_factory(Path("extensions/robot"), "tools.py", "robot", "TOOLS")(ctx)
    }
    enroll = tools["enroll_voice"].handler

    def as_(speaker):
        return ToolContext(ChannelMessage("voice", speaker, "記住我"), "main")

    # a stranger giving the owner's name is befriended as someone new, samples kept
    made = asyncio.run(enroll({"name": "爸爸", "language": "yue"}, as_(pid)))
    new_id = made.data["contact_id"]
    assert made.ok and new_id == "爸爸_2" and contacts.people() == []
    assert interaction.enrolling == (new_id, 3) and interaction.renamed == [(pid, new_id)]
    assert contacts.store.embeddings("voice", "cam++", new_id)[0].samples == 4
    assert contacts.store.embeddings("voice", "cam++", dad.id)[0].samples == 1
    # later in the same turn the old id is that contact
    again = asyncio.run(enroll({"name": "爸爸"}, as_(pid)))
    assert again.ok and again.data["contact_id"] == new_id
    # a named speaker learns into their own contact, under their own name only
    wrong = asyncio.run(enroll({"name": "媽媽"}, as_(dad.id)))
    assert not wrong.ok and "爸爸" in wrong.content and interaction.enrolling[0] == new_id
    own = asyncio.run(enroll({"name": "爸爸"}, as_(dad.id)))
    assert own.ok and interaction.enrolling == (dad.id, 3)
    # no conversation open: known, nothing more to learn
    interaction.session_open = False
    quiet = asyncio.run(enroll({"name": "爸爸"}, as_(dad.id)))
    assert quiet.ok and "no conversation" in quiet.content


def test_voice_enrollment_stays_in_its_session(tmp_path):
    """Learning ends with the session or the window; another known voice is skipped (#63)."""
    from types import SimpleNamespace

    from sidekick.interaction.interaction import ENROLL_WINDOW_S
    from sidekick.interaction.schemas import FrontEndEvent

    contacts = _session(tmp_path)
    dad = contacts.create("爸爸")
    session = InteractionSession()
    session.contacts = contacts
    assert session.start_enrollment(dad.id) is False  # no session open
    first = SimpleNamespace(speaker=None, addressee=None)
    session.machine = SimpleNamespace(session=first)  # type: ignore[assignment]
    assert session.start_enrollment(dad.id, 2) is True and first.speaker == dad.id
    now = time.time()
    assert session._enrolling(now) == dad.id
    event = FrontEndEvent("speech_end", now, duration_s=1.0)
    asyncio.run(session._maybe_enroll(_tone(440), event, "mum"))  # someone else: skipped
    assert contacts.store.embeddings("voice", "cam++", dad.id) == []
    asyncio.run(session._maybe_enroll(_tone(440), event, dad.id))
    assert contacts.store.embeddings("voice", "cam++", dad.id)[0].samples == 1
    assert session._enrollment is not None and session._enrollment[1] == 1
    assert session._enrolling(now + ENROLL_WINDOW_S + 1) is None  # the window is over
    session.start_enrollment(dad.id)
    session.machine.session = SimpleNamespace(speaker=None, addressee=None)  # a new session
    asyncio.run(session._maybe_enroll(_tone(440), event, dad.id))
    assert session._enrollment is None
    assert contacts.store.embeddings("voice", "cam++", dad.id)[0].samples == 1


def test_contact_edit_keeps_prints_and_delete_drops_facts(tmp_path):
    """Editing a contact is in place; deleting one takes their facts along (#63)."""
    from fastapi.testclient import TestClient

    from sidekick.agent import AgentSession
    from sidekick.config import ConfigAgents, ConfigSession
    from sidekick.dashboard import DashboardContext, build_app
    from sidekick.llm import LLMSession
    from sidekick.storage import StorageSession

    storage = StorageSession(tmp_path / "home")
    StorageSession.shared = storage
    storage.ensure_layout()
    config = ConfigSession(storage)
    spec = ConfigSession.default_spec()
    config.save(spec)
    agent = AgentSession(LLMSession())
    agent.setup(home=tmp_path / "home", agents=ConfigAgents())
    contacts = _session(tmp_path)
    ctx = DashboardContext(config, spec, agent=agent, contacts=contacts)
    client = TestClient(build_app(ctx))
    made = client.post("/api/contacts", json={"name": "阿明", "telegram": "42"}).json()
    contacts.store.add_sample(made["id"], "voice", "cam++", _vec(1))
    agent.memory.remember(made["id"], "鍾意行山")
    created = contacts.get(made["id"]).created_ts
    edited = client.put(
        f"/api/contacts/{made['id']}",
        json={"name": "明仔", "aliases": ["阿明"], "language": "yue", "is_owner": True},
    ).json()
    contact = contacts.get(made["id"])
    assert edited["id"] == made["id"] and contact.name == "明仔" and contact.is_owner
    assert (
        contact.aliases == ("阿明",) and contact.remote_ids == {} and contact.created_ts == created
    )
    assert contacts.store.embeddings("voice", "cam++", made["id"])[0].samples == 1
    assert agent.memory.recall([made["id"]])[0].text == "鍾意行山"
    assert client.put("/api/contacts/nobody", json={"name": "x"}).status_code == 404
    assert client.post("/api/contacts", json={"name": "阿明"}).json()["id"] == "阿明_2"
    assert client.delete(f"/api/contacts/{made['id']}").json()["ok"] is True
    assert agent.memory.recall([made["id"]]) == []
    assert contacts.store.embeddings("voice", "cam++", made["id"]) == []
