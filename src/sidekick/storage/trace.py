"""sidekick.storage.trace — generic trace table

Overview
    Every model call (LLM, ASR, TTS) and every engagement decision is recorded in a SQLite
    trace table (invariants 5 and 18). This is the shared implementation: one table per concern
    with declared columns, `record()`, `recent()` and `prune()`.
Design
    `TraceTable` owns a `Database` with a single migration creating the table; `id` (uuid4 hex)
    and `ts` (unix seconds) are always present; a column declared later is added to an existing
    table when it opens (`ALTER TABLE … ADD COLUMN`, older rows read NULL). Unknown fields raise,
    so a typo cannot silently drop data. `RecentCalls` is a service session's in-memory tail
    of the same calls (last result, medians, errors in the last hour, calls in flight), so the
    Live page reads it without SQL (block #69). Pruning deletes rows older than N days; a table built with `retention_days`
    prunes itself, at most once an hour and only when it writes, so nobody has to schedule it
    (the service traces keep `SERVICE_TRACE_RETENTION_DAYS`).
Depends on
    sidekick.log, .storage.Database.
"""

from __future__ import annotations

import statistics
import time
import uuid
from collections import deque
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .database import Database

SERVICE_TRACE_RETENTION_DAYS = 10.0  # LLM / ASR / TTS call traces
PRUNE_EVERY_S = 3600.0


class TraceTable:
    """A single trace table with fixed columns."""

    def __init__(
        self,
        path: Path,
        table: str,
        columns: Mapping[str, str],
        retention_days: float | None = None,
    ) -> None:
        if not table.isidentifier():
            raise ValueError(f"bad table name {table!r}")
        self.table = table
        self.columns = dict(columns)
        for name in self.columns:
            if not name.isidentifier() or name in {"id", "ts"}:
                raise ValueError(f"bad column name {name!r}")
        column_sql = ", ".join(f"{name} {kind}" for name, kind in self.columns.items())
        create = (
            f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, ts REAL NOT NULL"
            + (f", {column_sql}" if column_sql else "")
            + f"); CREATE INDEX IF NOT EXISTS {table}_ts ON {table}(ts);"
        )
        self.db = Database(path, [create])
        self._add_missing_columns()
        self.retention_days = retention_days
        self._pruned_at = 0.0

    def _add_missing_columns(self) -> None:
        present = {row["name"] for row in self.db.query(f"PRAGMA table_info({self.table})")}
        for name, kind in self.columns.items():
            if name not in present:
                self.db.execute(f"ALTER TABLE {self.table} ADD COLUMN {name} {kind}")

    def record(self, **fields: Any) -> str:
        """Insert one row; returns its id."""
        unknown = set(fields) - set(self.columns)
        if unknown:
            raise ValueError(f"unknown trace fields for {self.table}: {sorted(unknown)}")
        row_id = uuid.uuid4().hex
        names = ["id", "ts", *fields.keys()]
        values = [row_id, time.time(), *fields.values()]
        placeholders = ", ".join("?" for _ in names)
        self.db.execute(
            f"INSERT INTO {self.table} ({', '.join(names)}) VALUES ({placeholders})", values
        )
        if self.retention_days is not None and values[1] - self._pruned_at > PRUNE_EVERY_S:
            self._pruned_at = values[1]
            self.prune(self.retention_days)
        return row_id

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Newest rows first."""
        rows = self.db.query(f"SELECT * FROM {self.table} ORDER BY ts DESC LIMIT ?", (limit,))
        return [dict(row) for row in rows]

    def between(self, start_ts: float, end_ts: float, limit: int = 2000) -> list[dict[str, Any]]:
        """Rows with `start_ts <= ts < end_ts`, oldest first (replay by time range)."""
        rows = self.db.query(
            f"SELECT * FROM {self.table} WHERE ts >= ? AND ts < ? ORDER BY ts ASC LIMIT ?",
            (start_ts, end_ts, limit),
        )
        return [dict(row) for row in rows]

    def count(self) -> int:
        """Number of rows."""
        return int(self.db.query(f"SELECT COUNT(*) AS n FROM {self.table}")[0]["n"])

    def prune(self, days: float) -> int:
        """Delete rows older than `days`; returns how many went."""
        cutoff = time.time() - days * 86400.0
        return self.db.execute(f"DELETE FROM {self.table} WHERE ts < ?", (cutoff,))


class RecentCalls:
    """The newest calls of one service, kept in memory for live views (no SQL)."""

    def __init__(self, size: int = 100) -> None:
        self._calls: deque[dict[str, Any]] = deque(maxlen=size)
        self._inflight: dict[str, int] = {}

    def begin(self, slot: str) -> None:
        """A call on `slot` started."""
        self._inflight[slot] = self._inflight.get(slot, 0) + 1

    def end(
        self,
        slot: str,
        ok: bool,
        duration_ms: float,
        task: str | None = None,
        first_ms: float | None = None,
        error: str | None = None,
        cancelled: bool = False,
    ) -> None:
        """A call on `slot` finished (`first_ms`: its first token or audio, when streaming).

        A `cancelled` call (a barge-in, the slower request of a hedged call) is not an error.
        """
        self._inflight[slot] = max(0, self._inflight.get(slot, 0) - 1)
        self._calls.append(
            {
                "ts": time.time(),
                "slot": slot,
                "ok": ok,
                "ms": round(duration_ms),
                "first_ms": None if first_ms is None else round(first_ms),
                "task": task,
                "error": (error or "")[:160] or None,
                "cancelled": cancelled,
            }
        )

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Newest calls first."""
        return list(reversed(self._calls))[:limit]

    def summary(self) -> dict[str, dict[str, Any]]:
        """Per slot: the last call, medians of the last 20, calls / errors in the last hour."""
        now = time.time()
        out: dict[str, dict[str, Any]] = {}
        for slot in sorted({c["slot"] for c in self._calls} | set(self._inflight)):
            mine = [c for c in self._calls if c["slot"] == slot]
            last = mine[-1] if mine else None
            ok = [c for c in mine[-20:] if c["ok"]]
            firsts = [c["first_ms"] for c in ok if c["first_ms"] is not None]
            hour = [c for c in mine if now - c["ts"] < 3600]
            out[slot] = {
                "inflight": self._inflight.get(slot, 0),
                "last": None if last is None else {**last, "age_s": round(now - last["ts"], 1)},
                "median_ms": round(statistics.median(c["ms"] for c in ok)) if ok else None,
                "median_first_ms": round(statistics.median(firsts)) if firsts else None,
                "calls_1h": len(hour),
                "errors_1h": sum(1 for c in hour if not c["ok"] and not c.get("cancelled")),
                "cancelled_1h": sum(1 for c in hour if c.get("cancelled")),
            }
        return out
