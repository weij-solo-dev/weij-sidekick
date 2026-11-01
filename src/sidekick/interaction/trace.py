"""sidekick.interaction.trace — every engagement and interruption decision, with its clip

Overview
    Invariant 18: each accept / reject / duck / resume / stop decision is stored with its scores
    (name match, speaker, DoA, duration), the transcript when one exists, the turn latencies and
    a short WAV clip under `.derived_data/audio/`, pruned after `trace_retention_days`. The
    dashboard's listening monitor reads this table so thresholds are tuned on household data.
Design
    A `TraceTable` (`interaction_trace_v1.db`, table `decisions`) plus flat WAV files named by
    row id. Writes happen on the asyncio side after decisions; clip encoding is cheap (16-bit
    PCM). Pruning removes rows and their files together.
Depends on
    sidekick.log, sidekick.storage, sidekick.audio.

See Also
--------
    AGENTS.md invariant 18, PLAN.md block #7.

"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from sidekick.audio import AudioClip
from sidekick.log import Log
from sidekick.storage import TraceTable

COLUMNS = {
    "state": "TEXT",
    "event": "TEXT",
    "decision": "TEXT",
    "reason": "TEXT",
    "trigger_name": "TEXT",
    "name_score": "REAL",
    "speaker": "TEXT",
    "doa": "REAL",
    "duration_s": "REAL",
    "text": "TEXT",
    "reply": "TEXT",
    "clip": "TEXT",
    "timing": "TEXT",
}


class InteractionTrace:
    """Decision rows + clips."""

    def __init__(
        self, path: Path, audio_dir: Path, retention_days: float = 7.0, clip_max_s: float = 6.0
    ) -> None:
        self.table = TraceTable(path, "decisions", COLUMNS)
        self.audio_dir = audio_dir
        self.retention_days = retention_days
        self.clip_max_s = clip_max_s
        self.clip_files = True  # False when the recording ring serves the clips instead
        self.clip_retention_days = 1.0  # files under audio/ never outlive the ring's 24 h
        self.pre_roll_s = 1.0  # the front end's pre-roll, part of every segment clip
        self._last_prune = 0.0

    def record(
        self,
        state: str,
        event: str,
        decision: str,
        reason: str,
        *,
        trigger: str | None = None,
        name_score: float | None = None,
        speaker: str | None = None,
        doa: float | None = None,
        duration_s: float | None = None,
        text: str | None = None,
        reply: str | None = None,
        clip: AudioClip | None = None,
        timing: dict[str, Any] | None = None,
    ) -> str:
        """Store one decision; returns the row id (also the clip file stem)."""
        clip_name: str | None = None
        row_id = self.table.record(
            state=state,
            event=event,
            decision=decision,
            reason=reason,
            trigger_name=trigger,
            name_score=name_score,
            speaker=speaker,
            doa=doa,
            duration_s=duration_s,
            text=text,
            reply=reply,
            clip=None,
            timing=json.dumps(timing, ensure_ascii=False) if timing else None,
        )
        if clip is not None and clip.duration_s > 0 and not self.clip_files:
            self.table.db.execute(
                f"UPDATE {self.table.table} SET clip = ? WHERE id = ?", ("ring", row_id)
            )
        elif clip is not None and clip.duration_s > 0:
            try:
                self.audio_dir.mkdir(parents=True, exist_ok=True)
                samples = clip.samples[: int(self.clip_max_s * clip.sample_rate)]
                path = self.audio_dir / f"interaction_{row_id}.wav"
                path.write_bytes(AudioClip(samples, clip.sample_rate).to_wav_bytes())
                clip_name = path.name
                self.table.db.execute(
                    f"UPDATE {self.table.table} SET clip = ? WHERE id = ?", (clip_name, row_id)
                )
            except Exception as exc:
                Log.warning(f"clip not saved: {exc!r}")
        self._maybe_prune()
        return row_id

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Newest decisions first."""
        rows = self.table.recent(limit)
        for row in rows:
            if row.get("timing"):
                try:
                    row["timing"] = json.loads(row["timing"])
                except ValueError:
                    pass
        return rows

    def between(self, start_ts: float, end_ts: float) -> list[dict[str, Any]]:
        """Decisions in a time range, oldest first (replay)."""
        rows = self.table.between(start_ts, end_ts)
        for row in rows:
            if row.get("timing"):
                try:
                    row["timing"] = json.loads(row["timing"])
                except ValueError:
                    pass
        return rows

    def clip_path(self, row_id: str) -> Path | None:
        """The WAV file for a decision, if it exists."""
        path = self.audio_dir / f"interaction_{row_id}.wav"
        return path if path.exists() else None

    def clip_window(self, row_id: str) -> tuple[float, float] | None:
        """Wall-clock span of a decision's audio (segment plus pre-roll) for the ring."""
        rows = self.table.db.query(
            f"SELECT ts, duration_s FROM {self.table.table} WHERE id = ?", (row_id,)
        )
        if not rows:
            return None
        ts = float(rows[0]["ts"])
        duration = float(rows[0]["duration_s"] or 0.0)
        start = ts - min(duration + self.pre_roll_s, self.clip_max_s)
        return start, ts + 0.1

    def _maybe_prune(self) -> None:
        now = time.time()
        if now - self._last_prune < 3600.0:
            return
        self._last_prune = now
        self.prune()

    def prune(self) -> int:
        """Delete rows older than the retention and clip files older than `clip_retention_days`."""
        cutoff = time.time() - self.retention_days * 86400.0
        rows = self.table.db.query(f"SELECT id FROM {self.table.table} WHERE ts < ?", (cutoff,))
        for row in rows:
            (self.audio_dir / f"interaction_{row['id']}.wav").unlink(missing_ok=True)
        file_cutoff = time.time() - self.clip_retention_days * 86400.0
        if self.audio_dir.is_dir():
            for path in self.audio_dir.glob("interaction_*.wav"):
                try:
                    if path.stat().st_mtime < file_cutoff:
                        path.unlink()
                except OSError:
                    pass
        removed = self.table.prune(self.retention_days)
        if removed:
            Log.info(f"pruned {removed} interaction decision(s)")
        return removed
