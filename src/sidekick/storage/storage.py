"""sidekick.storage.storage — runtime home, SQLite access pattern, JSON spec files, downloads

Overview
    `StorageSession` owns the runtime home (`SIDEKICK_HOME` or `./.derived_data`), creates the
    directory layout, reads and writes the JSON spec with mode 0600, and downloads model
    archives. The SQLite pattern itself lives in `database.py` and the trace table in
    `trace.py`; this façade re-exports both.
Design
    Spec files are written atomically (temp file + rename) with the requested mode so a crash
    never leaves a half-written or world-readable secret. Downloads stream to a temporary file
    and are moved into place only when complete; `tar.bz2` archives are extracted with the
    `data` filter.
Depends on
    sidekick.log; httpx for downloads; stdlib json, os, tarfile.

See Also
--------
    AGENTS.md "Core rules" 7 and 8, "Storage and data directory".

"""

from __future__ import annotations

import json
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Any, ClassVar

import httpx

from sidekick.log import Log

from .database import Database
from .schemas import StorageLayout

HOME_ENV = "SIDEKICK_HOME"
DEFAULT_HOME_NAME = ".derived_data"


def resolve_home(explicit: Path | None = None) -> Path:
    """Explicit path, else `$SIDEKICK_HOME`, else `./.derived_data`."""
    if explicit is not None:
        return explicit.expanduser().resolve()
    env = os.environ.get(HOME_ENV)
    if env:
        return Path(env).expanduser().resolve()
    return (Path.cwd() / DEFAULT_HOME_NAME).resolve()


class StorageSession:
    """Runtime home and file helpers."""

    shared: ClassVar[StorageSession]

    def __init__(self, home: Path | None = None) -> None:
        self.layout = StorageLayout(resolve_home(home))

    @property
    def home(self) -> Path:
        """The runtime home directory."""
        return self.layout.home

    def ensure_layout(self) -> StorageLayout:
        """Create every directory of the layout."""
        for directory in self.layout.directories():
            directory.mkdir(parents=True, exist_ok=True)
        return self.layout

    def read_json(self, path: Path) -> Any:
        """Parse a JSON file, or return None when it does not exist."""
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def write_json(self, path: Path, value: Any, mode: int = 0o600) -> None:
        """Write JSON atomically with the given file mode (0600 for anything with secrets)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
            os.chmod(tmp_name, mode)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    BACKUP_EXCLUDE: ClassVar[tuple[str, ...]] = (
        "models",
        "cache",
        "logs",
        "extension_state",
        "recordings",
    )

    def backup(self, dest: Path) -> Path:
        """Write a tar.gz of the home without models, cache, logs and extension state."""
        import tarfile

        dest.parent.mkdir(parents=True, exist_ok=True)
        home = self.layout.home
        with tarfile.open(dest, "w:gz") as archive:
            for child in sorted(home.iterdir()):
                if child.name in self.BACKUP_EXCLUDE or child.name.endswith(".pid"):
                    continue
                archive.add(child, arcname=child.name)
        Log.info(f"backup written: {dest}")
        return dest

    def restore(self, archive_path: Path, force: bool = False) -> list[str]:
        """Extract a backup into the home; refuses a non-empty home unless `force`."""
        import tarfile

        home = self.layout.home
        home.mkdir(parents=True, exist_ok=True)
        existing = [
            c.name
            for c in home.iterdir()
            if c.name not in self.BACKUP_EXCLUDE and not (c.is_dir() and not any(c.iterdir()))
        ]
        if existing and not force:
            raise FileExistsError(f"home {home} is not empty ({existing[:5]}); use --force")
        names: list[str] = []
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                target = (home / member.name).resolve()
                if not str(target).startswith(str(home.resolve())):
                    raise ValueError(f"unsafe path in archive: {member.name}")
                names.append(member.name)
            archive.extractall(home, filter="data")
        if (home / "config.json").exists():
            os.chmod(home / "config.json", 0o600)
        Log.info(f"backup restored into {home}: {len(names)} entries")
        return names

    def ensure_download(self, url: str, dest: Path, extract: bool = False) -> Path:
        """Download `url` to `dest` unless present; optionally extract a tar.bz2 next to it.

        With `extract=True`, `dest` is the archive path and the returned path is the extracted
        directory (archive name without `.tar.bz2`), which is skipped when it already exists.
        """
        target_dir = dest.with_name(dest.name.removesuffix(".tar.bz2")) if extract else dest
        if target_dir.exists():
            return target_dir
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            Log.info(f"downloading {url} -> {dest}")
            tmp = dest.with_suffix(dest.suffix + ".part")
            with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as response:
                response.raise_for_status()
                with tmp.open("wb") as handle:
                    for chunk in response.iter_bytes(1 << 20):
                        handle.write(chunk)
            if tmp.stat().st_size == 0:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(f"empty download: {url}")
            os.replace(tmp, dest)
        if extract:
            Log.info(f"extracting {dest.name}")
            with tarfile.open(dest, "r:bz2") as archive:
                archive.extractall(dest.parent, filter="data")
            if not target_dir.exists():
                raise RuntimeError(f"archive did not produce {target_dir}")
            dest.unlink(missing_ok=True)
        return target_dir


__all__ = ["Database", "StorageSession", "resolve_home"]

StorageSession.shared = StorageSession()
