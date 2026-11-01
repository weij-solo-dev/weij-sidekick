"""sidekick.record.chunks — chunk directories: naming, listing, sizes, free disk, pruning

Overview
    Pure filesystem helpers over the recordings root: `chunk_path()` maps a timestamp to
    `root/YYYY-MM-DD/HH-MM-SS`, `list_days()` / `list_chunks()` read the `chunk.json` descriptors,
    `dir_bytes()` / `free_gb()` measure, `prune()` removes chunks older than the retention and,
    if the disk is still below the floor, the oldest closed chunks until it is not.
Design
    No state and no threads: the recorder calls these from its thread, the dashboard and the CLI
    from theirs, and every call re-reads the disk so a chunk deleted by hand simply disappears.
    A chunk without `chunk.json` (killed before the descriptor was written) is described from the
    directory name and file sizes so it still shows up and is still pruned. Local time is used for
    the names because the owner reads them; `start_ts` in the descriptor is the epoch truth.
Depends on
    stdlib only.

See Also
--------
    AGENTS.md "Recording", PLAN.md block "[2026-10-26 #25]".

"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from .schemas import CHUNK_FILE, RecordChunk

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}-\d{2}-\d{2}$")
CHUNK_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}/\d{2}-\d{2}-\d{2}$")


def chunk_id(ts: float) -> str:
    """`YYYY-MM-DD/HH-MM-SS` in local time."""
    return time.strftime("%Y-%m-%d/%H-%M-%S", time.localtime(ts))


def chunk_path(root: Path, ts: float) -> Path:
    """Directory for a chunk starting at `ts`."""
    return root / chunk_id(ts)


def resolve(root: Path, identifier: str) -> Path | None:
    """The directory for a chunk id, or None for anything that is not a well-formed id."""
    if not CHUNK_ID_RE.match(identifier):
        return None
    path = root / identifier
    return path if path.is_dir() else None


def dir_bytes(path: Path) -> int:
    """Sum of file sizes directly inside a chunk directory."""
    total = 0
    try:
        for child in path.iterdir():
            if child.is_file():
                total += child.stat().st_size
    except OSError:
        pass
    return total


def free_gb(path: Path) -> float:
    """Free space on the volume holding `path` (walks up to an existing parent)."""
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free / 1e9
    except OSError:
        return 0.0


def read_chunk(path: Path) -> RecordChunk | None:
    """Describe a chunk directory (from `chunk.json`, else from its name and files)."""
    if not path.is_dir() or not TIME_RE.match(path.name) or not DAY_RE.match(path.parent.name):
        return None
    descriptor = path / CHUNK_FILE
    chunk: RecordChunk | None = None
    if descriptor.exists():
        try:
            chunk = RecordChunk.from_dict(json.loads(descriptor.read_text(encoding="utf-8")), path)
        except (ValueError, OSError):
            chunk = None
    if chunk is None:
        try:
            start = time.mktime(
                time.strptime(f"{path.parent.name}/{path.name}", "%Y-%m-%d/%H-%M-%S")
            )
        except ValueError:
            return None
        chunk = RecordChunk(
            id=f"{path.parent.name}/{path.name}", path=path, start_ts=start, open=False
        )
        chunk.end_ts = max(start, path.stat().st_mtime)
    chunk.bytes = dir_bytes(path)
    return chunk


def list_days(root: Path) -> list[str]:
    """Day directories, oldest first."""
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir() and DAY_RE.match(d.name))


def list_chunks(root: Path, day: str | None = None) -> list[RecordChunk]:
    """Chunks of one day (or every day), oldest first."""
    days = [day] if day else list_days(root)
    out: list[RecordChunk] = []
    for name in days:
        day_dir = root / name
        if not day_dir.is_dir():
            continue
        for child in sorted(day_dir.iterdir()):
            chunk = read_chunk(child)
            if chunk is not None:
                out.append(chunk)
    return out


def remove_chunk(chunk: RecordChunk) -> None:
    """Delete a chunk directory and its day directory when that becomes empty."""
    shutil.rmtree(chunk.path, ignore_errors=True)
    day_dir = chunk.path.parent
    try:
        if day_dir.is_dir() and not any(day_dir.iterdir()):
            day_dir.rmdir()
    except OSError:
        pass


def prune(
    root: Path,
    retention_hours: float,
    min_free_gb: float = 0.0,
    now: float | None = None,
    keep: str | None = None,
) -> list[RecordChunk]:
    """Remove chunks older than the retention, then the oldest closed ones while the disk is low."""
    now = time.time() if now is None else now
    removed: list[RecordChunk] = []
    cutoff = now - retention_hours * 3600.0
    remaining: list[RecordChunk] = []
    for chunk in list_chunks(root):
        if chunk.id == keep:
            remaining.append(chunk)
            continue
        if chunk.start_ts < cutoff:
            remove_chunk(chunk)
            removed.append(chunk)
        else:
            remaining.append(chunk)
    while min_free_gb > 0 and free_gb(root) < min_free_gb and remaining:
        oldest = remaining.pop(0)
        if oldest.id == keep:
            break
        remove_chunk(oldest)
        removed.append(oldest)
    return removed
