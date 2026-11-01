import os
import sqlite3

import pytest

from sidekick.storage import Database, StorageSession, TraceTable, resolve_home


def test_resolve_home_prefers_explicit_then_env_then_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SIDEKICK_HOME", raising=False)
    assert resolve_home() == (tmp_path / ".derived_data").resolve()
    monkeypatch.setenv("SIDEKICK_HOME", str(tmp_path / "elsewhere"))
    assert resolve_home() == (tmp_path / "elsewhere").resolve()
    assert resolve_home(tmp_path / "explicit") == (tmp_path / "explicit").resolve()


def test_ensure_layout_creates_directories_and_versioned_db_names(tmp_path):
    storage = StorageSession(tmp_path / "home")
    layout = storage.ensure_layout()
    for directory in layout.directories():
        assert directory.is_dir()
    assert layout.db_path("dialogue", 1).name == "dialogue_v1.db"


def test_write_json_is_atomic_and_private(tmp_path):
    storage = StorageSession(tmp_path)
    path = tmp_path / "config.json"
    storage.write_json(path, {"b": 1, "a": "秘密"})
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert storage.read_json(path) == {"a": "秘密", "b": 1}
    assert storage.read_json(tmp_path / "missing.json") is None
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]


def test_database_migrations_apply_in_order_and_are_idempotent(tmp_path):
    path = tmp_path / "t_v1.db"
    db = Database(path, ["CREATE TABLE a (x INTEGER);"])
    assert db.user_version() == 1
    db.execute("INSERT INTO a (x) VALUES (?)", (7,))
    db2 = Database(path, ["CREATE TABLE a (x INTEGER);", "ALTER TABLE a ADD COLUMN y TEXT;"])
    assert db2.user_version() == 2
    assert db2.query("SELECT x, y FROM a")[0]["x"] == 7
    with pytest.raises(RuntimeError):
        Database(path, ["CREATE TABLE a (x INTEGER);"])


def test_transaction_rolls_back_on_error(tmp_path):
    db = Database(tmp_path / "t_v1.db", ["CREATE TABLE a (x INTEGER UNIQUE);"])
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
        conn.execute("INSERT INTO a (x) VALUES (1)")
        conn.execute("INSERT INTO a (x) VALUES (1)")
    assert db.query("SELECT COUNT(*) AS n FROM a")[0]["n"] == 0


def test_trace_table_records_recent_and_prunes(tmp_path):
    trace = TraceTable(tmp_path / "x_trace_v1.db", "calls", {"provider": "TEXT", "ok": "INTEGER"})
    trace.record(provider="minimax", ok=1)
    trace.record(provider="local", ok=0)
    rows = trace.recent()
    assert [r["provider"] for r in rows] == ["local", "minimax"]
    assert trace.count() == 2
    with pytest.raises(ValueError):
        trace.record(nope=1)
    assert trace.prune(days=0) == 2
    assert trace.count() == 0


def test_trace_table_rejects_bad_names(tmp_path):
    with pytest.raises(ValueError):
        TraceTable(tmp_path / "x.db", "bad name", {})
    with pytest.raises(ValueError):
        TraceTable(tmp_path / "x.db", "ok", {"id": "TEXT"})
    os.environ.pop("SIDEKICK_HOME", None)
