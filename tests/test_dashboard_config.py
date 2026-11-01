"""Config routes: providers catalog, schema, the generic section route, credentials (write-only),
slots, languages, the TV zone / sector, the readiness routes and the backup."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sidekick.body import BodyNullBackend, BodySession
from sidekick.config import ConfigSession
from sidekick.dashboard import DashboardContext, build_app
from sidekick.doctor import DoctorSession
from sidekick.storage import StorageSession


def _client(tmp_path):
    storage = StorageSession(tmp_path / "home")
    StorageSession.shared = storage
    storage.ensure_layout()
    config = ConfigSession(storage)
    spec = ConfigSession.default_spec()
    config.save(spec)
    body = BodySession(BodyNullBackend())
    body.connect()
    doctor = DoctorSession(config, storage)
    doctor.setup(body=body)
    ctx = DashboardContext(config, spec, body=body, doctor=doctor)
    return TestClient(build_app(ctx)), config, body


def test_providers_schema_and_sections(tmp_path):
    client, config, body = _client(tmp_path)
    try:
        cat = client.get("/api/config/providers").json()
        minimax = next(p for p in cat["providers"] if p["id"] == "minimax")
        assert minimax["credentials"] == ["api_key"] and not minimax["configured"]
        assert "llm.fast" in minimax["slots"] and "tts.primary" in cat["slots"]
        assert "llm" in minimax["models"] and minimax["voices"]["yue"]
        assert cat["slot_names"]["asr"] == ["primary", "local", "kws"]
        schema = client.get("/api/config/schema").json()
        master = next(
            f
            for f in next(f for f in schema["body"] if f["name"] == "sway")["fields"]
            if f["name"] == "master"
        )
        assert master["type"] == "number" and master["min"] == 0.0 and master["max"] == 1.5
        assert "liveliness" in master["description"]
        gate = next(f for f in schema["interaction"] if f["name"] == "speaker_gate")
        assert gate["type"] == "enum" and gate["choices"] == ["off", "soft", "strict"]
        triggers = next(f for f in schema["interaction"] if f["name"] == "triggers")
        assert triggers["type"] == "flags"
        answer = next(f for f in schema["interaction"] if f["name"] == "answer_timeout_s")
        assert answer["default"] == 15.0 and "question" in answer["description"]  # block #89
        quiet = next(f for f in schema["automation"] if f["name"] == "quiet_hours")
        assert (
            quiet["type"] == "list"
            and quiet["nullable"] is True
            and quiet["default"] == ["23:00", "07:30"]
        )
        assert "subagents" not in {f["name"] for f in schema["agents"]}  # not a form field
        # the generic section route: deep merge, validation, apply note
        out = client.post("/api/config/agents", json={"values": {"main_max_steps": 9}}).json()
        assert (
            out["main_max_steps"] == 9 and out["applied"] is False and "next start" in out["note"]
        )
        assert config.load().agents.main_max_steps == 9
        out = client.post(
            "/api/config/interaction", json={"values": {"triggers": {"gaze": True}}}
        ).json()
        assert (
            out["triggers"]["gaze"] is True
            and out["triggers"]["wake_name"] is True
            and out["applied"]
        )
        dial = next(f for f in schema["body"] if f["name"] == "expressiveness")
        assert dial["type"] == "number" and dial["default"] == 1.0 and dial["max"] == 1.6
        out = client.post("/api/config/body", json={"values": {"expressiveness": 1.3}}).json()
        assert out["expressiveness"] == 1.3 and out["applied"] and body.expressiveness == 1.3
        assert body.motion is not None and body.motion.energy == 1.3
        assert client.post("/api/config/recording", json={"values": {"fps": 99}}).status_code == 422
        assert client.post("/api/config/nope", json={"values": {}}).status_code == 404
        assert client.post("/api/config/onboarding", json={"values": {}}).status_code == 404
    finally:
        body.close()


def test_credentials_slots_languages_tv(tmp_path):
    client, config, body = _client(tmp_path)
    try:
        r = client.post(
            "/api/config/credentials",
            json={"provider": "minimax", "values": {"api_key": "sk-cp-ROUTE000000000000000000"}},
        )
        assert r.status_code == 200 and r.json()["fields"] == ["api_key"]
        assert "ROUTE" not in client.get("/api/config").text
        assert "ROUTE" not in client.get("/api/config/providers").text
        assert next(
            p
            for p in client.get("/api/config/providers").json()["providers"]
            if p["id"] == "minimax"
        )["configured"]
        assert config.load().credentials["minimax"]["api_key"].endswith("0000")
        assert client.post("/api/config/languages", json={"default": "en"}).status_code == 200
        assert client.post("/api/config/languages", json={"default": "klingon"}).status_code == 422
        assert (
            client.post(
                "/api/config/slot",
                json={
                    "kind": "tts",
                    "name": "primary",
                    "provider": "minimax",
                    "voice": "Cantonese_WiseProfessor",
                    "speed": 1.1,
                },
            ).status_code
            == 200
        )
        slot = client.get("/api/config/providers").json()["slots"]["tts.primary"]
        assert slot["voice"] == "Cantonese_WiseProfessor" and slot["speed"] == 1.1
        # tv zone and sector are written independently
        assert client.post(
            "/api/config/tv", json={"values": {"tv_zone": [0.1, 0.2, 0.3, 0.3]}}
        ).json()["tv_zone"] == [0.1, 0.2, 0.3, 0.3]
        assert client.post("/api/config/tv", json={"values": {"tv_sector": [0.5, 0.3]}}).json()[
            "tv_zone"
        ] == [0.1, 0.2, 0.3, 0.3]
        loaded = config.load()
        assert loaded.contacts.tv_zone == [0.1, 0.2, 0.3, 0.3] and loaded.interaction.tv_sector == [
            0.5,
            0.3,
        ]
        assert client.post("/api/config/tv", json={"values": {"tv_zone": None}}).json()[
            "tv_sector"
        ] == [0.5, 0.3]
        assert config.load().contacts.tv_zone is None
    finally:
        body.close()


def test_readiness_routes_and_backup(tmp_path):
    client, _config, body = _client(tmp_path)
    try:
        health = client.get("/api/health").json()
        assert "onboarding_completed" not in health
        assert health["doctor"]["ready"] is False and health["doctor"]["tabs"]["agent"] == "bad"
        report = client.get("/api/doctor").json()
        assert report["layers"] == ["local"] and any(
            i["id"] == "slots.llm" for i in report["items"]
        )
        run = client.post("/api/doctor/run?layers=local,loopback").json()
        assert run["layers"] == ["local", "loopback"] and any(
            i["id"] == "loop.speaker" for i in run["items"]
        )
        backup = client.post("/api/system/backup").json()
        assert backup["path"].endswith(".tar.gz") and backup["size_mb"] >= 0
        assert (tmp_path / "home" / "cache" / "backups").exists()
    finally:
        body.close()
