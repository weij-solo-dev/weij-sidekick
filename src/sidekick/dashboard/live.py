"""sidekick.dashboard.live — the Live tab's data feed: state frames, module vital signs, activity

Overview
    `LiveFeed.frame()` assembles one JSON frame for the `/api/live` WebSocket from the sessions
    the dashboard context already holds. At 10 Hz: body telemetry (commanded and measured pose,
    joints, audio levels and peak rings), the interaction state and captions, presence, faces
    and the perception events that appeared since the previous frame. Once a second the frame
    also carries `modules` — every core module's `live()` vital signs (interaction, body,
    perception, contact, agent, memory, automation, channel, record, extension, the services
    llm / asr / tts, and the system: readiness, uptime, host vitals, warnings) — and
    `activity`: what the modules did since the previous push (decisions, events, turns and
    tools, job runs, channel traffic, warnings), newest first. `mjpeg_stream()` is the async
    generator behind `/api/body/stream.mjpg`: the latest camera frame, scaled and JPEG-encoded
    off the event loop, at a capped rate.
Design
    One frame is one dict built from cheap synchronous reads — every `live()` returns values
    held in memory (no SQL, no HTTP, no directory walk; block #69), so the WebSocket route is a
    loop of `frame()` + `sleep` on the event loop. A module whose `live()` raises is reported
    as `{"error": …}` and the rest still arrive. Each feed instance is per connection and keeps
    its own cursors (the last event and activity timestamps), so several browser tabs do not
    interfere; the first push carries the newest activity so the stream is never empty on
    load. The MJPEG generator yields multipart parts and simply stops when the client goes
    away (Starlette cancels the response task), and skips a tick when the body has no frame yet
    instead of failing.
    Each frame carries the service's state; every read is wrapped, so a module that cannot
    answer (the service stopping) never closes the socket, and the MJPEG stream ends 2 s after
    the robot disconnects (block #87).
Depends on
    sidekick.body, sidekick.interaction, sidekick.perception, sidekick.agent, sidekick.automation,
    sidekick.channel, sidekick.record, sidekick.extension, sidekick.doctor (duck-typed through
    the context), sidekick.llm / asr / tts (their shared sessions), sidekick.log (`recent`,
    `counts`), sidekick.contact (`brighten_frame`: the stream is gamma-lifted when the room is
    dark, like the detector's input), numpy, opencv (lazy).

See Also
--------
    AGENTS.md "Dashboard and CLI", PLAN.md blocks "[2026-10-26 #25]", "[2026-10-29 #69]".

"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import numpy as np
import numpy.typing as npt

from sidekick.asr import ASRSession
from sidekick.contact import brighten_frame
from sidekick.llm import LLMSession
from sidekick.log import Log
from sidekick.tts import TTSSession

from .vitals import HostVitals

MJPEG_BOUNDARY = b"sidekickframe"
INTERACTION_KEYS = (
    "state",
    "reason",
    "session",
    "held",
    "ducked",
    "speaking",
    "turn_running",
    "tts_connected",
    "level_dbfs",
    "self_sector_yaw",
    "attention",
    "initiative",
)
MODULES_PERIOD_S = 1.0  # module vital signs and activity ride on one frame a second
ACTIVITY_PUSH = 40  # rows in one push at most


class LiveFeed:
    """Per-connection frame builder."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.last_event_ts = time.time()
        self.frames = 0
        self.modules_at = 0.0
        self.activity_ts = 0.0  # the first push carries the newest activity

    @staticmethod
    def _safe(read: Any) -> Any:
        try:
            return read()
        except Exception as exc:  # one module's failure never stops the feed
            Log.debug(f"live: {exc!r}")
            return {"error": repr(exc)[:200]}

    def modules(self) -> dict[str, Any]:
        """Every core module's vital signs (`live()`), memory only."""
        ctx = self.ctx
        safe = self._safe
        out: dict[str, Any] = {}
        for name, session in (
            ("interaction", ctx.interaction),
            ("body", ctx.body),
            ("perception", ctx.perception),
            ("agent", ctx.agent),
            ("automation", ctx.automation),
            ("channel", ctx.channels),
            ("record", ctx.record),
            ("extension", ctx.extensions),
        ):
            if session is not None and hasattr(session, "live"):
                out[name] = safe(session.live)
        if ctx.contacts is not None and getattr(ctx.contacts, "ready", False):
            out["contact"] = safe(ctx.contacts.live)
        if ctx.agent is not None and hasattr(ctx.agent, "memory_live"):
            out["memory"] = safe(ctx.agent.memory_live)
        out["services"] = {
            "llm": safe(LLMSession.shared.live),
            "asr": safe(ASRSession.shared.live),
            "tts": safe(TTSSession.shared.live),
        }
        if ctx.service is not None:
            out["service"] = safe(ctx.service.live)
        out["system"] = {
            "uptime_s": round(time.time() - ctx.started_at),
            "doctor": safe(ctx.doctor.live) if ctx.doctor is not None else None,
            "host": safe(HostVitals.shared.sample),
            "log": Log.counts(600.0),
        }
        return out

    def activity(self) -> list[dict[str, Any]]:
        """What the modules did since the previous push, newest first."""
        ctx = self.ctx
        since = self.activity_ts
        rows: list[dict[str, Any]] = []
        for session in (ctx.interaction, ctx.perception, ctx.agent, ctx.automation, ctx.channels):
            if session is not None and hasattr(session, "activity"):
                got = self._safe(lambda s=session: s.activity(since))
                if isinstance(got, list):
                    rows.extend(got)
        for row in Log.recent(20, since):
            rows.append(
                {
                    "ts": row["ts"],
                    "module": "system",
                    "text": f"{row['where']}: {row['message']}",
                    "level": "bad" if row["level"] in ("error", "critical") else "warn",
                }
            )
        rows.sort(key=lambda row: row["ts"], reverse=True)
        rows = rows[:ACTIVITY_PUSH]
        if rows:
            self.activity_ts = rows[0]["ts"]
        return rows

    def frame(self) -> dict[str, Any]:
        """One JSON-ready state frame; a module that cannot answer never closes the socket."""
        ctx = self.ctx
        self.frames += 1
        now = time.time()
        safe = self._safe
        out: dict[str, Any] = {"ts": round(now, 3), "seq": self.frames}
        service = ctx.service
        out["service"] = service.state if service is not None else None
        out["body"] = safe(lambda: ctx.body.telemetry().as_dict()) if ctx.body is not None else None
        if ctx.interaction is not None:
            snapshot = safe(ctx.interaction.snapshot)
            out["interaction"] = {k: snapshot.get(k) for k in INTERACTION_KEYS}
            out["captions"] = safe(ctx.interaction.captions)
        else:
            out["interaction"] = {"state": "off"}
            out["captions"] = None
        if ctx.perception is not None:
            per = safe(ctx.perception.snapshot)
            out["presence"] = per.get("presence")
            out["faces"] = per.get("faces", [])
            recent = safe(lambda: ctx.perception.recent(30))
            events = (
                [e for e in recent if e["ts"] > self.last_event_ts]
                if isinstance(recent, list)
                else []
            )
            if events:
                self.last_event_ts = max(e["ts"] for e in events)
            out["events"] = list(reversed(events))
        else:
            out["presence"] = None
            out["events"] = []
        if now - self.modules_at >= MODULES_PERIOD_S:
            self.modules_at = now
            out["modules"] = self.modules()
            out["activity"] = safe(self.activity)
        return out


def encode_jpeg(
    frame: npt.NDArray[np.uint8], width: int, quality: int, brighten: bool = True
) -> bytes | None:
    """Scale a BGR frame to `width`, lift it when dark, JPEG-encode (worker thread)."""
    import cv2

    h, w = frame.shape[:2]
    image: Any = frame
    if w > width:
        image = cv2.resize(
            frame, (width, max(1, round(h * width / w))), interpolation=cv2.INTER_AREA
        )
    if brighten:
        image = brighten_frame(image)
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return bytes(encoded.tobytes()) if ok else None


async def mjpeg_stream(
    body: Any, width: int = 640, fps: float = 8.0, quality: int = 70
) -> AsyncIterator[bytes]:
    """Multipart JPEG parts at up to `fps`, until the client disconnects or the robot is off.

    A body disconnected for 2 s (the service stopped) ends the stream, so the page shows its
    placeholder instead of a frozen frame and opens a new stream after the next start.
    """
    period = 1.0 / max(1.0, min(fps, 30.0))
    gone_since: float | None = None
    while True:
        started = time.monotonic()
        if body is None or not getattr(body, "connected", True):
            gone_since = gone_since or started
            if started - gone_since > 2.0:
                return
        else:
            gone_since = None
        frame = body.frame() if body is not None else None
        if frame is not None:
            data = await asyncio.to_thread(encode_jpeg, frame, width, quality)
            if data is not None:
                yield (
                    b"--" + MJPEG_BOUNDARY + b"\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n"
                )
        await asyncio.sleep(max(0.01, period - (time.monotonic() - started)))
