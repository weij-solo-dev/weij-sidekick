"""sidekick.cli — the `sidekick` command: `startup` and `close`

Overview
    Two commands are the whole CLI (the owner, PLAN.md block #85). `sidekick startup` starts the
    main process — the dashboard, the data pages and, when the owner left it running, Banana's
    service — in the background and prints the dashboard's address; `sidekick close` closes it:
    the service stops first, so the robot turns off, then the dashboard. Everything else —
    readiness, configuration, the daemon, channels, enrollment, extensions, backup — is on the
    dashboard; starting and stopping Banana is its power control.
Design
    `startup` spawns the same command with the internal `--foreground` flag, detached in its own
    session (a Ctrl+C in the shell never reaches it), its output appended to
    `logs/sidekick.out.log`, and waits until the dashboard answers `/api/health`; a boot that
    dies is reported with the log's last lines. The foreground process keeps `sidekick.pid` in
    the home while it runs, so there is one per home and `close` knows whom to signal. A home
    without `config.json` gets a first spec for this host (macOS: `lite-mac`, a Linux ARM board:
    `pi`, else `default`; a MiniMax key from `SIDEKICK_MINIMAX_API_KEY` / `MINIMAX_API_KEY` when
    one is set, for development) — the readiness list and the start gate then say what is
    missing. `close` sends SIGTERM and waits for `App.stop()`. argparse only.
Depends on
    sidekick.app, sidekick.config, sidekick.storage, sidekick.log, httpx.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

from sidekick import __version__
from sidekick.app import App, AppNotInitialized
from sidekick.config import ConfigSession, ConfigSpec
from sidekick.log import Log
from sidekick.storage import StorageSession

PID_FILE = "sidekick.pid"
OUT_LOG = "sidekick.out.log"
DEV_KEY_ENVS = ("SIDEKICK_MINIMAX_API_KEY", "MINIMAX_API_KEY")
READY_TIMEOUT_S = 60.0
CLOSE_TIMEOUT_S = 60.0  # the service stops first: the daemon's own stop takes up to 30 s


def _home(args: argparse.Namespace) -> Path:
    storage = StorageSession(Path(args.home) if args.home else None)
    return storage.layout.home.resolve()


def host_profile() -> str:
    """The deployment profile a first spec starts from on this host."""
    if sys.platform == "darwin":
        return "lite-mac"
    if sys.platform.startswith("linux") and platform.machine() in ("aarch64", "arm64"):
        return "pi"
    return "default"


def ensure_config(home: Path) -> ConfigSpec:
    """The spec of this home, written first when there is none (no keys unless from env)."""
    storage = StorageSession(home)
    StorageSession.shared = storage
    storage.ensure_layout()
    session = ConfigSession(storage)
    spec = session.load()
    if spec is not None:
        return spec
    spec = ConfigSession.preset_spec(host_profile())
    key = next((os.environ[name] for name in DEV_KEY_ENVS if os.environ.get(name)), "")
    if key:
        spec.credentials.setdefault("minimax", {})["api_key"] = key
    session.save(spec)
    print(f"wrote a first config for this host ({host_profile()}): {session.path}")
    return spec


def read_pid(home: Path) -> int | None:
    """The main process of this home when it is alive."""
    try:
        pid = int((home / PID_FILE).read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        (home / PID_FILE).unlink(missing_ok=True)
        return None
    except PermissionError:
        return pid
    return pid


def dashboard_url(spec: ConfigSpec) -> str:
    """Where the dashboard answers."""
    return f"http://{spec.dashboard.host}:{spec.dashboard.port}/"


def wait_ready(url: str, process: subprocess.Popen[bytes] | None, timeout_s: float) -> bool:
    """Until the dashboard answers (True) or the process dies / time runs out (False)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            return False
        try:
            if httpx.get(f"{url}api/health", timeout=1.0).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    return False


def _tail(path: Path, lines: int = 20) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return []


def cmd_startup(args: argparse.Namespace) -> int:
    """Start the main process in the background (or, with the internal flag, run it here)."""
    home = _home(args)
    spec = ensure_config(home)
    if args.foreground:
        return _run_foreground(home, args.log_level)
    url = dashboard_url(spec)
    pid = read_pid(home)
    if pid is not None:
        print(f"sidekick is already running (pid {pid}): {url}")
        return 0
    out = home / "logs" / OUT_LOG
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "sidekick.cli", "--home", str(home), "--log-level"]
    argv += [args.log_level, "startup", "--foreground"]
    with out.open("ab") as log_file:
        log_file.write(f"\n--- sidekick startup {time.strftime('%Y-%m-%d %H:%M:%S')}\n".encode())
        process = subprocess.Popen(
            argv,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    print(f"starting sidekick (pid {process.pid}) …")
    if not wait_ready(url, process, READY_TIMEOUT_S):
        print("sidekick did not come up; the last lines of its log:")
        for line in _tail(out):
            print("  " + line)
        return 1
    print(f"sidekick is up: {url}")
    print("Banana starts on its own when you left it running; else press Start on the dashboard.")
    return 0


def _run_foreground(home: Path, log_level: str) -> int:
    pid_path = home / PID_FILE
    other = read_pid(home)
    if other is not None and other != os.getpid():
        print(f"sidekick is already running in this home (pid {other})")
        return 1
    pid_path.write_text(f"{os.getpid()}\n")
    try:
        asyncio.run(App(home, log_level).run())
    except AppNotInitialized as exc:
        print(str(exc))
        return 1
    except KeyboardInterrupt:  # pragma: no cover - interactive
        Log.info("interrupted")
    finally:
        if read_pid(home) == os.getpid():
            pid_path.unlink(missing_ok=True)
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    """Close the main process: Banana's service stops (the robot turns off), then the rest."""
    home = _home(args)
    pid = read_pid(home)
    if pid is None:
        print("sidekick is not running")
        return 0
    print(f"closing sidekick (pid {pid}); the robot turns off first …")
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + CLOSE_TIMEOUT_S
    while time.monotonic() < deadline:
        if read_pid(home) is None:
            print("sidekick closed")
            return 0
        time.sleep(0.3)
    print(f"sidekick (pid {pid}) did not close in {CLOSE_TIMEOUT_S:.0f} s; killing it")
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    (home / PID_FILE).unlink(missing_ok=True)
    return 1


def build_parser() -> argparse.ArgumentParser:
    """The argparse tree: `startup` and `close`."""
    parser = argparse.ArgumentParser(
        prog="sidekick", description="Banana, a home butler with a Reachy Mini body"
    )
    parser.add_argument("--version", action="version", version=f"sidekick {__version__}")
    parser.add_argument("--home", help="runtime home (default: $SIDEKICK_HOME or ./.derived_data)")
    parser.add_argument("--log-level", default="INFO")
    sub = parser.add_subparsers(dest="command", required=True)
    p_startup = sub.add_parser("startup", help="start sidekick (the dashboard, then Banana)")
    p_startup.add_argument("--foreground", action="store_true", help=argparse.SUPPRESS)
    p_startup.set_defaults(func=cmd_startup)
    sub.add_parser("close", help="close sidekick (Banana stops, the robot turns off)").set_defaults(
        func=cmd_close
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
