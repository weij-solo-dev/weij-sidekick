"""Replay routes over a recorded chunk: overview, chunk list, telemetry, tracks and media with ranges."""

from __future__ import annotations

import time

import numpy as np
from fastapi.testclient import TestClient

from sidekick.agent import AgentSession
from sidekick.body import BodyNullBackend, BodySession
from sidekick.config import ConfigAgents, ConfigSession
from sidekick.dashboard import DashboardContext, build_app
from sidekick.llm import LLMSession
from sidekick.record import RecordSession, RecordSettings
from sidekick.record.chunks import list_chunks
from sidekick.storage import StorageSession


def test_replay_routes(tmp_path):
    storage = StorageSession(tmp_path / "home")
    StorageSession.shared = storage
    storage.ensure_layout()
    config = ConfigSession(storage)
    spec = ConfigSession.default_spec()
    config.save(spec)
    backend = BodyNullBackend()
    body = BodySession(backend)
    body.connect()
    backend.set_frame(np.zeros((180, 320, 3), dtype=np.uint8))
    agent = AgentSession(LLMSession())
    agent.setup(home=tmp_path / "home", agents=ConfigAgents())
    record = RecordSession()
    root = storage.layout.recordings_dir
    record.setup(
        RecordSettings(root=root, chunk_s=1.0, min_free_gb=0.0, width=320, height=180, fps=5.0),
        body,
        extra=lambda: {"state": "engaged", "who": "owner", "ducked": False},
    )
    record.start()
    try:
        from sidekick.agent import DialogueMessage

        time.sleep(0.3)  # land inside the first chunk, not before its start
        agent.dialogue.append(DialogueMessage("voice", "owner", "user", "你好"))
        deadline = time.time() + 5.0
        while time.time() < deadline and len(list_chunks(root)) < 2:
            backend.feed_audio(np.full(1600, 0.2, dtype=np.float32))
            time.sleep(0.1)
    finally:
        record.stop()
        body.close()
    ctx = DashboardContext(config, spec, agent=agent, record=record)
    client = TestClient(build_app(ctx))
    overview = client.get("/api/record").json()
    assert overview["status"]["chunks"] >= 2 and len(overview["days"]) == 1
    chunks = client.get(f"/api/record/chunks?day={overview['days'][0]}").json()
    first = chunks[0]
    assert first["open"] is False and first["telemetry_rows"] > 0
    assert client.get(f"/api/record/{first['id']}").json()["id"] == first["id"]
    rows = client.get(f"/api/record/{first['id']}/telemetry").json()
    assert rows and rows[0]["x"]["state"] == "engaged"
    tracks = client.get(f"/api/record/{first['id']}/tracks?bin_s=0.1").json()
    assert tracks["audio"]["mic"]["peaks"] and max(tracks["audio"]["mic"]["peaks"]) > 0.1
    assert tracks["dialogue"] and tracks["dialogue"][0]["content"] == "你好"
    wav = client.get(f"/api/record/{first['id']}/file/mic.wav", headers={"Range": "bytes=0-99"})
    assert wav.status_code == 206 and len(wav.content) == 100 and wav.headers["content-range"]
    assert client.get(f"/api/record/{first['id']}/file/chunk.json").status_code == 404
    assert client.get("/api/record/2020-01-01/00-00-00").status_code == 404
    assert client.get("/api/record/../etc/passwd/telemetry").status_code in (404, 422)
    assert client.get("/").text.count('id="rp-video"') == 1
    assert client.get("/dashboard_replay.js").status_code == 200
