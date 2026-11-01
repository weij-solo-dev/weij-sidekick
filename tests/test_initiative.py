"""Initiative rules (greet after an absence, sociability, quiet hours, cap), last-seen, settings."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from sidekick.contact import Contact, ContactSession, ContactStore
from sidekick.interaction import Initiative, InteractionSession
from sidekick.interaction.initiative import in_quiet_hours
from sidekick.perception import PerceptionEvent

NOON = datetime(2026, 10, 27, 12, 0).timestamp()
H = 3600.0


def _contacts(tmp_path) -> ContactSession:
    contacts = ContactSession()
    contacts.store = ContactStore(tmp_path / "contact_v1.db")
    contacts.store.upsert(Contact("ming", "阿明", language="yue"))
    contacts.store.upsert(Contact("owner", "爸爸", is_owner=True))
    return contacts


def test_contact_last_seen_migration_touch_and_rate_limit(tmp_path):
    contacts = _contacts(tmp_path)
    assert contacts.last_seen("ming") is None
    assert contacts.touch("ming", NOON)
    assert not contacts.touch("ming", NOON + 5.0)  # one write per 10 s
    assert contacts.last_seen("ming") == NOON
    assert contacts.touch("ming", NOON + 11.0) and contacts.last_seen("ming") == NOON + 11.0
    assert contacts.touch("ming", NOON + 12.0, force=True)
    assert not contacts.touch("person:1", NOON) and not contacts.touch("nobody", NOON)
    assert not contacts.touch("self", NOON)
    # upsert keeps last_seen; the Contact carries it
    contacts.store.upsert(Contact("ming", "阿明仔", language="yue"))
    assert (
        contacts.get("ming").name == "阿明仔" and contacts.get("ming").last_seen_ts == NOON + 12.0
    )


def test_quiet_hours_window():
    assert in_quiet_hours(("23:00", "07:30"), datetime(2026, 10, 27, 23, 30))
    assert in_quiet_hours(["23:00", "07:30"], datetime(2026, 10, 27, 6, 0))
    assert not in_quiet_hours(("23:00", "07:30"), datetime(2026, 10, 27, 12, 0))
    assert in_quiet_hours(("12:00", "14:00"), datetime(2026, 10, 27, 13, 0))
    assert not in_quiet_hours(None, datetime(2026, 10, 27, 13, 0))


def test_initiative_greets_a_known_person_after_an_absence(tmp_path):
    contacts = _contacts(tmp_path)
    ini = Initiative(contacts, "normal", ("23:00", "07:30"))
    # never seen → a greeting is due; unknown people never are
    assert ini.on_mutual_gaze(None, NOON) is None and ini.last_reason == "unknown person"
    assert ini.on_mutual_gaze("person:3", NOON) is None
    assert ini.on_mutual_gaze("ghost", NOON) is None and ini.last_reason == "no such contact"
    due = ini.on_mutual_gaze("ming", NOON)
    assert due and due["name"] == "阿明" and due["language"] == "yue" and due["absent_h"] is None
    assert contacts.last_seen("ming") == NOON  # offering counts as seeing
    # the same gaze a minute later: seen recently (and greeted recently)
    assert ini.on_mutual_gaze("ming", NOON + 60) is None and ini.last_reason == "greeted recently"
    contacts.touch("ming", NOON + 1.5 * H, force=True)
    assert ini.on_mutual_gaze("ming", NOON + 1.6 * H) is None
    assert ini.last_reason.startswith("seen 6 min ago")
    # back after 2 h → greet again, with the absence
    due = ini.on_mutual_gaze("ming", NOON + 3.6 * H)
    assert due and due["absent_h"] == 2.1
    # quiet hours
    assert ini.on_mutual_gaze("owner", datetime(2026, 10, 27, 23, 30).timestamp()) is None
    assert ini.last_reason == "quiet hours"
    # sociability levels
    quiet = Initiative(contacts, "quiet")
    assert quiet.on_mutual_gaze("owner", NOON) is None and quiet.last_reason == "sociability quiet"
    chatty = Initiative(contacts, "chatty")
    contacts.touch("owner", NOON, force=True)
    assert chatty.on_mutual_gaze("owner", NOON + 0.4 * H) is None
    assert chatty.on_mutual_gaze("owner", NOON + 0.6 * H)
    # daily cap, reset at midnight
    capped = Initiative(contacts, "normal")
    capped.offered_today, capped._today = 6, "2026-10-27"
    assert capped.on_mutual_gaze("ming", NOON + 9 * H) is None and capped.last_reason == "daily cap"
    assert capped.on_mutual_gaze("ming", NOON + 13 * H)  # next day

    # configure() follows the Settings page
    class _Cfg:
        sociability = "quiet"

    capped.configure(_Cfg())
    assert capped.sociability == "quiet" and capped.snapshot()["sociability"] == "quiet"


class _Perception:
    def __init__(self):
        self.events: list[PerceptionEvent] = []
        self.subscriptions = []

    def subscribe(self, pattern, callback):
        self.subscriptions.append((pattern, callback))

    async def publish(self, event):
        self.events.append(event)


class _Body:
    awake = True

    def moving(self):
        return False


class _Machine:
    from sidekick.interaction import InteractionState

    state = InteractionState.IDLE


def test_session_turns_mutual_gaze_into_greet_due(tmp_path):
    contacts = _contacts(tmp_path)
    session = InteractionSession()
    session.contacts = contacts
    session.perception = _Perception()
    session.body = _Body()  # type: ignore[assignment]
    session.machine = _Machine()  # type: ignore[assignment]
    session.initiative = Initiative(contacts, "normal")
    gaze = PerceptionEvent("gaze.mutual", data={"contact": "ming", "duration_s": 2.6})
    asyncio.run(session._on_gaze_event(gaze))
    assert [e.type for e in session.perception.events] == ["greet.due"]
    assert session.perception.events[0].data["contact"] == "ming"
    assert (
        session.recent[0]["event"] == "initiative" and "greet 阿明" in session.recent[0]["reason"]
    )
    # a second gaze right away: nothing; while held or engaged: nothing
    asyncio.run(session._on_gaze_event(gaze))
    session._held = "controller"
    asyncio.run(session._on_gaze_event(PerceptionEvent("gaze.mutual", data={"contact": "owner"})))
    assert len(session.perception.events) == 1
    # the robot extension answers greet.due with an in-person automation
    manifest = json.loads(Path("extensions/robot/extension.json").read_text())
    greet = next(a for a in manifest["automations"] if a["name"] == "greet")
    assert greet["event"] == "greet.due" and greet["delivery"] == "in_person"
    assert "initiative" in Path("extensions/robot/skill_initiative.md").read_text()


def test_sociability_setting_round_trips_through_the_dashboard(tmp_path):
    from fastapi.testclient import TestClient

    from sidekick.config import ConfigInteraction, ConfigSession
    from sidekick.dashboard import DashboardContext, build_app
    from sidekick.storage import StorageSession

    assert ConfigInteraction(sociability="chatty").sociability == "chatty"
    try:
        ConfigInteraction(sociability="loud")
    except Exception:
        pass
    else:  # pragma: no cover
        raise AssertionError("sociability must be one of quiet / normal / chatty")
    storage = StorageSession(tmp_path / "home")
    StorageSession.shared = storage
    storage.ensure_layout()
    config = ConfigSession(storage)
    spec = ConfigSession.default_spec()
    config.save(spec)
    session = InteractionSession()
    session.config = spec.interaction
    session.initiative = Initiative(None, "normal")
    ctx = DashboardContext(config, spec, interaction=session)
    client = TestClient(build_app(ctx))
    out = client.post(
        "/api/config/interaction", json={"values": {"sociability": "quiet", "idle_scan": False}}
    ).json()
    assert out["sociability"] == "quiet" and out["idle_scan"] is False
    assert session.initiative.sociability == "quiet" and session.config.idle_scan is False
    assert (
        client.post("/api/config/interaction", json={"values": {"sociability": "x"}}).status_code
        == 422
    )


def test_captions_listening_only_inside_a_session():
    session = InteractionSession()
    session._speech_since = time.time()
    assert session.captions()["listening"] is False and session.captions()["speech_open"] is True
    session.machine = _Machine()  # type: ignore[assignment]
    assert session.captions()["listening"] is False
    from sidekick.interaction import InteractionState

    class _Engaged:
        state = InteractionState.ENGAGED
        session = None

    session.machine = _Engaged()  # type: ignore[assignment]
    assert session.captions()["listening"] is True
    assert session.telemetry()["speech"] is True
