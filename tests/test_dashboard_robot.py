"""Robot tab routes over the null body: hold gating, pose, gestures, the capability tests, files."""

from __future__ import annotations

import math
import threading
import time

import numpy as np
from fastapi.testclient import TestClient

from sidekick.body import BodyNullBackend, BodySession
from sidekick.config import ConfigSession
from sidekick.dashboard import DashboardContext, build_app
from sidekick.interaction import InteractionSession
from sidekick.record import encoder_name
from sidekick.storage import StorageSession


def _client(tmp_path):
    storage = StorageSession(tmp_path / "home")
    StorageSession.shared = storage
    storage.ensure_layout()
    config = ConfigSession(storage)
    spec = ConfigSession.default_spec()
    config.save(spec)
    backend = BodyNullBackend()
    body = BodySession(backend, poll_hz=20.0)
    body.connect()
    backend.set_frame(np.full((360, 640, 3), 90, dtype=np.uint8))
    ctx = DashboardContext(config, spec, body=body, interaction=InteractionSession())
    return TestClient(build_app(ctx)), body, backend, storage


def _wait(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _yaw(backend):
    return math.atan2(backend.head[1, 0], backend.head[0, 0]) if backend.head is not None else 0.0


def test_hold_gates_motion_and_pose_reaches_the_backend(tmp_path):
    client, body, backend, _ = _client(tmp_path)
    try:
        status = client.get("/api/robot").json()
        assert status["held"] is False and "nod" in status["gestures"]
        assert status["limits"]["body_yaw"] > 2.0 and status["expressions"]
        # motion needs the hold
        assert client.post("/api/robot/pose", json={"yaw": 0.3}).status_code == 409
        assert client.post("/api/robot/gesture", json={"name": "nod"}).status_code == 409
        held = client.post("/api/robot/control", json={"held": True}).json()
        assert held["held"] is True and held["holder"] == "dashboard"
        assert _wait(lambda: body.motion is not None and body.motion.state.manual)
        # the agent's look is dropped while held, the controller's pose is honoured
        body.look(yaw=-0.5, duration_s=0.1)
        r = client.post(
            "/api/robot/pose",
            json={
                "yaw": 0.4,
                "pitch": 0.1,
                "z": 0.01,
                "body_yaw": 1.0,
                "antennas": [0.5, -0.5],
                "duration_s": 0.1,
            },
        )
        assert r.status_code == 200
        assert _wait(lambda: abs(_yaw(backend) - 0.4) < 0.05)
        assert _wait(lambda: abs(backend.body_yaw - 1.0) < 0.05)
        assert _wait(lambda: abs(backend.antennas[0] - 0.5) < 0.05)
        assert abs(backend.head[2, 3] - 0.01) < 0.003
        assert body.control_status()["dropped"] >= 1
        assert client.post("/api/robot/gesture", json={"name": "nod"}).json()["ok"] is True
        assert client.post("/api/robot/gesture", json={"name": "wave"}).status_code == 422
        assert client.post("/api/robot/express", json={"name": "no-such"}).status_code == 404
        assert client.post("/api/robot/express", json={"name": "laugh"}).json()["ok"] is True
        assert _wait(lambda: body.motion.state.layers.get("express") == "laugh")
        assert client.post("/api/robot/breathing", json={"enabled": True}).status_code == 404
        # release: back to neutral, agent commands accepted again
        released = client.post("/api/robot/control", json={"held": False}).json()
        assert released["held"] is False
        assert _wait(lambda: abs(_yaw(backend)) < 0.05 and abs(backend.body_yaw) < 0.05)
        body.look(yaw=0.3, duration_s=0.1)
        assert _wait(lambda: abs(_yaw(backend) - 0.3) < 0.05)
    finally:
        body.close()


def _feed(backend, seconds: float, amplitude: float = 0.5) -> threading.Thread:
    """Feed 20 ms chunks in real time (the pump drains whatever is queued at once)."""

    def run() -> None:
        tone = (amplitude * np.sin(np.arange(320) / 10.0)).astype(np.float32)
        for _ in range(int(seconds / 0.02)):
            backend.feed_audio(tone)
            time.sleep(0.02)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def test_capability_tests_and_files(tmp_path):
    client, body, backend, storage = _client(tmp_path)
    try:
        # microphone: feed a tone while the capture runs
        feeder = _feed(backend, 1.0)
        mic = client.post("/api/robot/test/mic", json={"seconds": 0.3}).json()
        feeder.join()
        assert mic.get("error") is None, mic
        assert mic["ok"] is True and mic["samples"] >= 4800 and -8 < mic["peak_dbfs"] <= 0
        assert mic["file"].startswith("mic-") and mic["file"].endswith(".wav")
        wav = client.get(mic["url"])
        assert wav.status_code == 200 and wav.headers["content-type"] == "audio/wav"
        assert wav.content[:4] == b"RIFF"
        # speaker: tone, then the capture played back
        spoken_before = backend.spoken_seconds()
        spk = client.post("/api/robot/test/speaker", json={"kind": "tone", "seconds": 0.2}).json()
        assert spk["ok"] is True and spk["kind"] == "tone"
        assert _wait(lambda: backend.spoken_seconds() - spoken_before > 0.15)
        again = client.post("/api/robot/test/speaker", json={"kind": "mic", "seconds": 1}).json()
        assert again["ok"] is True and again["seconds"] == mic["seconds"]
        bad = client.post("/api/robot/test/speaker", json={"kind": "noise"}).json()
        assert bad["ok"] is False
        # snapshot
        snap = client.post("/api/robot/test/snapshot").json()
        assert snap["ok"] is True and snap["width"] == 640 and snap["bytes"] > 500
        jpg = client.get(snap["url"])
        assert jpg.status_code == 200 and jpg.content[:2] == b"\xff\xd8"
        # video: needs GStreamer; without it the route reports the reason instead of failing
        feeder = _feed(backend, 1.5, 0.1)
        video = client.post("/api/robot/test/video", json={"seconds": 1}).json()
        feeder.join()
        if encoder_name() is None:
            assert video["ok"] is False and video["error"]
        else:
            assert video["ok"] is True and video["frames"] >= 5 and video["bytes"] > 0
            assert client.get(video["url"]).status_code == 200
            assert client.get(video["mic_url"]).status_code == 200
        # files are listed newest first and only allowlisted names are served
        files = client.get("/api/robot").json()["files"]
        assert any(f["name"] == snap["file"] for f in files)
        assert client.get("/api/robot/file/../config.json").status_code == 404
        assert client.get("/api/robot/file/mic-20260101-000000.wav").status_code == 404
        assert client.get("/api/robot/file/other-20260101-000000.wav").status_code == 404
        assert (storage.layout.cache_dir / "robot" / snap["file"]).is_file()
    finally:
        body.close()
