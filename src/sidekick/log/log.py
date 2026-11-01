"""sidekick.log.log — logging façade over stdlib logging

Overview
    One way to log for the whole project (invariant 9): a `Log` class with
    `debug/info/info0/warning/error`, one line format, English only, with the calling module
    and function filled in automatically. `info0()` marks function entry with a `->` prefix,
    mirroring Scoop's `Log.info0`. `mask_secret()` is the only sanctioned way to put a credential
    into a log line or a trace row (invariant 6).
Design
    Everything hangs under the `sidekick` logger so handlers are configured once in
    `configure_logging()` (stderr plus a rotating file under `.derived_data/logs/`). The caller's
    module name is read from the stack once per call; `stacklevel=2` lets stdlib fill `funcName`.
    The newest warnings and errors are also kept in memory (`Log.recent()`, `Log.counts()`) so
    the Live page shows them without reading the file (block #69). This module imports nothing
    from sidekick: it is layer 0.
Depends on
    stdlib logging only.

See Also
--------
    AGENTS.md "Core rules" 6 and 9.

"""

from __future__ import annotations

import inspect
import logging
import sys
import time
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_FORMAT = "%(asctime)s [%(levelname).1s] %(name)s.%(funcName)s | %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S"
_ROOT = "sidekick"


def mask_secret(value: str | None) -> str:
    """Keep only the first and last four characters plus the length, or less for short values."""
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return f"****({len(value)})"
    return f"{value[:4]}…{value[-4:]}({len(value)})"


# The newest warnings and errors, for the Live page (no file reads).
_RECENT: deque[dict[str, Any]] = deque(maxlen=300)


class _RecentHandler(logging.Handler):
    """Keeps warnings and errors in `_RECENT`."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _RECENT.append(
                {
                    "ts": record.created,
                    "level": record.levelname.lower(),
                    "where": f"{record.name.removeprefix(_ROOT + '.')}.{record.funcName}",
                    "message": record.getMessage()[:300],
                }
            )
        except Exception:  # logging must never raise
            pass


def configure_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    """Install the stderr handler and, when `log_dir` is given, a rotating file handler."""
    root = logging.getLogger(_ROOT)
    root.setLevel(level.upper())
    root.propagate = False
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter(_FORMAT, _DATEFMT)
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    root.addHandler(stream)
    recent = _RecentHandler(logging.WARNING)
    root.addHandler(recent)
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "sidekick.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def _caller_logger() -> logging.Logger:
    frame = inspect.currentframe()
    # _caller_logger -> Log.<level> -> caller
    caller = frame.f_back.f_back if frame is not None and frame.f_back is not None else None
    name = caller.f_globals.get("__name__", _ROOT) if caller is not None else _ROOT
    if not name.startswith(_ROOT):
        name = f"{_ROOT}.{name}"
    return logging.getLogger(name)


class Log:
    """Static façade; use `Log.info("...")` from anywhere in sidekick."""

    @staticmethod
    def debug(message: str = "") -> None:
        """Debug-level line."""
        _caller_logger().debug(message, stacklevel=2)

    @staticmethod
    def info(message: str = "") -> None:
        """Info-level line."""
        _caller_logger().info(message, stacklevel=2)

    @staticmethod
    def info0(message: str = "") -> None:
        """Function-entry marker: `-> <message>` at info level."""
        _caller_logger().info(f"-> {message}".rstrip(), stacklevel=2)

    @staticmethod
    def warning(message: str = "") -> None:
        """Warning-level line."""
        _caller_logger().warning(message, stacklevel=2)

    @staticmethod
    def error(message: str = "") -> None:
        """Error-level line."""
        _caller_logger().error(message, stacklevel=2)

    @staticmethod
    def recent(limit: int = 50, since: float = 0.0) -> list[dict[str, Any]]:
        """The newest warnings and errors (`ts`, `level`, `where`, `message`), newest first."""
        rows = [row for row in reversed(_RECENT) if row["ts"] > since]
        return rows[:limit]

    @staticmethod
    def counts(window_s: float = 600.0) -> dict[str, int]:
        """Warnings and errors logged in the last `window_s` seconds."""
        cutoff = time.time() - window_s
        out = {"warning": 0, "error": 0}
        for row in _RECENT:
            if row["ts"] >= cutoff:
                out["error" if row["level"] in ("error", "critical") else "warning"] += 1
        return out
