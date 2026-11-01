"""sidekick.extension.registry — installed extensions, enabled flags and settings in `extension_v1.db`

Overview
    One row per known extension (bundled or user-installed) with its directory, version,
    enabled flag, settings values and the last error. Secrets inside settings are stored as
    given (the file lives in the 0600 home) and masked only when displayed.
Design
    SQLite via `Database`, open per operation (invariant 7).
Depends on
    sidekick.log, sidekick.storage.

See Also
--------
    AGENTS.md "Extensions".

"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from sidekick.storage import Database

from .schemas import ExtensionRecord

MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS extensions (
        name TEXT PRIMARY KEY, path TEXT NOT NULL, version TEXT NOT NULL, enabled INTEGER NOT NULL,
        settings TEXT, source TEXT NOT NULL, installed_ts REAL NOT NULL, error TEXT
    );
    """
]


class ExtensionRegistry:
    """CRUD over extension records."""

    def __init__(self, path: Path) -> None:
        self.db = Database(path, MIGRATIONS)

    @staticmethod
    def _row(row: Any) -> ExtensionRecord:
        return ExtensionRecord(
            name=row["name"],
            path=row["path"],
            version=row["version"],
            enabled=bool(row["enabled"]),
            settings=json.loads(row["settings"] or "{}"),
            source=row["source"],
            installed_ts=row["installed_ts"],
            error=row["error"],
        )

    def save(self, record: ExtensionRecord) -> ExtensionRecord:
        """Insert or replace."""
        self.db.execute(
            "INSERT INTO extensions (name, path, version, enabled, settings, source, installed_ts, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET path = excluded.path, version = excluded.version, enabled = excluded.enabled,"
            " settings = excluded.settings, source = excluded.source, error = excluded.error",
            (
                record.name,
                record.path,
                record.version,
                int(record.enabled),
                json.dumps(record.settings, ensure_ascii=False),
                record.source,
                record.installed_ts,
                record.error,
            ),
        )
        return record

    def get(self, name: str) -> ExtensionRecord | None:
        """One record."""
        rows = self.db.query("SELECT * FROM extensions WHERE name = ?", (name,))
        return self._row(rows[0]) if rows else None

    def list_records(self) -> list[ExtensionRecord]:
        """All records by name."""
        return [self._row(r) for r in self.db.query("SELECT * FROM extensions ORDER BY name")]

    def delete(self, name: str) -> bool:
        """Remove."""
        return self.db.execute("DELETE FROM extensions WHERE name = ?", (name,)) > 0

    def set_enabled(self, name: str, enabled: bool, error: str | None = None) -> None:
        """Flip the flag (and record the last error)."""
        self.db.execute(
            "UPDATE extensions SET enabled = ?, error = ? WHERE name = ?",
            (int(enabled), error, name),
        )

    def set_settings(self, name: str, settings: dict[str, Any]) -> None:
        """Replace the settings values."""
        self.db.execute(
            "UPDATE extensions SET settings = ? WHERE name = ?",
            (json.dumps(settings, ensure_ascii=False), name),
        )

    def touch(self, name: str) -> None:
        """Update the install timestamp (after an update)."""
        self.db.execute(
            "UPDATE extensions SET installed_ts = ? WHERE name = ?", (time.time(), name)
        )
