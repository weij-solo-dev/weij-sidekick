"""Live feed routes: state frames, WebSocket, MJPEG stream, the 3D model and static scripts."""

from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from sidekick.body import BodyNullBackend, BodySession
from sidekick.config import ConfigSession
from sidekick.dashboard import DashboardContext, build_app
from sidekick.interaction import InteractionSession
from sidekick.storage import StorageSession


def _client(tmp_path):
    storage = StorageSession(tmp_path / "home")
    StorageSession.shared = storage
    storage.ensure_layout()
    config = ConfigSession(storage)
    spec = ConfigSession.default_spec()
    config.save(spec)
    backend = BodyNullBackend()
    body = BodySession(backend)
    body.connect()
    backend.set_frame(np.zeros((1080, 1920, 3), dtype=np.uint8))
    ctx = DashboardContext(config, spec, body=body, interaction=InteractionSession())
    return TestClient(build_app(ctx)), body, backend


def test_live_frame_and_websocket(tmp_path):
    client, body, backend = _client(tmp_path)
    try:
        backend.feed_audio(np.full(1600, 0.25, dtype=np.float32))
        body.speak(np.full(3200, 0.5, dtype=np.float32))
        body.wait_quiet(2.0)
        frame = client.get("/api/live/frame").json()
        assert frame["body"]["state"] == "awake" and len(frame["body"]["head"]) == 4
        assert frame["body"]["mic_peaks"] and max(frame["body"]["mic_peaks"]) > 0.2
        assert (
            frame["interaction"]["state"] == "unconfigured" and frame["captions"]["heard"] is None
        )
        with client.websocket_connect("/api/live?hz=20") as ws:
            first = ws.receive_json()
            second = ws.receive_json()
        assert first["seq"] == 1 and second["seq"] == 2 and "body" in second
    finally:
        body.close()


def test_mjpeg_model_and_scripts(tmp_path):
    client, body, _ = _client(tmp_path)
    try:
        with client.stream("GET", "/api/body/stream.mjpg?width=320&fps=20") as r:
            assert r.status_code == 200 and "multipart/x-mixed-replace" in r.headers["content-type"]
            chunk = next(r.iter_bytes(chunk_size=65536))
            assert b"Content-Type: image/jpeg" in chunk and b"\xff\xd8" in chunk
        model = client.get("/api/body/model").json()
        assert model["available"] is True
        names = [g["name"] for g in model["groups"]]
        assert names[:3] == ["base", "torso", "head"] and len(model["rods"]) == 6
        assert all(len(g["matrix"]) == 16 for g in model["groups"])
        assert model["head_rest_z"] == 0.177
        mesh = client.get("/api/body/mesh/head_front_3dprint.stl")
        assert mesh.status_code == 200 and len(mesh.content) > 10000
        assert client.get("/api/body/mesh/robot.urdf").status_code == 404
        assert client.get("/api/body/mesh/..%2Frobot.urdf").status_code == 404
        page = client.get("/").text
        assert 'data-tab="live"' in page and 'data-tab="record"' in page and "importmap" in page
        assert 'data-tab="body"' in page and 'data-tab="health"' not in page
        assert "topbar" not in page and 'id="rail-system"' in page and "data-theme-pick" not in page
        for name in (
            "live",
            "robot",
            "robot3d",
            "three.module.min",
            "stl_loader",
            "orbit_controls",
        ):
            assert client.get(f"/dashboard_{name}.js").status_code == 200, name
        assert client.get("/dashboard_nope.js").status_code == 404
    finally:
        body.close()
