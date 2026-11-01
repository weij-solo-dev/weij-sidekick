"""sidekick.dashboard.replay — track data for one recorded chunk (Replay tab)

Overview
    `chunk_tracks()` turns a chunk into what the Replay canvas draws under the video: peak
    envelopes of the mic and speaker tracks (binned server-side from the WAV files), and the
    timestamped rows of the SQLite stores that fall inside the chunk — dialogue messages (user,
    assistant, tool steps), engagement decisions, persisted perception events — each with an
    offset in seconds from the chunk start so the browser maps them straight onto the timeline.
Design
    Audio peaks are computed with numpy over the whole file (≤ 5 min at 16 kHz, a few ms); FLAC
    chunks (Pi profile) get no envelope here because decoding would need GStreamer on the
    request path — the browser still plays them. Store queries go through the new `between()`
    helpers, which keep the dashboard free of SQL. Nothing here is cached: a chunk is read when
    the operator opens it.
Depends on
    numpy; the sessions reached through `DashboardContext` (duck-typed).

See Also
--------
    AGENTS.md "Dashboard and CLI", PLAN.md block "[2026-10-26 #25]".

"""

from __future__ import annotations

import time
import wave
from pathlib import Path
from typing import Any

import numpy as np


def wav_peaks(path: Path, bin_s: float) -> tuple[list[float], int]:
    """Per-bin absolute peaks (0..1) of a PCM16 mono WAV and its sample rate."""
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            frames = handle.getnframes()
            data = handle.readframes(frames)
    except (OSError, wave.Error):
        return [], 16000
    samples = np.frombuffer(data, dtype="<i2")
    if len(samples) == 0:
        return [], rate
    size = max(1, int(rate * bin_s))
    count = (len(samples) + size - 1) // size
    padded = np.zeros(count * size, dtype=np.int16)
    padded[: len(samples)] = samples
    peaks = np.abs(padded.reshape(count, size).astype(np.int32)).max(axis=1) / 32768.0
    return [round(float(v), 3) for v in peaks], rate


def chunk_tracks(chunk: Any, ctx: Any, bin_s: float = 0.25) -> dict[str, Any]:
    """Everything the Replay tab draws for one chunk."""
    bin_s = min(max(bin_s, 0.05), 5.0)
    start = float(chunk.start_ts)
    end = float(chunk.end_ts) if chunk.end_ts is not None else time.time()
    out: dict[str, Any] = {
        "id": chunk.id,
        "start_ts": start,
        "end_ts": end,
        "duration_s": round(end - start, 1),
        "bin_s": bin_s,
        "has_video": (chunk.path / "video.mp4").is_file(),
        "audio": {},
        "dialogue": [],
        "decisions": [],
        "events": [],
    }
    for name in ("mic", "speaker"):
        wav = chunk.path / f"{name}.wav"
        flac = chunk.path / f"{name}.flac"
        if wav.is_file():
            peaks, _ = wav_peaks(wav, bin_s)
            out["audio"][name] = {"file": wav.name, "peaks": peaks}
        elif flac.is_file():
            out["audio"][name] = {"file": flac.name, "peaks": []}
    agent = getattr(ctx, "agent", None)
    if agent is not None:
        for row in agent.dialogue.between(start, end):
            out["dialogue"].append(
                {
                    "at": round(row.ts - start, 2),
                    "ts": row.ts,
                    "channel": row.channel,
                    "speaker": row.speaker,
                    "role": row.role,
                    "visibility": row.visibility,
                    "content": row.content[:300],
                    "tool": (row.meta or {}).get("tool"),
                }
            )
    interaction = getattr(ctx, "interaction", None)
    trace = getattr(interaction, "trace", None) if interaction is not None else None
    if trace is not None:
        for row in trace.between(start, end):
            out["decisions"].append(
                {
                    "at": round(float(row["ts"]) - start, 2),
                    "ts": row["ts"],
                    "event": row.get("event"),
                    "decision": row.get("decision"),
                    "reason": row.get("reason"),
                    "state": row.get("state"),
                    "text": row.get("text"),
                    "reply": row.get("reply"),
                    "speaker": row.get("speaker"),
                    "id": row.get("id"),
                    "clip": bool(row.get("clip")),
                }
            )
    perception = getattr(ctx, "perception", None)
    if perception is not None:
        for event in perception.stored_between(start, end):
            out["events"].append(
                {
                    "at": round(float(event["ts"]) - start, 2),
                    "ts": event["ts"],
                    "type": event["type"],
                    "severity": event["severity"],
                    "data": event["data"],
                }
            )
    return out
