"""sidekick.perception.perception — PerceptionSession: the event bus and the core event sources

Overview
    One asyncio event bus for everything the robot notices (`presence.*`, `face.*`, `gaze.*`
    incl. `gaze.mutual`, `audio.*`, `person.ready` / `greet.due` from `interaction`, and
    `feed.update`, `job.done`, `ha.state` from extension watchers).
    Subscribers are async callbacks with type patterns; events of `severity >= notice` persist to
    `events_v1.db`; a short in-memory history feeds the dashboard. Core sources are the camera
    presence watcher and the audio watcher over `BodySession`.
Design
    `publish()` fans out sequentially and isolates subscriber errors; sources are `Watcher`s so
    extensions register theirs the same way (`register_watcher`). `presence()` is the snapshot
    consumed by the delivery policy. The bus never touches the body (it only reads). `setup`
    attaches the camera and audio watchers only when `perception.enabled` is on and the body it
    is given is connected; without them the bus still carries extension and agent events.
    Since block #87 the service restarts it in place: `setup` binds the store, the body and the
    settings, `start()` makes the body watchers (the body is connected by then) and `stop()` drops
    them; `on_face` listeners and subscriptions are kept once, whatever the restarts; `check()`
    reports our face detector.
Depends on
    sidekick.log, sidekick.storage, sidekick.body.

See Also
--------
    AGENTS.md "Perception", PLAN.md block "[2026-10-26 #16]".

"""

from __future__ import annotations

import collections
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, ClassVar

from sidekick.body import BodyFace, BodySession
from sidekick.log import Log
from sidekick.storage import Database

from .audio import AudioWatcher
from .camera import CameraWatcher
from .schemas import PerceptionEvent, Presence, Severity
from .watcher import Watcher

Subscriber = Callable[[PerceptionEvent], Awaitable[None]]

MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, type TEXT NOT NULL,
        severity INTEGER NOT NULL, source TEXT NOT NULL, data TEXT
    );
    CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
    """
]


class PerceptionSession:
    """Event bus + sources."""

    shared: ClassVar[PerceptionSession]

    def __init__(self) -> None:
        self._subscribers: list[tuple[str, Subscriber]] = []
        self.history: collections.deque[PerceptionEvent] = collections.deque(maxlen=200)
        self.db: Database | None = None
        self.persist_min = Severity.NOTICE
        self.watchers: dict[str, Watcher] = {}
        self.camera: CameraWatcher | None = None
        self.audio: AudioWatcher | None = None
        self.published = 0
        self._today: tuple[str, dict[str, int]] = ("", {})  # local date, event type → count
        self.started = False
        self.enabled = True
        self.body: BodySession | None = None
        self.contacts: Any = None
        self.config: Any = None
        self._face_listeners: list[Callable[[BodyFace], None]] = []

    def setup(
        self,
        body: BodySession | None = None,
        db_path: Path | None = None,
        config: Any = None,
        contacts: Any = None,
    ) -> None:
        """Bind the store, the body and the settings; the body watchers are made by `start()`."""
        self.enabled = bool(getattr(config, "enabled", True))
        self.body, self.contacts, self.config = body, contacts, config
        if config is not None:
            self.history = collections.deque(
                self.history, maxlen=int(getattr(config, "history", 200))
            )
            self.persist_min = Severity.parse(
                str(getattr(config, "persist_min_severity", "notice"))
            )
        if db_path is not None:
            self.db = Database(db_path, MIGRATIONS)

    def register_watcher(self, watcher: Watcher) -> None:
        """Add a source (core or extension)."""
        self.watchers[watcher.name] = watcher

    def unregister_watcher(self, name: str) -> Watcher | None:
        """Remove a source (stopped by the caller when running)."""
        return self.watchers.pop(name, None)

    def subscribe(self, type_pattern: str, callback: Subscriber) -> None:
        """Receive events matching `presence.*`, `*` or an exact type (once per pair)."""
        if (type_pattern, callback) not in self._subscribers:
            self._subscribers.append((type_pattern, callback))

    def unsubscribe(self, callback: Subscriber) -> None:
        """Stop receiving."""
        self._subscribers = [(p, c) for p, c in self._subscribers if c is not callback]

    async def publish(self, event: PerceptionEvent) -> None:
        """Record, persist when severe enough, fan out."""
        self.published += 1
        self.history.appendleft(event)
        day = time.strftime("%Y-%m-%d")
        if self._today[0] != day:
            self._today = (day, {})
        counts = self._today[1]
        counts[event.type] = counts.get(event.type, 0) + 1
        if self.db is not None and event.severity >= self.persist_min:
            try:
                self.db.execute(
                    "INSERT INTO events (ts, type, severity, source, data) VALUES (?, ?, ?, ?, ?)",
                    (
                        event.ts,
                        event.type,
                        int(event.severity),
                        event.source,
                        json.dumps(event.data, ensure_ascii=False),
                    ),
                )
            except Exception as exc:
                Log.warning(f"event persist: {exc!r}")
        if event.severity >= Severity.NOTICE:
            Log.info(f"event {event.type} {event.data}")
        for pattern, callback in list(self._subscribers):
            if event.matches(pattern):
                try:
                    await callback(event)
                except Exception as exc:
                    Log.error(f"subscriber for {pattern}: {exc!r}")

    async def start(self) -> None:
        """Make the body watchers (the body is connected by now), then start every watcher."""
        body, config = self.body, self.config
        if body is not None and self.enabled and body.connected:
            poll_hz = float(getattr(config, "poll_hz", 4.0)) if config is not None else 4.0
            self.camera = CameraWatcher(
                body,
                poll_hz,
                float(getattr(config, "presence_enter_s", 1.0)) if config is not None else 1.0,
                float(getattr(config, "presence_leave_s", 60.0)) if config is not None else 60.0,
                contacts=self.contacts,
                mutual_gaze_s=float(getattr(config, "mutual_gaze_s", 2.5)),
                mutual_min_height=float(getattr(config, "mutual_gaze_min_height", 0.12)),
            )
            self.camera.face_listeners.extend(self._face_listeners)
            self.audio = AudioWatcher(body)
            self.register_watcher(self.camera)
            self.register_watcher(self.audio)
        for watcher in self.watchers.values():
            await watcher.start(self.publish)
        self.started = True
        Log.info(f"perception started: {sorted(self.watchers)}")

    async def stop(self) -> None:
        """Stop every watcher; the body watchers go (the next start makes fresh ones)."""
        for watcher in self.watchers.values():
            await watcher.stop()
        for body_watcher in (self.camera, self.audio):
            if body_watcher is not None:
                self.unregister_watcher(body_watcher.name)
        self.camera = self.audio = None
        self.started = False

    def check(self) -> list[dict[str, Any]]:
        """Readiness items: the camera watcher (our face detector) and the sound watcher."""
        if not self.enabled:
            return [{"id": "camera", "title": "perception", "level": "off", "detail": "off"}]
        camera = self.camera
        if camera is None:
            return [{"id": "camera", "title": "camera", "level": "warn", "detail": "no camera"}]
        running = camera.running
        return [
            {
                "id": "camera",
                "title": "face detection",
                "level": "ok" if running and not camera.errors else "warn",
                "detail": ("running" if running else "not running")
                + (f" · {camera.errors} error(s)" if camera.errors else ""),
            }
        ]

    def presence(self) -> Presence:
        """Current snapshot."""
        if self.camera is None:
            return Presence()
        base = self.camera.presence
        if self.audio is not None and self.audio.last_direction is not None:
            return Presence(
                base.someone_present,
                base.face_visible,
                base.frontal,
                base.since_ts,
                base.last_seen_ts,
                self.audio.last_direction,
            )
        return base

    def recent(
        self, limit: int = 50, min_severity: Severity = Severity.DEBUG
    ) -> list[dict[str, Any]]:
        """Newest events first (in-memory)."""
        out = []
        for event in self.history:
            if event.severity >= min_severity:
                out.append(
                    {
                        "ts": event.ts,
                        "type": event.type,
                        "severity": event.severity.name.lower(),
                        "source": event.source,
                        "data": event.data,
                    }
                )
            if len(out) >= limit:
                break
        return out

    def stored(self, limit: int = 100) -> list[dict[str, Any]]:
        """Persisted events, newest first."""
        if self.db is None:
            return []
        rows = self.db.query(
            "SELECT ts, type, severity, source, data FROM events ORDER BY ts DESC LIMIT ?", (limit,)
        )
        return [
            {
                "ts": r["ts"],
                "type": r["type"],
                "severity": Severity(r["severity"]).name.lower(),
                "source": r["source"],
                "data": json.loads(r["data"] or "{}"),
            }
            for r in rows
        ]

    def stored_between(
        self, start_ts: float, end_ts: float, limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Persisted events with `start_ts <= ts < end_ts`, oldest first (replay)."""
        if self.db is None:
            return []
        rows = self.db.query(
            "SELECT ts, type, severity, source, data FROM events"
            " WHERE ts >= ? AND ts < ? ORDER BY ts ASC LIMIT ?",
            (start_ts, end_ts, limit),
        )
        return [
            {
                "ts": r["ts"],
                "type": r["type"],
                "severity": Severity(r["severity"]).name.lower(),
                "source": r["source"],
                "data": json.loads(r["data"] or "{}"),
            }
            for r in rows
        ]

    def local_face(self) -> BodyFace:
        """The largest face our own detector sees right now (for the attention servo)."""
        return self.camera.local_face if self.camera is not None else BodyFace(False)

    def on_face(self, callback: Callable[[BodyFace], None]) -> None:
        """Receive every detection of our own detector (a `BodyFace`, undetected when none).

        Kept by the session, so a camera watcher made at a later start gets it too.
        """
        if callback not in self._face_listeners:
            self._face_listeners.append(callback)
        if self.camera is not None and callback not in self.camera.face_listeners:
            self.camera.face_listeners.append(callback)

    def local_face_vector(self, max_age_s: float = 2.0) -> Any:
        """The largest face's SFace vector when fresh (attribution of a speaker to a face)."""
        cam = self.camera
        if cam is None or cam.local_face_vector is None:
            return None
        if time.time() - cam.local_face_vector_ts > max_age_s:
            return None
        return cam.local_face_vector

    def faces(self) -> list[dict[str, Any]]:
        """Detected faces as normalised boxes with the identified name (dashboard overlay)."""
        return list(self.camera.faces) if self.camera is not None else []

    def live(self) -> dict[str, Any]:
        """Vital signs for the Live page (presence, faces, today's counts, watchers), in memory."""
        now = time.time()
        today = self._today[1] if self._today[0] == time.strftime("%Y-%m-%d") else {}
        return {
            "presence": self.presence().as_dict(),
            "faces": [
                {
                    "name": face.get("name"),
                    "contact": face.get("contact"),
                    "score": face.get("id_score"),
                }
                for face in self.faces()
            ],
            "today": {
                kind: today.get(kind, 0)
                for kind in ("presence.enter", "gaze.mutual", "greet.due", "person.ready")
            },
            "published": self.published,
            "watchers": [
                {
                    "name": name,
                    "polls": w.polls,
                    "errors": w.errors,
                    "last_error": w.last_error,
                    "ago_s": None if w.last_poll_ts is None else round(now - w.last_poll_ts, 1),
                }
                for name, w in self.watchers.items()
            ],
        }

    def activity(self, since: float = 0.0, limit: int = 30) -> list[dict[str, Any]]:
        """Bus events of severity info and up for the Live activity stream, newest first."""
        rows = []
        for event in self.history:
            if event.ts <= since:
                break
            if event.severity < Severity.INFO:
                continue
            data = json.dumps(event.data, ensure_ascii=False)
            rows.append(
                {
                    "ts": event.ts,
                    "module": "perception",
                    "text": f"{event.type}" + (f" {data[:80]}" if event.data else ""),
                    "level": "warn" if event.severity >= Severity.WARNING else "info",
                }
            )
        return rows[:limit]

    def snapshot(self) -> dict[str, Any]:
        """Dashboard state."""
        return {
            "started": self.started,
            "presence": self.presence().as_dict(),
            "faces": self.faces(),
            "watchers": {
                name: {"polls": w.polls, "errors": w.errors, "last_error": w.last_error}
                for name, w in self.watchers.items()
            },
            "published": self.published,
        }
