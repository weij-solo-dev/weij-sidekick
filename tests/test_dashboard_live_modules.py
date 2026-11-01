"""Live = now (block #69): every module's `live()` once a second, the activity stream, host vitals."""

from __future__ import annotations

import time

import numpy as np

from sidekick.automation import AutomationSession, Job
from sidekick.body import BodyNullBackend, BodySession
from sidekick.channel import ChannelMessage, ChannelReply, ChannelSession
from sidekick.config import ConfigSession
from sidekick.dashboard import DashboardContext
from sidekick.dashboard.live import LiveFeed
from sidekick.dashboard.vitals import HostVitals, resident_mb
from sidekick.interaction import InteractionSession
from sidekick.perception import PerceptionSession
from sidekick.record import RecordSession
from sidekick.storage import RecentCalls, StorageSession


class Adapter:
    name = "telegram"
    capabilities = None
    received = 0
    sent = 0
    last_error = None
    last_update_at = None

    async def start(self, handler):
        self.handler = handler

    async def stop(self):
        pass

    async def send(self, reply):
        self.sent += 1
        return True


class Broken:
    def live(self):
        raise RuntimeError("boom")


def test_recent_calls_summary():
    calls = RecentCalls()
    calls.begin("fast")
    assert calls.summary()["fast"]["inflight"] == 1
    calls.end("fast", True, 1200.0, "agent.main.step0", first_ms=900.0)
    calls.begin("fast")
    calls.end("fast", False, 300.0, "agent.main.step0", error="http 500")
    summary = calls.summary()["fast"]
    assert summary["inflight"] == 0 and summary["calls_1h"] == 2 and summary["errors_1h"] == 1
    assert summary["median_ms"] == 1200 and summary["median_first_ms"] == 900
    assert summary["last"]["ok"] is False and summary["last"]["error"] == "http 500"
    assert calls.recent(1)[0]["ms"] == 300


def test_host_vitals_sample():
    rss, current = resident_mb()
    assert rss is not None and rss > 1.0 and isinstance(current, bool)
    sample = HostVitals().sample()
    assert {"load", "cores", "rss_mb", "cpu_pct", "threads", "loop_lag_ms", "temp_c"} <= set(sample)
    assert sample["threads"] >= 1


async def test_channel_live_and_activity():
    channels = ChannelSession()
    adapter = Adapter()
    channels.register(adapter)
    got: list[ChannelMessage] = []

    async def handler(message):
        got.append(message)

    channels.setup(handler)
    await channels.dispatch(ChannelMessage("telegram", "tg:1", "你好"))
    assert await channels.send(ChannelReply("你好呀", channel="telegram", to="tg:1"))
    live = channels.live()["telegram"]
    assert live["last_in_s"] == 0 and live["last_out_s"] == 0 and live["sent"] == 1
    rows = channels.activity()
    assert [r["module"] for r in rows] == ["channel", "channel"] and "→" in rows[0]["text"]


async def test_automation_live_counts_runs(tmp_path):
    class Agent:
        def register_tools(self, tools):
            pass

        def delivered_since(self, ts):
            return []

        async def run_job_turn(self, prompt, owner, channel, delivery, job_id):
            return "提你食藥"

    automation = AutomationSession()
    automation.setup(tmp_path / "automation_v1.db", None, Agent())  # type: ignore[arg-type]
    job = automation.jobs.save(Job("食藥", "at", "2020-01-01T08:00", "提我食藥"))  # type: ignore[union-attr]
    await automation.run_job(job)
    live = automation.live()
    assert live["runs_today"] == 1 and live["job"] is None
    rows = automation.activity()
    assert rows and "食藥" in rows[0]["text"] and "提你食藥" in rows[0]["text"]


def test_feed_pushes_modules_once_a_second_and_survives_a_broken_module(tmp_path):
    storage = StorageSession(tmp_path / "home")
    StorageSession.shared = storage
    storage.ensure_layout()
    config = ConfigSession(storage)
    spec = ConfigSession.default_spec()
    backend = BodyNullBackend()
    body = BodySession(backend)
    body.connect()
    backend.set_frame(np.zeros((720, 1280, 3), dtype=np.uint8))
    ctx = DashboardContext(
        config,
        spec,
        body=body,
        interaction=InteractionSession(),
        perception=PerceptionSession(),
        channels=ChannelSession(),
        record=RecordSession(),
        extensions=Broken(),
    )
    try:
        feed = LiveFeed(ctx)
        first = feed.frame()
        second = feed.frame()
        assert "modules" in first and "modules" not in second and "activity" in first
        modules = first["modules"]
        assert modules["body"]["state"] == "awake" and modules["body"]["manual"] is False
        assert modules["interaction"]["state"] == "off" and modules["interaction"]["turn"] is None
        assert modules["perception"]["presence"]["someone_present"] is False
        assert modules["record"]["state"] == "off"
        assert modules["extension"] == {"error": "RuntimeError('boom')"}
        assert set(modules["services"]) == {"llm", "asr", "tts"}
        assert modules["system"]["host"]["cores"] and "warning" in modules["system"]["log"]
        assert "held" in first["interaction"] and first["interaction"]["held"] is None
        feed.modules_at = time.time() - 2.0
        assert "modules" in feed.frame()
    finally:
        body.close()
