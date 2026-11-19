"""The power control's routes, what a stopped Banana refuses, and the loopback guard (block #87)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from sidekick.body import BodyNullBackend, BodySession
from sidekick.config import ConfigSession
from sidekick.dashboard import DashboardContext, build_app
from sidekick.interaction import InteractionSession
from sidekick.service import ServiceBusy
from sidekick.storage import StorageSession


class Service:
    """The part of `ServiceSession` the routes use."""

    def __init__(self, state: str = "stopped") -> None:
        self.state = state
        self.requests: list[tuple[str, str]] = []
        self.busy = False

    @property
    def running(self) -> bool:
        return self.state == "running"

    def status(self) -> dict[str, Any]:
        return {"state": self.state, "wanted": "stopped", "busy": self.busy, "transition": None}

    def request(self, action: str, by: str = "dashboard") -> dict[str, Any]:
        if self.busy:
            raise ServiceBusy("a start is running")
        self.requests.append((action, by))
        self.state = "starting" if action == "start" else "stopping"
        return self.status()

    def live(self) -> dict[str, Any]:
        return {"state": self.state}


@pytest.fixture
def client(tmp_path):
    storage = StorageSession(tmp_path / "home")
    StorageSession.shared = storage
    storage.ensure_layout()
    config = ConfigSession(storage)
    spec = ConfigSession.default_spec()
    config.save(spec)
    body = BodySession(BodyNullBackend())
    service = Service()
    ctx = DashboardContext(
        config, spec, body=body, interaction=InteractionSession(), service=service
    )
    with TestClient(build_app(ctx)) as test_client:
        yield test_client, service


def test_power_control_routes(client):
    test_client, service = client
    assert test_client.get("/api/service").json()["state"] == "stopped"
    assert test_client.get("/api/health").json()["service"]["state"] == "stopped"
    reply = test_client.post("/api/service", json={"action": "start"})
    assert reply.status_code == 200 and reply.json()["state"] == "starting"
    assert service.requests == [("start", "dashboard")]
    service.busy = True
    assert test_client.post("/api/service", json={"action": "stop"}).status_code == 409
    assert test_client.post("/api/service", json={"action": "reboot"}).status_code == 422


def test_a_stopped_banana_refuses_what_needs_it(client):
    test_client, _ = client
    for method, path, body in (
        ("post", "/api/say", {"text": "hi"}),
        ("post", "/api/agent/chat", {"text": "hi"}),
        ("post", "/api/body/express", {"name": "nod"}),
        ("post", "/api/robot/control", {"held": True}),
        ("post", "/api/robot/test/snapshot", None),
        ("get", "/api/body/frame.jpg", None),
        ("post", "/api/agent/memory/write", None),
    ):
        reply = (
            getattr(test_client, method)(path, json=body)
            if body
            else getattr(test_client, method)(path)
        )
        assert reply.status_code == 409, path
        assert "stopped" in reply.json()["detail"], path
    # the data pages still answer
    assert test_client.get("/api/config").status_code == 200
    assert test_client.get("/api/logs").status_code == 200


def test_the_loopback_guard(client):
    test_client, _ = client
    evil = {"Origin": "https://evil.example"}
    refused = test_client.post("/api/service", json={"action": "start"}, headers=evil)
    assert refused.status_code == 403 and "cross-site" in refused.json()["detail"]
    rebound = test_client.get("/api/health", headers={"Host": "evil.example:8787"})
    assert rebound.status_code == 403
    tunnel = test_client.get("/api/health", headers={"Host": "localhost:9000"})
    assert tunnel.status_code == 200  # an SSH tunnel on another port still works
    own = test_client.post(
        "/api/service", json={"action": "start"}, headers={"Origin": "http://127.0.0.1:8787"}
    )
    assert own.status_code == 200
    with pytest.raises(WebSocketDisconnect):
        with test_client.websocket_connect("/api/live", headers=evil) as socket:
            socket.receive_json()


def test_the_route_runs_a_real_service_on_the_loop(tmp_path):
    """POST /api/service starts the transition task on the server's loop (it once ran on a
    worker thread, where `create_task` has no loop: a 500 and a stuck "stopping")."""
    from sidekick.service import ServiceSession

    log: list[str] = []

    class Module:
        async def start(self) -> None:
            log.append("start")

        async def stop(self) -> None:
            log.append("stop")

    class Config:
        spec: Any = object()

        def load(self) -> Any:
            return self.spec

        def apply(self, spec: Any) -> dict[str, str]:
            return {}

        def release(self) -> None:
            log.append("release")

    storage = StorageSession(tmp_path / "home")
    StorageSession.shared = storage
    storage.ensure_layout()
    config = ConfigSession(storage)
    spec = ConfigSession.default_spec()
    config.save(spec)
    service = ServiceSession()
    service.setup(
        config=Config(),  # type: ignore[arg-type]
        state_path=tmp_path / "service.json",
        prepare=lambda: None,
        modules=[("body", Module())],
    )
    ctx = DashboardContext(config, spec, service=service)
    with TestClient(build_app(ctx)) as test_client:
        reply = test_client.post("/api/service", json={"action": "start"})
        assert reply.status_code == 200 and reply.json()["state"] == "starting"
        for _ in range(100):
            if test_client.get("/api/service").json()["state"] == "running":
                break
        assert test_client.get("/api/service").json()["state"] == "running" and log == ["start"]
