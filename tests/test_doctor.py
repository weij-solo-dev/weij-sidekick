"""Readiness (`doctor`): the local layer over a null body, the probe mapping, the loopback, the report."""

from __future__ import annotations

import asyncio

import numpy as np

from sidekick.body import BodyNullBackend, BodySession
from sidekick.config import ConfigProbeOutcome, ConfigSession
from sidekick.doctor import DoctorItem, DoctorReport, DoctorSession
from sidekick.storage import StorageSession


def _session(tmp_path, with_key: bool = False) -> tuple[DoctorSession, ConfigSession]:
    storage = StorageSession(tmp_path / "home")
    StorageSession.shared = storage
    storage.ensure_layout()
    config = ConfigSession(storage)
    spec = ConfigSession.default_spec()
    if with_key:
        spec.credentials["minimax"] = {"api_key": "sk-cp-TEST00000000000000000000"}
    config.save(spec)
    return DoctorSession(config, storage), config


def test_report_levels_and_summary():
    items = (
        DoctorItem("a", "A", "ok", "fine", "system"),
        DoctorItem("b", "B", "warn", "advice", "contacts"),
        DoctorItem("c", "C", "bad", "blocks", "agent"),
        DoctorItem("d", "D", "bad", "blocks too", "agent"),
    )
    report = DoctorReport(1.0, items, ("local",))
    assert report.bad == 2 and report.warn == 1 and report.ready is False
    assert report.summary() == "not ready · 2 blocking · 1 advisory"
    assert report.worst_by_tab() == {"contacts": "warn", "agent": "bad"}
    data = report.as_dict(failing_only=True)
    assert [i["id"] for i in data["items"]] == ["b", "c", "d"] and data["tabs"]["agent"] == "bad"
    assert DoctorReport(1.0, items[:1]).summary() == "ready"
    assert DoctorReport(1.0, items[:2]).summary() == "ready · 1 advisory"
    assert DoctorReport(0.0, ()).summary() == "not checked yet"
    assert DoctorReport(0.0, (), running="probe").summary() == "checking probe…"


def test_local_layer_names_what_is_missing(tmp_path):
    doctor, _config = _session(tmp_path)
    body = BodySession(BodyNullBackend())
    body.connect()
    try:
        doctor.setup(body=body)
        report = doctor.local(force=True)
        by_id = {item.id: item for item in report.items}
        assert by_id["python"].ok
        # no MiniMax key yet → the cloud slots block, and say which key is missing
        assert by_id["slots.llm"].level == "bad" and "api_key missing" in by_id["slots.llm"].detail
        assert by_id["slots.llm"].tab == "agent" and by_id["slots.tts"].tab == "voice"
        # the runtime rows (body, microphone, channels …) are the modules' own checks now,
        # collected through the service while it runs (block #86)
        assert "body" not in by_id and "mic" not in by_id and "channels" not in by_id
        assert "models.speech" in by_id and "disk" in by_id and report.ready is False
        assert report.layers == ("local",) and report.as_dict()["tabs"]["agent"] == "bad"
        # the cache: a second call within the TTL reuses the rows, force refreshes
        again = doctor.local()
        assert again.ts == report.ts
        doctor.LOCAL_TTL_S = 0.0
        assert doctor.local().ts >= report.ts
        snap = doctor.snapshot()
        assert snap["ready"] is False and all(i["level"] != "ok" for i in snap["items"])
    finally:
        body.close()


def test_probe_layer_maps_outcomes_and_persists(tmp_path):
    doctor, config = _session(tmp_path, with_key=True)

    async def fake_probe(spec):
        spec.region["minimax"] = "overseas"
        return {
            "llm.fast": ConfigProbeOutcome(
                "llm.fast",
                "ok",
                "pong",
                "minimax",
                "v1",
                "MiniMax-M2",
                "overseas",
                latency_ms=812.0,
            ),
            "tts.primary": ConfigProbeOutcome(
                "tts.primary", "credentials", "invalid api key", "minimax", "ws", "speech-2.6"
            ),
        }

    doctor.setup(probe=fake_probe)
    report = asyncio.run(doctor.run(["probe"]))
    by_id = {item.id: item for item in report.items}
    assert by_id["probe.llm.fast"].ok and by_id["probe.llm.fast"].latency_ms == 812.0
    assert by_id["probe.llm.fast"].tab == "agent" and by_id["probe.llm.fast"].layer == "probe"
    assert (
        by_id["probe.tts.primary"].level == "bad"
        and "invalid api key" in by_id["probe.tts.primary"].detail
    )
    assert report.layers == ("probe",)
    assert config.load().region["minimax"] == "overseas"  # the resolved region was saved
    # a later local run keeps the probe rows next to the fresh local rows
    full = doctor.local(force=True)
    assert full.layers == ("local", "probe") and "probe.llm.fast" in {i.id for i in full.items}


def test_loopback_over_the_null_body(tmp_path):
    doctor, _ = _session(tmp_path)
    backend = BodyNullBackend()
    body = BodySession(backend)
    body.connect()
    try:
        doctor.setup(body=body)
        doctor.PRE_S, doctor.TONE_S, doctor.POST_S = 0.1, 0.2, 0.1
        backend.set_frame(np.full((360, 640, 3), 90, dtype=np.uint8))
        report = asyncio.run(doctor.run(["loopback"]))
        by_id = {item.id: item for item in report.items}
        assert by_id["loop.speaker"].ok  # the null speaker drains
        assert by_id["loop.mic"].level == "warn"  # nothing arrives from the null microphone
        assert by_id["loop.camera"].ok and "fps" in by_id["loop.camera"].detail
        backend.set_frame(np.zeros((360, 640, 3), dtype=np.uint8))
        dark = asyncio.run(doctor.run(["loopback"]))
        assert {i.id: i for i in dark.items}["loop.camera"].level == "warn"
    finally:
        body.close()


def test_run_without_a_body_reports_and_never_overlaps(tmp_path):
    doctor, _ = _session(tmp_path)
    report = asyncio.run(doctor.run(["local", "loopback"]))
    by_id = {item.id: item for item in report.items}
    assert by_id["loop.body"].level == "warn"
    doctor._running = "probe"
    assert asyncio.run(doctor.run(["local"])).running == "probe"


class _Service:
    """The part of `ServiceSession` the doctor reads."""

    def __init__(self, state: str, checks: list[dict]) -> None:
        self.state = state
        self._checks = checks

    @property
    def running(self) -> bool:
        return self.state == "running"

    def checks(self) -> list[dict]:
        return self._checks if self.running else []


def test_local_layer_collects_the_running_modules_checks(tmp_path):
    """Block #86: the modules' own items join the prerequisites while the service runs."""
    doctor, _ = _session(tmp_path, with_key=True)
    checks = [
        {
            "id": "body.mic",
            "title": "microphone",
            "level": "bad",
            "detail": "no audio",
            "tab": "body",
        },
        {
            "id": "channels.remote",
            "title": "remote channels",
            "level": "off",
            "detail": "none",
            "tab": "channel",
        },
    ]
    doctor.setup(service=_Service("running", checks))
    report = doctor.local(force=True)
    by_id = {item.id: item for item in report.items}
    assert by_id["body.mic"].level == "bad" and by_id["body.mic"].tab == "body"
    assert by_id["channels.remote"].ok  # not configured is not a problem
    assert report.as_dict()["tabs"]["body"] == "bad" and report.service == "running"


def test_stopped_service_reports_the_prerequisites_only(tmp_path):
    doctor, _ = _session(tmp_path)  # no key: the LLM slots block a start
    doctor.setup(service=_Service("stopped", [{"id": "x", "title": "x", "level": "bad"}]))
    report = doctor.local(force=True)
    assert "x" not in {item.id for item in report.items}
    assert report.summary() == f"stopped · {report.bad} to fix before starting" and report.bad >= 1
    assert [i.id for i in doctor.prerequisites()][:1] == ["python"]
