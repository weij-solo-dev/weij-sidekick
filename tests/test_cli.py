"""The CLI is `startup` and `close` (block #85): a first config, one process per home, close."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from sidekick import cli


def run(argv, capsys):
    code = cli.main(argv)
    return code, capsys.readouterr().out


def test_only_startup_and_close():
    parser = cli.build_parser()
    assert parser.parse_args(["startup"]).command == "startup"
    assert parser.parse_args(["close"]).command == "close"
    assert parser.parse_args(["startup", "--foreground"]).foreground  # internal
    for gone in ("run", "init", "doctor", "daemon", "config", "enroll", "service", "backup"):
        with pytest.raises(SystemExit):
            parser.parse_args([gone])


def test_a_first_config_for_this_host(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIDEKICK_MINIMAX_API_KEY", "sk-cp-ENVKEY0000000000009999")
    home = tmp_path / "home"
    spec = cli.ensure_config(home)
    assert spec.robot.name == "Bobby" and "wrote a first config" in capsys.readouterr().out
    data = json.loads((home / "config.json").read_text())
    assert data["credentials"]["minimax"]["api_key"].startswith("sk-cp-ENVKEY")
    assert oct((home / "config.json").stat().st_mode & 0o777) == "0o600"
    assert cli.ensure_config(home).robot.name == "Bobby"  # kept, not rewritten
    assert capsys.readouterr().out == ""
    assert cli.host_profile() in ("lite-mac", "pi", "default")


def test_close_without_a_process_and_a_stale_pid(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    code, out = run(["--home", str(home), "close"], capsys)
    assert code == 0 and "not running" in out
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (home / cli.PID_FILE).write_text(f"{dead.pid}\n")
    assert cli.read_pid(home) is None and not (home / cli.PID_FILE).exists()


def test_close_signals_the_process_and_waits(tmp_path, capsys, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    sleeper = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal, time; signal.signal(signal.SIGTERM, lambda *a: exit(0)); time.sleep(60)",
        ]
    )
    (home / cli.PID_FILE).write_text(f"{sleeper.pid}\n")

    def gone_when_exited(path):  # the real process removes its pid file as it exits
        if sleeper.poll() is not None:
            (path / cli.PID_FILE).unlink(missing_ok=True)
            return None
        return sleeper.pid

    monkeypatch.setattr(cli, "read_pid", gone_when_exited)
    code, out = run(["--home", str(home), "close"], capsys)
    assert code == 0 and "closed" in out and sleeper.wait(5) is not None  # it got SIGTERM


def test_startup_reports_a_process_already_running(tmp_path, capsys):
    home = tmp_path / "home"
    cli.ensure_config(home)
    capsys.readouterr()
    (home / cli.PID_FILE).write_text(f"{os.getpid()}\n")
    code, out = run(["--home", str(home), "startup"], capsys)
    assert code == 0 and "already running" in out and "http://127.0.0.1:8787/" in out
