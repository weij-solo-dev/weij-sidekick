"""sidekick.body.daemon — lifecycle of the `reachy-mini-daemon` process from the sidekick CLI

Overview
    The owner's rule: the daemon is never run by hand. `BodyDaemon` spawns it from the active
    Python environment with flags derived from `config.body`, keeps a pid file under the
    sidekick home, waits until the daemon reports `running`, and stops it with SIGINT so its
    own shutdown puts the robot to sleep. `status()` merges the pid file with
    `GET /api/daemon/status` so readiness and the dashboard can tell "ours, running",
    "someone else's" and "down" apart. The service's start calls `ensure_running()` (spawn it
    when sidekick manages it and it is down; start its backend when it answers but was stopped)
    and its stop calls `shutdown()` (ours: SIGINT; someone else's, e.g. on a Wireless robot:
    `POST /api/daemon/stop?goto_sleep=…`), so a stopped Banana is a robot turned off (block #85).
Design
    One subprocess per home, detached in its own session so a Ctrl+C in the operator's shell
    does not kill the robot's daemon; the body's `stop()` stops it with the service. The daemon's
    stdout/stderr go to `logs/reachy-daemon.log`, rotated (one old file kept) when a spawn finds
    it over `LOG_ROTATE_BYTES` — the daemon logs a lot and once ran four days into 240 MB. Nothing
    here wakes or sleeps the robot on its own (invariant 11): the daemon does both as part of its
    start and stop, with the `wake_on_start` / `sleep_on_stop` flags. The simulation flags exist
    so the whole stack can be exercised without hardware (`--mockup-sim` needs no MuJoCo).
Depends on
    sidekick.log, httpx.

See Also
--------
    AGENTS.md "Dashboard and CLI", PLAN.md block "[2026-10-26 #12]".

"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from sidekick.log import Log

from . import dsp

PID_FILE = "reachy_daemon.pid"
LOG_FILE = "reachy-daemon.log"
LOG_ROTATE_BYTES = 50_000_000  # a spawn rotates a log this big (one old file kept)


@dataclass(frozen=True, slots=True)
class BodyDaemonConfiguration:
    """What to launch and where."""

    host: str = "localhost"
    port: int = 8000
    sim: str = "none"
    wake_on_start: bool = True
    sleep_on_stop: bool = True
    preload_datasets: bool = True
    media: bool = True
    log_level: str = "INFO"
    robot_name: str = "reachy_mini"
    start_timeout_s: float = 90.0
    extra_args: tuple[str, ...] = ()
    check_audio_dsp: bool = True

    @property
    def base_url(self) -> str:
        """HTTP root."""
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True, slots=True)
class BodyDaemonStatus:
    """What `BodyDaemon.status()` reports."""

    reachable: bool
    state: str = "down"
    motor_mode: str | None = None
    version: str | None = None
    robot_name: str | None = None
    pid: int | None = None
    managed: bool = False
    error: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def running(self) -> bool:
        """Backend up and serving."""
        return self.reachable and self.state == "running"

    def line(self) -> str:
        """One-line summary for the CLI."""
        who = "managed" if self.managed else ("external" if self.reachable else "none")
        pid = f" pid={self.pid}" if self.pid else ""
        if not self.reachable:
            return f"daemon down ({who}){pid}" + (f": {self.error}" if self.error else "")
        return f"daemon {self.state} ({who}){pid} version={self.version} motors={self.motor_mode}"


class BodyDaemon:
    """Start / stop / status for one daemon instance."""

    def __init__(self, configuration: BodyDaemonConfiguration, home: Path) -> None:
        self.configuration = configuration
        self.home = home
        self.pid_path = home / PID_FILE
        self.log_path = home / "logs" / LOG_FILE
        self.started_here = False
        self.last_dsp: dsp.BodyDSPStatus | None = None
        self._cached: tuple[float, BodyDaemonStatus] | None = None

    # ------------------------------------------------------------------ status

    def read_pid(self) -> int | None:
        """Pid from the pid file when that process is still alive."""
        try:
            pid = int(self.pid_path.read_text().strip())
        except (OSError, ValueError):
            return None
        if not _alive(pid):
            self.pid_path.unlink(missing_ok=True)
            return None
        return pid

    def http_status(self, timeout: float = 2.0) -> dict[str, Any] | None:
        """`GET /api/daemon/status` or None when unreachable."""
        try:
            response = httpx.get(
                f"{self.configuration.base_url}/api/daemon/status", timeout=timeout
            )
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        payload = response.json()
        return payload if isinstance(payload, dict) else None

    def cached_status(self, max_age_s: float = 5.0) -> BodyDaemonStatus:
        """`status()` at most every `max_age_s` (the dashboard's 1 Hz health poll)."""
        now = time.monotonic()
        if self._cached is None or now - self._cached[0] > max_age_s:
            self._cached = (now, self.status(timeout=1.0))
        return self._cached[1]

    def status(self, timeout: float = 2.0) -> BodyDaemonStatus:
        """Merge pid file and HTTP status."""
        pid = self.read_pid()
        payload = self.http_status(timeout)
        if payload is None:
            return BodyDaemonStatus(
                False,
                pid=pid,
                managed=pid is not None,
                error="starting" if pid is not None else "unreachable",
            )
        backend = payload.get("backend_status") or {}
        return BodyDaemonStatus(
            True,
            state=str(payload.get("state", "unknown")),
            motor_mode=backend.get("motor_control_mode") if isinstance(backend, dict) else None,
            version=payload.get("version"),
            robot_name=payload.get("robot_name"),
            pid=pid,
            managed=pid is not None,
            error=payload.get("error"),
            payload=payload,
        )

    # ------------------------------------------------------------------- start

    def command(self) -> list[str]:
        """The argv used to launch the daemon."""
        cfg = self.configuration
        argv = [sys.executable, "-m", "reachy_mini.daemon.app.main"]
        argv += ["--fastapi-host", "127.0.0.1" if cfg.host in ("localhost", "::1") else cfg.host]
        argv += ["--fastapi-port", str(cfg.port)]
        argv += ["--robot-name", cfg.robot_name, "--log-level", cfg.log_level]
        if cfg.sim == "mujoco":
            argv.append("--sim")
        elif cfg.sim == "mockup":
            argv.append("--mockup-sim")
        if not cfg.media:
            argv.append("--no-media")
        if not cfg.wake_on_start:
            argv.append("--no-wake-up-on-start")
        if not cfg.sleep_on_stop:
            argv.append("--no-goto-sleep-on-stop")
        if cfg.preload_datasets:
            argv.append("--preload-datasets")
        argv.extend(cfg.extra_args)
        return argv

    def ensure_running(self, spawn: bool = True) -> BodyDaemonStatus:
        """The daemon running: spawned when down (and `spawn`), its backend started when stopped.

        A daemon that answers with its backend stopped (after `sleep()`, or an error) gets
        `POST /api/daemon/start?wake_up=…`; one still starting is waited for.
        """
        current = self.status()
        if current.running:
            return current
        if current.reachable:
            if current.state in ("stopped", "not_initialized", "error"):
                Log.info(f"daemon up, backend {current.state}: starting it")
                self._post("/api/daemon/start", {"wake_up": self.configuration.wake_on_start})
            return self.wait_running()
        if not spawn:
            Log.warning(f"daemon unreachable and not managed here: {current.line()}")
            return current
        return self.start(wait=True)

    def shutdown(self) -> bool:
        """Turn the robot off: stop the daemon sidekick spawned, or put another one to sleep."""
        if self.read_pid() is not None:
            return self.stop()
        if self.status(timeout=1.0).reachable:
            return self.sleep()
        return True

    def sleep(self, timeout_s: float = 30.0) -> bool:
        """Stop the backend of a daemon sidekick did not spawn (the robot sleeps, media freed)."""
        Log.info0()
        if not self._post("/api/daemon/stop", {"goto_sleep": self.configuration.sleep_on_stop}):
            return False
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            status = self.status(timeout=1.0)
            if not status.reachable or status.state in ("stopped", "error"):
                Log.info(f"daemon backend {status.state}")
                return True
            time.sleep(0.5)
        Log.warning("daemon backend did not stop in time")
        return False

    def _post(self, path: str, params: dict[str, Any]) -> bool:
        try:
            response = httpx.post(
                f"{self.configuration.base_url}{path}",
                params={k: str(v).lower() for k, v in params.items()},
                timeout=5.0,
            )
        except httpx.HTTPError as exc:
            Log.warning(f"POST {path}: {type(exc).__name__}")
            return False
        if response.status_code != 200:
            Log.warning(f"POST {path}: {response.status_code} {response.text[:120]}")
            return False
        return True

    def _rotate_log(self) -> None:
        try:
            if self.log_path.stat().st_size > LOG_ROTATE_BYTES:
                os.replace(self.log_path, self.log_path.with_name(LOG_FILE + ".1"))
                Log.info(f"rotated {LOG_FILE} (over {LOG_ROTATE_BYTES // 1_000_000} MB)")
        except OSError:
            pass

    def start(self, wait: bool = True) -> BodyDaemonStatus:
        """Launch the daemon unless one already answers; optionally wait for `running`."""
        Log.info0(f"{self.configuration.base_url} sim={self.configuration.sim}")
        current = self.status()
        if current.reachable:
            Log.info(f"daemon already up: {current.line()}")
            return current
        if current.pid is not None:
            Log.info(f"daemon pid {current.pid} still starting")
        else:
            if (
                self.configuration.check_audio_dsp
                and self.configuration.media
                and self.configuration.sim == "none"
            ):
                self.last_dsp = dsp.ensure_healthy()
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_log()
            argv = self.command()
            Log.info(f"spawning {' '.join(argv[1:])}")
            with self.log_path.open("ab") as log_file:
                log_file.write(
                    f"\n--- sidekick spawn {time.strftime('%Y-%m-%d %H:%M:%S')}\n".encode()
                )
                process = subprocess.Popen(
                    argv,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    cwd=str(self.home),
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                )
            self.pid_path.write_text(f"{process.pid}\n")
            self.started_here = True
        if not wait:
            return self.status()
        return self.wait_running()

    def wait_running(self, timeout_s: float | None = None) -> BodyDaemonStatus:
        """Poll until the daemon reports `running` (or `error` / process death / timeout)."""
        deadline = time.monotonic() + (timeout_s or self.configuration.start_timeout_s)
        last = self.status(timeout=1.0)
        while time.monotonic() < deadline:
            last = self.status(timeout=1.0)
            if last.running or last.state == "error":
                break
            if last.pid is None and not last.reachable:
                return BodyDaemonStatus(False, error=f"daemon exited; see {self.log_path}")
            time.sleep(0.5)
        if last.running:
            Log.info(f"daemon ready: {last.line()}")
        else:
            Log.warning(f"daemon not running after wait: {last.line()}")
        return last

    # -------------------------------------------------------------------- stop

    def stop(self, timeout_s: float = 30.0) -> bool:
        """SIGINT the daemon we know about and wait for it to exit."""
        Log.info0()
        pid = self.read_pid()
        if pid is None:
            status = self.status()
            if status.reachable:
                Log.warning("daemon is running but was not started by sidekick; leaving it alone")
                return False
            Log.info("no daemon to stop")
            return True
        for sig, grace in (
            (signal.SIGINT, timeout_s),
            (signal.SIGTERM, 5.0),
            (signal.SIGKILL, 2.0),
        ):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                break
            if _wait_exit(pid, grace):
                break
            Log.warning(f"daemon pid {pid} ignored {sig.name}; escalating")
        self.pid_path.unlink(missing_ok=True)
        self.started_here = False
        Log.info(f"daemon pid {pid} stopped")
        return True

    def restart(self) -> BodyDaemonStatus:
        """Stop then start."""
        self.stop()
        return self.start()

    def tail_log(self, lines: int = 40) -> list[str]:
        """Last lines of the daemon log."""
        try:
            content = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        return content[-lines:]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        # A zombie child of this process reports alive to kill(); reap it so it does not.
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return True


def _wait_exit(pid: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.2)
    return not _alive(pid)
