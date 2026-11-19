"""Banana's service on the real modules over a null body: start → stop → start … in one process.

Block #83's contract: every module's session lives as long as the process, `setup` runs again
before each start, `stop` releases what `start` took — no thread, callback, subscription or tool
piles up however often the owner presses Start and Stop (block #87).
"""

from __future__ import annotations

import asyncio
import socket
import threading

import numpy as np
import pytest

from sidekick.app import App
from sidekick.asr import ASRResult, ASRSession
from sidekick.audio import AudioClip
from sidekick.config import ConfigSession
from sidekick.doctor import DoctorSession
from sidekick.llm import LLMResult, LLMSession
from sidekick.storage import StorageSession
from sidekick.tts import TTSResult, TTSSession, TTSStreamEvent
from sidekick.vad import VADSession

RUNTIME_THREADS = (
    "sidekick-frontend",
    "sidekick-motion",
    "sidekick-audio-in",
    "sidekick-audio-out",
    "sidekick-body-monitor",
    "sidekick-body-frames",
    "sidekick-record",
)


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def infer(self, messages, options=None):
        self.calls += 1
        return LLMResult(True, "pong", "fake", "fake", "fake-1", "****", latency_ms=5.0)


class FakeASR:
    async def transcribe(self, clip, language=None):
        return ASRResult(True, "", "fake", "fake", "fake-1", "****")


class FakeVAD:
    sample_rate = 16000
    window_size = 320

    def feed(self, samples):
        pass

    def is_speech(self):
        return False

    def pop_segments(self):
        return []

    def flush(self):
        pass

    def reset(self):
        pass


class FakeStream:
    def __init__(self) -> None:
        self.q: asyncio.Queue[TTSStreamEvent] = asyncio.Queue()

    async def send(self, text):
        pass

    async def flush(self):
        await self.q.put(TTSStreamEvent("flushed"))

    async def cancel(self):
        await self.q.put(TTSStreamEvent("canceled"))

    async def finish(self):
        await self.q.put(TTSStreamEvent("finished"))

    async def events(self):
        while True:
            event = await self.q.get()
            yield event
            if event.kind in ("finished", "error"):
                return

    async def aclose(self):
        await self.q.put(TTSStreamEvent("finished"))


class FakeTTS:
    async def open_stream(self):
        return FakeStream()

    async def infer(self, text):
        return TTSResult(True, AudioClip.silence(0.2).to_pcm16_bytes(), "f", "f", "m", "v", "*")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def app(tmp_path, monkeypatch):
    for cls in (LLMSession, ASRSession, TTSSession, VADSession):
        monkeypatch.setattr(cls, "shared", cls())
    home = tmp_path / "home"
    storage = StorageSession(home)
    storage.ensure_layout()
    spec = ConfigSession.default_spec()
    spec.body.mode = "null"
    spec.credentials["minimax"] = {"api_key": "sk-test-000000000000000000000000"}
    spec.recording.enabled = False
    spec.contacts.enroll_self = False
    spec.automation.heartbeat_minutes = 0
    spec.dashboard.port = _free_port()
    ConfigSession(storage).save(spec)
    # Banana stays stopped at boot, so the test can switch the news feeds off first.
    storage.write_json(storage.layout.service_path, {"wanted": "stopped", "by": "test"})
    llm = FakeLLM()

    def fake_apply(self, spec=None):  # every slot bound to a fake: no network, no model
        LLMSession.shared.setup("fast", llm)
        LLMSession.shared.setup("smart", llm)
        ASRSession.shared.setup("local", FakeASR())
        TTSSession.shared.setup("primary", FakeTTS())
        VADSession.shared.setup("primary", FakeVAD)
        return {}

    async def no_downloads(self, progress=None):
        return []

    monkeypatch.setattr(ConfigSession, "apply", fake_apply)
    monkeypatch.setattr(DoctorSession, "ensure_models", no_downloads)
    application = App(home)
    application.boot()
    application.llm = llm  # type: ignore[attr-defined]
    return application


def _runtime_threads() -> list[str]:
    return sorted(t.name for t in threading.enumerate() if t.name in RUNTIME_THREADS)


async def test_the_service_cycles_on_the_same_singletons(app):
    await app.start()
    service = app.service
    assert service.state == "stopped" and service.wanted == "stopped"
    assert app.contacts.ready  # set up while stopped: the data pages work
    await app.extensions.disable("news")  # no feed polling in a test
    service.request("start")
    await service.wait()
    transition = service.status()["transition"]
    assert service.state == "running", transition
    states = {s["id"]: s["state"] for s in transition["steps"]}
    assert states["config"] == "ok" and states["body"] == "ok" and states["agent"] == "ok"
    assert states["channels"] == "skipped" and states["record"] == "skipped"
    assert app.llm.calls == 2  # the agent proved fast and smart answer
    assert app.interaction.started and app.interaction.pipeline.keeper.connected
    running_threads = _runtime_threads()
    tools = len(app.agent.registry.all())
    subscribers = len(app.perception._subscribers)
    touch = len(app.body._touch_callbacks)
    states_cb = len(app.body._state_callbacks)
    faces = len(app.perception._face_listeners)
    for _ in range(3):
        service.request("stop")
        await service.wait()
        assert service.state == "stopped" and _runtime_threads() == []
        assert not app.body.connected and not app.interaction.started
        assert app.perception.camera is None and not LLMSession.shared.slots()
        assert app.contacts.ready and app.agent.dialogue is not None  # data pages still work
        service.request("start")
        await service.wait()
        assert service.state == "running", service.status()["transition"]
    assert _runtime_threads() == running_threads
    assert len(app.agent.registry.all()) == tools
    assert len(app.perception._subscribers) == subscribers
    assert len(app.body._touch_callbacks) == touch and len(app.body._state_callbacks) == states_cb
    assert len(app.perception._face_listeners) == faces
    readiness = app.doctor.local(force=True)
    assert readiness.service == "running" and any(i.id == "agent.llm.fast" for i in readiness.items)
    await app.stop()
    assert service.state == "stopped" and _runtime_threads() == []
    assert service.wanted == "running"  # a process exit is not the owner's Stop


async def test_a_failed_model_call_keeps_banana_stopped(app, monkeypatch):
    async def broken(messages, options=None):
        return LLMResult(False, None, "fake", "fake", "fake-1", "****", error_message="401")

    await app.start()
    await app.extensions.disable("news")
    monkeypatch.setattr(app.llm, "infer", broken)
    app.service.request("start")
    await app.service.wait()
    transition = app.service.status()["transition"]
    assert app.service.state == "stopped" and transition["ok"] is False
    steps = {s["id"]: s for s in transition["steps"]}
    assert steps["agent"]["state"] == "bad" and steps["agent"]["items"][0]["tab"] == "agent"
    assert steps["automation"]["state"] == "skipped"
    assert _runtime_threads() == [] and not app.body.connected
    await app.stop()
    np.testing.assert_equal(app.service.wanted, "stopped")
