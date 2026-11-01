"""sidekick.storage.schemas — data directory layout

Overview
    Paths under the runtime home (`./.derived_data/` by default). Everything persistent lives
    here: config spec, SQLite files, logs, audio clips, downloaded models, user extensions.
Design
    A frozen dataclass computed once from `home`; `db_path()` applies the versioned file-name
    rule (invariant 8).
Depends on
    stdlib pathlib.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StorageLayout:
    """Resolved directories under the sidekick home."""

    home: Path

    @property
    def config_path(self) -> Path:
        """User spec file, mode 0600."""
        return self.home / "config.json"

    @property
    def service_path(self) -> Path:
        """The owner's last Start / Stop, kept across restarts (`sidekick.service`)."""
        return self.home / "service.json"

    @property
    def logs_dir(self) -> Path:
        """Rotating log files."""
        return self.home / "logs"

    @property
    def audio_dir(self) -> Path:
        """Engagement clips and other audio traces."""
        return self.home / "audio"

    @property
    def models_dir(self) -> Path:
        """Downloaded ONNX models (sherpa-onnx, OpenCV)."""
        return self.home / "models"

    @property
    def extensions_dir(self) -> Path:
        """User-installed extensions."""
        return self.home / "extensions"

    @property
    def cache_dir(self) -> Path:
        """Scratch space that may be deleted at any time."""
        return self.home / "cache"

    @property
    def recordings_dir(self) -> Path:
        """Default root of the 24 h recording ring (`record` module)."""
        return self.home / "recordings"

    def db_path(self, name: str, version: int = 1) -> Path:
        """`<name>_v<version>.db` under home."""
        return self.home / f"{name}_v{version}.db"

    def directories(self) -> tuple[Path, ...]:
        """Every directory `ensure_layout()` creates."""
        return (
            self.home,
            self.logs_dir,
            self.audio_dir,
            self.recordings_dir,
            self.models_dir,
            self.extensions_dir,
            self.cache_dir,
        )
