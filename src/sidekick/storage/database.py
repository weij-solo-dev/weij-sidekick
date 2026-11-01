"""sidekick.storage.database — the SQLite access pattern

Overview
    `Database`: one SQLite file with ordered migrations, a connection per operation, explicit
    `BEGIN IMMEDIATE` transactions (invariant 7), and a version suffix on the file name decided
    by the caller (invariant 8).
Design
    `executescript()` commits any open transaction before running, so each migration script is
    wrapped in its own `BEGIN IMMEDIATE … COMMIT` inside the script; a failure leaves the
    transaction open and closing the connection rolls it back. WAL mode keeps readers and the
    single writer from blocking each other across threads and the asyncio loop.
Depends on
    sidekick.log, stdlib sqlite3.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sidekick.log import Log


class Database:
    """One SQLite file with ordered migrations."""

    def __init__(self, path: Path, migrations: Sequence[str]) -> None:
        self.path = path
        self.migrations = tuple(migrations)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection for one operation and close it afterwards."""
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """`BEGIN IMMEDIATE` … `COMMIT`, rolling back on any exception."""
        with self.connect() as conn:
            conn.isolation_level = None
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    def migrate(self) -> None:
        """Apply migrations beyond the stored `user_version`."""
        with self.connect() as conn:
            current = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if current > len(self.migrations):
                raise RuntimeError(
                    f"{self.path.name}: user_version {current} is newer than this build knows"
                )
            for index in range(current, len(self.migrations)):
                # executescript() commits any open transaction first, so the transaction has to
                # live inside the script itself; an error leaves it open and closing the
                # connection rolls it back.
                conn.isolation_level = None
                conn.executescript(
                    "BEGIN IMMEDIATE;\n"
                    f"{self.migrations[index]}\n"
                    f"PRAGMA user_version = {index + 1};\n"
                    "COMMIT;"
                )
                Log.info(f"{self.path.name}: migrated to version {index + 1}")

    def user_version(self) -> int:
        """Current schema version."""
        with self.connect() as conn:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        """Read-only convenience: run one statement and fetch all rows."""
        with self.connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Single write statement in its own transaction; returns the rowcount."""
        with self.transaction() as conn:
            return int(conn.execute(sql, params).rowcount)
