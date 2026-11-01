"""BodyDaemon: argv building, status merge, and (slow) a real mockup-sim daemon lifecycle."""

from __future__ import annotations

import sys
import time

import pytest

from sidekick.body import BodyDaemon, BodyDaemonConfiguration


def test_command_reflects_configuration(tmp_path):
    cfg = BodyDaemonConfiguration(port=8123, sim="mockup", wake_on_start=False, media=False)
    argv = BodyDaemon(cfg, tmp_path).command()
    assert argv[:3] == [sys.executable, "-m", "reachy_mini.daemon.app.main"]
    assert "--mockup-sim" in argv and "--no-media" in argv and "--no-wake-up-on-start" in argv
    assert argv[argv.index("--fastapi-port") + 1] == "8123"
    assert "--preload-datasets" in argv
    mujoco = BodyDaemon(
        BodyDaemonConfiguration(sim="mujoco", preload_datasets=False), tmp_path
    ).command()
    assert "--sim" in mujoco and "--preload-datasets" not in mujoco


def test_status_merges_pid_and_http(tmp_path, monkeypatch):
    daemon = BodyDaemon(BodyDaemonConfiguration(port=8999), tmp_path)
    monkeypatch.setattr(daemon, "http_status", lambda timeout=2.0: None)
    status = daemon.status()
    assert not status.reachable and status.state == "down" and not status.managed
    assert "down" in status.line()
    monkeypatch.setattr(
        daemon,
        "http_status",
        lambda timeout=2.0: {
            "state": "running",
            "version": "1.12.0",
            "robot_name": "reachy_mini",
            "backend_status": {"motor_control_mode": "enabled"},
        },
    )
    status = daemon.status()
    assert status.running and status.version == "1.12.0" and not status.managed
    assert "external" in status.line()
    assert daemon.stop() is False  # never kills a daemon it did not start


@pytest.mark.slow
def test_mockup_daemon_lifecycle(tmp_path):
    cfg = BodyDaemonConfiguration(
        port=8031, sim="mockup", media=False, preload_datasets=False, start_timeout_s=120.0
    )
    daemon = BodyDaemon(cfg, tmp_path)
    assert not daemon.status().reachable, "port 8031 must be free for this test"
    started = time.monotonic()
    status = daemon.start()
    try:
        assert status.running, f"daemon did not start: {status} log={daemon.tail_log()}"
        assert status.managed and status.pid is not None
        assert "managed" in status.line()
        print(f"mockup daemon running after {time.monotonic() - started:.1f}s: {status.line()}")
    finally:
        assert daemon.stop(timeout_s=30.0)
    assert not daemon.status().reachable
    assert not daemon.pid_path.exists()
