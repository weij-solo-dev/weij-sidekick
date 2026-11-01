"""The service (block #87): start / stop inside the process, steps, rollback, the remembered choice."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from sidekick.service import ServiceBusy, ServiceSession
from sidekick.storage import StorageSession


class Module:
    """A runtime module as the service sees it: start, stop, check."""

    def __init__(
        self,
        name: str,
        log: list[str],
        items: list[dict] | None = None,
        *,
        fail: bool = False,
        hang: bool = False,
    ) -> None:
        self.name, self.log, self.items, self.fail, self.hang = name, log, items or [], fail, hang

    async def start(self) -> None:
        self.log.append(f"start {self.name}")
        if self.hang:
            await asyncio.sleep(30)
        if self.fail:
            raise RuntimeError(f"{self.name} broke")

    async def stop(self) -> None:
        self.log.append(f"stop {self.name}")

    def check(self) -> list[dict]:
        return self.items


class Recorder(Module):
    """A module with plain (threaded) start / stop, like the recorder."""

    def start(self) -> None:  # type: ignore[override]
        self.log.append(f"start {self.name}")

    def stop(self) -> None:  # type: ignore[override]
        self.log.append(f"stop {self.name}")


class Config:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.spec: Any = object()

    def load(self) -> Any:
        self.log.append("load")
        return self.spec

    def apply(self, spec: Any) -> dict[str, str]:
        self.log.append("apply")
        return {}

    def release(self) -> None:
        self.log.append("release")


def _service(tmp_path, modules, log, prerequisites=None) -> ServiceSession:
    StorageSession.shared = StorageSession(tmp_path)
    service = ServiceSession()
    service.setup(
        config=Config(log),  # type: ignore[arg-type]
        state_path=tmp_path / "service.json",
        prepare=lambda: log.append("prepare"),
        modules=modules,
        prerequisites=prerequisites
        or (lambda: [{"id": "python", "title": "Python", "level": "ok"}]),
    )
    return service


async def test_start_runs_every_step_in_order_and_remembers(tmp_path):
    log: list[str] = []
    body = Module("body", log, [{"id": "link", "title": "connection", "level": "ok"}])
    channels = Module("channels", log, [{"id": "remote", "title": "remote", "level": "off"}])
    record = Recorder("record", log, [{"id": "ring", "title": "recording", "level": "warn"}])
    service = _service(tmp_path, [("body", body), ("channels", channels), ("record", record)], log)
    status = service.request("start")
    assert status["state"] == "starting" and status["busy"]
    await service.wait()
    assert service.state == "running"
    assert log == ["load", "apply", "prepare", "start body", "start channels", "start record"]
    steps = {s["id"]: s for s in service.status()["transition"]["steps"]}
    assert steps["config"]["state"] == "ok" and steps["models"]["state"] == "skipped"
    assert steps["body"]["state"] == "ok" and steps["body"]["tab"] == "body"
    assert steps["channels"]["state"] == "skipped"  # nothing configured: a dash
    assert steps["record"]["state"] == "warn" and steps["record"]["items"][0]["tab"] == "record"
    assert service.status()["transition"]["ok"] is True
    stored = StorageSession.shared.read_json(tmp_path / "service.json")
    assert stored["wanted"] == "running" and stored["by"] == "dashboard"
    assert [i["id"] for i in service.checks()] == ["body.link", "channels.remote", "record.ring"]


async def test_a_bad_check_rolls_back_what_started(tmp_path):
    log: list[str] = []
    body = Module("body", log, [{"id": "link", "title": "connection", "level": "ok"}])
    agent = Module(
        "agent",
        log,
        [{"id": "llm.fast", "title": "LLM fast", "level": "bad", "detail": "invalid api key"}],
    )
    late = Module("extensions", log)
    service = _service(tmp_path, [("body", body), ("agent", agent), ("extensions", late)], log)
    service.request("start")
    await service.wait()
    assert service.state == "stopped" and service.checks() == []
    transition = service.status()["transition"]
    assert transition["ok"] is False and "invalid api key" in transition["error"]
    steps = {s["id"]: s["state"] for s in transition["steps"]}
    assert steps == {
        "config": "ok",
        "models": "skipped",
        "body": "ok",
        "agent": "bad",
        "extensions": "skipped",
    }
    assert log[-3:] == ["stop agent", "stop body", "release"]  # reverse, then the backends
    assert "start extensions" not in log


async def test_a_module_that_raises_is_a_failed_step(tmp_path):
    log: list[str] = []
    service = _service(tmp_path, [("body", Module("body", log, fail=True))], log)
    service.request("start")
    await service.wait()
    step = service.status()["transition"]["steps"][-1]
    assert step["state"] == "bad" and "body broke" in step["items"][0]["detail"]
    assert log[-2:] == ["stop body", "release"]


async def test_missing_prerequisites_start_nothing(tmp_path):
    log: list[str] = []
    service = _service(
        tmp_path,
        [("body", Module("body", log))],
        log,
        prerequisites=lambda: [
            {
                "id": "slots.llm",
                "title": "LLM slots",
                "level": "bad",
                "detail": "llm.fast: minimax api_key missing",
                "tab": "agent",
            }
        ],
    )
    service.request("start")
    await service.wait()
    transition = service.status()["transition"]
    assert service.state == "stopped" and transition["ok"] is False
    assert transition["steps"][0]["items"][0]["tab"] == "agent"
    assert "api_key missing" in transition["error"]
    assert "start body" not in log and "apply" not in log


async def test_one_transition_at_a_time(tmp_path):
    log: list[str] = []
    service = _service(tmp_path, [("body", Module("body", log, hang=True))], log)
    service.request("start")
    await asyncio.sleep(0.05)
    with pytest.raises(ServiceBusy):
        service.request("stop")
    with pytest.raises(ValueError):
        ServiceSession().request("reboot")
    await service.stop()  # the process exits: the start is cancelled and rolled back
    assert service.state == "stopped" and log[-2:] == ["stop body", "release"]
    assert service.status()["transition"]["error"] == "cancelled"


async def test_stop_is_remembered_and_honoured_at_the_next_boot(tmp_path):
    log: list[str] = []
    service = _service(tmp_path, [("body", Module("body", log))], log)
    service.request("start")
    await service.wait()
    service.request("stop")
    await service.wait()
    assert service.state == "stopped" and log[-2:] == ["stop body", "release"]
    assert service.status()["transition"]["action"] == "stop"
    # the next process reads the choice: Bobby stays stopped, the modules are still bound
    log.clear()
    again = _service(tmp_path, [("body", Module("body", log))], log)
    await again.start()
    assert again.state == "stopped" and again.wanted == "stopped" and log == ["prepare"]
    # an explicit start is remembered again; a process exit does not change the choice
    again.request("start")
    await again.wait()
    await again.stop()
    assert again.wanted == "running"
    third = _service(tmp_path, [("body", Module("body", log))], log)
    await third.start()
    await third.wait()
    assert third.state == "running" and third.status()["transition"]["by"] == "boot"
    await third.stop()


async def test_restart_stops_then_starts(tmp_path):
    log: list[str] = []
    service = _service(tmp_path, [("body", Module("body", log))], log)
    service.request("start")
    await service.wait()
    log.clear()
    service.request("restart")
    await service.wait()
    assert service.state == "running"
    assert log == ["stop body", "release", "load", "apply", "prepare", "start body"]
    # a start of a running service only records the choice
    assert service.request("start")["state"] == "running"


class SlowStop(Module):
    """A module whose stop takes a while, like the body's sleep move (5–6 s)."""

    async def stop(self) -> None:
        self.log.append(f"stop {self.name} begins")
        await asyncio.sleep(0.3)
        self.log.append(f"stop {self.name} ends")


async def test_an_exit_during_a_stop_waits_for_it_and_keeps_the_choice(tmp_path):
    """Block #89: Stop on the dashboard, then `sidekick close` 5 s later. The exit cancelled
    the stop and ran a second one over it (the daemon stopped twice) and the Stop was lost."""
    log: list[str] = []
    service = _service(tmp_path, [("body", SlowStop("body", log))], log)
    service.request("start")
    await service.wait()
    log.clear()
    service.request("stop")
    await asyncio.sleep(0.05)  # the body is going to sleep
    assert service.state == "stopping"
    await service.stop()  # the process exits
    assert log == ["stop body begins", "stop body ends", "release"]  # one stop, finished
    assert service.state == "stopped"
    again = _service(tmp_path, [("body", SlowStop("body", log))], log)
    await again.start()
    assert again.wanted == "stopped" and again.state == "stopped"


async def test_an_exit_during_a_restart_finishes_the_stop_and_starts_nothing(tmp_path):
    log: list[str] = []
    service = _service(tmp_path, [("body", SlowStop("body", log))], log)
    service.request("start")
    await service.wait()
    log.clear()
    service.request("restart")
    await asyncio.sleep(0.05)
    await service.stop()
    assert log == ["stop body begins", "stop body ends", "release"]
    assert service.state == "stopped" and service.wanted == "running"  # a restart is no Stop


def test_a_request_needs_the_running_loop_and_changes_nothing_without_it(tmp_path):
    """The route once ran on a worker thread: `create_task` failed after the state had moved."""
    log: list[str] = []
    service = _service(tmp_path, [("body", Module("body", log))], log)
    service.state = "running"
    with pytest.raises(RuntimeError):
        service.request("stop")  # no running loop in a plain function
    assert service.state == "running" and service.transition is None
