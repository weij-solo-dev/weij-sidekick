"""sidekick.record.schemas — settings, chunk descriptors and status for the recorder

Overview
    `RecordSettings` is what the recorder runs on (built from the config section by
    `from_config`, duck-typed so this module never imports `config`), `RecordChunk` describes one
    chunk directory (written to and read from `chunk.json`), `RecordStatus` is the Health card.
Design
    Frozen dataclasses with JSON helpers; chunk ids are `YYYY-MM-DD/HH-MM-SS` (local time), which
    doubles as the directory path under the recordings root so the id is the only key the
    dashboard needs. Sizes are bytes, times are epoch seconds.
Depends on
    stdlib only.

See Also
--------
    AGENTS.md "Recording", PLAN.md block "[2026-10-26 #25]".

"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

AUDIO_CODECS = ("wav", "flac")
CHUNK_FILE = "chunk.json"
VIDEO_FILE = "video.mp4"
TELEMETRY_FILE = "telemetry.jsonl"
TELEMETRY_GZ = "telemetry.jsonl.gz"


@dataclass(frozen=True, slots=True)
class RecordSettings:
    """How to record."""

    root: Path
    enabled: bool = True
    chunk_s: float = 300.0
    retention_hours: float = 24.0
    min_free_gb: float = 20.0
    width: int = 1280
    height: int = 720
    fps: float = 10.0
    bitrate_kbps: int = 1000
    audio_codec: str = "wav"
    telemetry_hz: float = 10.0
    sample_rate: int = 16000

    @classmethod
    def from_config(cls, config: Any, default_root: Path) -> RecordSettings:
        """From a `ConfigRecording`-shaped object (duck-typed to keep `record` below `config`)."""
        root = getattr(config, "root", None)
        return cls(
            root=Path(root).expanduser() if root else default_root,
            enabled=bool(getattr(config, "enabled", True)),
            chunk_s=float(getattr(config, "chunk_minutes", 5.0)) * 60.0,
            retention_hours=float(getattr(config, "retention_hours", 24.0)),
            min_free_gb=float(getattr(config, "min_free_gb", 20.0)),
            width=int(getattr(config, "width", 1280)),
            height=int(getattr(config, "height", 720)),
            fps=float(getattr(config, "fps", 10.0)),
            bitrate_kbps=int(getattr(config, "bitrate_kbps", 1000)),
            audio_codec=str(getattr(config, "audio_codec", "wav")),
            telemetry_hz=float(getattr(config, "telemetry_hz", 10.0)),
        )


@dataclass(slots=True)
class RecordChunk:
    """One chunk directory."""

    id: str
    path: Path
    start_ts: float
    end_ts: float | None = None
    frames: int = 0
    mic_samples: int = 0
    speaker_samples: int = 0
    telemetry_rows: int = 0
    bytes: int = 0
    video: str | None = None
    audio_codec: str = "wav"
    sample_rate: int = 16000
    fps: float = 10.0
    errors: list[str] = field(default_factory=list)
    open: bool = False
    activity: float = 0.0

    @property
    def duration_s(self) -> float:
        """Seconds covered (closed chunks) or elapsed so far."""
        end = self.end_ts if self.end_ts is not None else time.time()
        return max(0.0, end - self.start_ts)

    def as_dict(self) -> dict[str, Any]:
        """JSON form (also the `chunk.json` content)."""
        return {
            "id": self.id,
            "start_ts": round(self.start_ts, 3),
            "end_ts": None if self.end_ts is None else round(self.end_ts, 3),
            "duration_s": round(self.duration_s, 1),
            "frames": self.frames,
            "mic_samples": self.mic_samples,
            "speaker_samples": self.speaker_samples,
            "telemetry_rows": self.telemetry_rows,
            "bytes": self.bytes,
            "video": self.video,
            "audio_codec": self.audio_codec,
            "sample_rate": self.sample_rate,
            "fps": self.fps,
            "errors": list(self.errors),
            "open": self.open,
            "activity": round(self.activity, 3),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Path) -> RecordChunk:
        """Inverse of `as_dict` (missing keys default)."""
        return cls(
            id=str(data.get("id") or f"{path.parent.name}/{path.name}"),
            path=path,
            start_ts=float(data.get("start_ts") or 0.0),
            end_ts=data.get("end_ts"),
            frames=int(data.get("frames") or 0),
            mic_samples=int(data.get("mic_samples") or 0),
            speaker_samples=int(data.get("speaker_samples") or 0),
            telemetry_rows=int(data.get("telemetry_rows") or 0),
            bytes=int(data.get("bytes") or 0),
            video=data.get("video"),
            audio_codec=str(data.get("audio_codec") or "wav"),
            sample_rate=int(data.get("sample_rate") or 16000),
            fps=float(data.get("fps") or 10.0),
            errors=[str(e) for e in data.get("errors") or []],
            open=bool(data.get("open", False)),
            activity=float(data.get("activity") or 0.0),
        )


@dataclass(frozen=True, slots=True)
class RecordStatus:
    """What the Health card and the Record page show."""

    state: str
    root: str
    chunk: str | None
    chunks: int
    hours: float
    size_gb: float
    free_gb: float
    min_free_gb: float
    retention_hours: float
    video: str | None
    errors: str | None
    frames: int = 0

    def as_dict(self) -> dict[str, Any]:
        """JSON form."""
        return {
            "state": self.state,
            "root": self.root,
            "chunk": self.chunk,
            "chunks": self.chunks,
            "hours": round(self.hours, 2),
            "size_gb": round(self.size_gb, 3),
            "free_gb": round(self.free_gb, 1),
            "min_free_gb": self.min_free_gb,
            "retention_hours": self.retention_hours,
            "video": self.video,
            "errors": self.errors,
            "frames": self.frames,
        }
