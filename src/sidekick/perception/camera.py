"""sidekick.perception.camera — presence and gaze from the body's face tracker and our own detector

Overview
    The daemon's face tracker finds and follows faces in good light; this watcher turns its
    `BodyFace` readings into events: `face.seen` when a face appears, `gaze.frontal` when it is
    centred, `presence.enter` once a face has been visible for `enter_s`, and `presence.leave`
    after `leave_s` without one. It keeps the `Presence` snapshot. When a `contact` session is
    attached it also runs **our** detector (YuNet on a gamma-lifted 640 px copy of the frame,
    every poll — 10 Hz by default, the face servo's rate) so faces are found in a dark room
    where the daemon sees nothing, identifies the largest face once a second, publishes the
    boxes with names for the dashboard (`faces`), offers the largest one as `local_face` for
    presence when the daemon reports none, and hands every detection to the registered
    `face_listeners` (the attention servo in `interaction`) straight from the poll. It also detects **mutual gaze**: the largest face is centred, turned
    toward the camera (YuNet's five landmarks: the nose sits between the eyes) and large enough
    for `mutual_gaze_s` → one `gaze.mutual` event per gaze episode (re-armed after the person
    looks away for a second), carrying the identified contact when there is one. That event is
    the attention layer's hand-off to the initiative layer (block #38).
Design
    The presence state machine is pure over timestamps so it is unit-tested with injected
    faces. Detection runs in a worker thread (~10 ms at 640 px); the TV zone from the onboarding
    wizard is applied by the detector itself. Facing is a landmark ratio, not a pose model: the
    nose offset from the eye midpoint over the inter-eye distance is below `FACING_RATIO` when
    the head is turned toward the camera by less than ~20°; without landmarks (daemon tracker
    only) a centred face counts as facing. Identified contacts are `touch()`ed so their
    `last_seen` reflects faces as well as voices.
Depends on
    sidekick.log, sidekick.body, sidekick.contact (duck-typed, optional), numpy, opencv (lazy).

See Also
--------
    AGENTS.md "Perception", "Interaction" (gaze trigger, session extension).

"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from sidekick.body import BodyFace, BodySession
from sidekick.contact import brighten_frame
from sidekick.log import Log

from .schemas import PerceptionEvent, Presence, Severity
from .watcher import Watcher

FACING_RATIO = 0.3  # |nose - eye midpoint| / inter-eye distance: below this the face is toward us
MUTUAL_CENTRE = 0.3  # |x| of the image (−1..1) within which a face counts as centred
MUTUAL_REARM_S = 1.0  # looking away this long ends a gaze episode


def facing_camera(row: Any) -> bool | None:
    """From a YuNet row (x, y, w, h, 5 landmarks, score): is the head turned toward the camera?"""
    try:
        values = [float(v) for v in row[:14]]
    except (TypeError, ValueError, IndexError):
        return None
    if len(values) < 14:
        return None
    right_eye_x, left_eye_x, nose_x = values[4], values[6], values[8]
    eye_distance = abs(left_eye_x - right_eye_x)
    if eye_distance < 1.0:
        return None
    return abs(nose_x - (right_eye_x + left_eye_x) / 2.0) / eye_distance < FACING_RATIO


class CameraWatcher(Watcher):
    """Presence from face tracking."""

    name = "camera"

    def __init__(
        self,
        body: BodySession,
        poll_hz: float = 4.0,
        enter_s: float = 1.0,
        leave_s: float = 60.0,
        contacts: Any = None,
        detect_width: int = 640,
        mutual_gaze_s: float = 2.5,
        mutual_min_height: float = 0.12,
    ) -> None:
        super().__init__(1.0 / poll_hz)
        self.body = body
        self.enter_s = enter_s
        self.leave_s = leave_s
        self.contacts = contacts
        self.detect_width = detect_width
        self.mutual_gaze_s = mutual_gaze_s
        self.mutual_min_height = mutual_min_height
        self.local_facing: bool | None = None  # largest face turned toward the camera?
        self.local_height = 0.0  # of the frame height
        self.face_listeners: list[Callable[[BodyFace], None]] = []
        self._mutual_since: float | None = None
        self._mutual_last: float = 0.0
        self._mutual_fired = False
        self.mutual_gazes = 0
        self.presence = Presence()
        self.faces: list[dict[str, Any]] = []
        self.faces_ts = 0.0
        self.local_face = BodyFace(False)
        self.local_face_vector: Any = None  # SFace vector of the largest face (identify tick)
        self.local_face_vector_ts = 0.0
        self.detections = 0
        self._visible_since: float | None = None
        self._last_seen: float | None = None
        self._was_frontal = False
        self._last_identify = 0.0
        self._identified: tuple[str | None, float] = (None, 0.0)

    def observe(
        self,
        face: BodyFace,
        now: float | None = None,
        facing: bool | None = None,
        height: float | None = None,
        contact: str | None = None,
    ) -> list[PerceptionEvent]:
        """Feed one reading; returns the events it causes.

        `facing` (head toward the camera), `height` (of the frame) and `contact` come from our
        detector when it runs; with only the daemon's tracker a centred face counts as facing.
        """
        now = time.time() if now is None else now
        events: list[PerceptionEvent] = []
        present = self.presence.someone_present
        events.extend(self._mutual(face, now, facing, height, contact))
        if face.detected:
            if self._visible_since is None:
                self._visible_since = now
                events.append(
                    PerceptionEvent("face.seen", Severity.DEBUG, {"x": face.x, "y": face.y}, now)
                )
            self._last_seen = now
            frontal = face.frontal
            if frontal and not self._was_frontal:
                events.append(PerceptionEvent("gaze.frontal", Severity.DEBUG, {"x": face.x}, now))
            self._was_frontal = frontal
            if not present and now - self._visible_since >= self.enter_s:
                present = True
                events.append(PerceptionEvent("presence.enter", Severity.NOTICE, {}, now))
            self.presence = Presence(
                present,
                True,
                frontal,
                self.presence.since_ts or (now if present else None),
                now,
                self.presence.speech_direction,
            )
        else:
            self._visible_since = None
            self._was_frontal = False
            if present and self._last_seen is not None and now - self._last_seen >= self.leave_s:
                present = False
                events.append(
                    PerceptionEvent(
                        "presence.leave",
                        Severity.NOTICE,
                        {"after_s": round(now - self._last_seen)},
                        now,
                    )
                )
            self.presence = Presence(
                present,
                False,
                False,
                self.presence.since_ts if present else None,
                self._last_seen,
                self.presence.speech_direction,
            )
        return events

    def _mutual(
        self,
        face: BodyFace,
        now: float,
        facing: bool | None,
        height: float | None,
        contact: str | None,
    ) -> list[PerceptionEvent]:
        """One `gaze.mutual` per episode of a centred face turned toward the camera."""
        centred = face.detected and face.x is not None and abs(face.x) < MUTUAL_CENTRE
        toward = centred and facing is not False
        big = height is None or height >= self.mutual_min_height
        if toward and big:
            self._mutual_last = now
            if self._mutual_since is None:
                self._mutual_since = now
            elif not self._mutual_fired and now - self._mutual_since >= self.mutual_gaze_s:
                self._mutual_fired = True
                self.mutual_gazes += 1
                data: dict[str, Any] = {
                    "contact": contact,
                    "duration_s": round(now - self._mutual_since, 1),
                    "height": None if height is None else round(height, 3),
                }
                if contact and self.contacts is not None:
                    data["name"] = self.contacts.display_name(contact)
                return [PerceptionEvent("gaze.mutual", Severity.INFO, data, now)]
        elif self._mutual_since is not None and now - self._mutual_last >= MUTUAL_REARM_S:
            self._mutual_since, self._mutual_fired = None, False
        return []

    async def poll(self) -> list[PerceptionEvent]:
        """Read the daemon's tracker, run our detector, fall back to ours for presence."""
        if not self.body.awake:
            self.faces, self.local_face = [], BodyFace(False)
            return self.observe(BodyFace(False))
        face = self.body.face()
        ours = False
        if self.contacts is not None and getattr(self.contacts, "ready", False):
            await asyncio.to_thread(self.detect)
            ours = True
            for listener in list(self.face_listeners):
                try:
                    listener(self.local_face)
                except Exception as exc:
                    Log.debug(f"face listener: {exc!r}")
        if not face.detected and self.local_face.detected:
            face = self.local_face
        if ours and self.local_face.detected:
            return self.observe(
                face,
                facing=self.local_facing,
                height=self.local_height,
                contact=self._identified[0],
            )
        return self.observe(face)

    def detect(self) -> list[dict[str, Any]]:
        """Run YuNet on the current frame (worker thread); updates `faces` and `local_face`."""
        frame = self.body.frame()
        now = time.time()
        if frame is None:
            if now - self.faces_ts > 1.0:
                self.faces, self.local_face = [], BodyFace(False)
            return self.faces
        height, width = frame.shape[:2]
        if width > self.detect_width:
            import cv2

            scale = self.detect_width / width
            frame = np.asarray(
                cv2.resize(
                    frame,
                    (self.detect_width, max(1, round(height * scale))),
                    interpolation=cv2.INTER_AREA,
                ),
                dtype=np.uint8,
            )
            height, width = frame.shape[:2]
        frame = brighten_frame(frame)
        try:
            found = self.contacts.face.detect(frame)
        except Exception as exc:  # models missing, odd frame
            Log.debug(f"local face detect: {exc!r}")
            found = []
        self.detections += 1
        rows: list[dict[str, Any]] = []
        for face in found[:4]:
            rows.append(
                {
                    "x": round(face.x / width, 4),
                    "y": round(face.y / height, 4),
                    "w": round(face.w / width, 4),
                    "h": round(face.h / height, 4),
                    "score": round(float(face.score), 2),
                    "contact": None,
                    "name": None,
                    "facing": facing_camera(getattr(face, "row", None)),
                }
            )
        if rows and now - self._last_identify >= 1.0:
            self._last_identify = now
            try:
                identification, _ = self.contacts.identify_face(frame)
                self._identified = (
                    identification.contact_id,
                    round(float(identification.score), 2),
                )
                vector = self.contacts.face.embed(frame, found[0]) if found else None
                self.local_face_vector, self.local_face_vector_ts = vector, now
            except Exception as exc:
                Log.debug(f"identify face: {exc!r}")
        if rows and self._identified[0]:
            rows[0]["contact"] = self._identified[0]
            rows[0]["name"] = self.contacts.display_name(self._identified[0])
            rows[0]["id_score"] = self._identified[1]
            touch = getattr(self.contacts, "touch", None)
            if callable(touch):
                touch(self._identified[0], now)
        elif not rows:
            self._identified = (None, 0.0)
            self.local_face_vector = None
        self.faces, self.faces_ts = rows, now
        if rows:
            r = rows[0]
            self.local_face = BodyFace(
                True,
                (r["x"] + r["w"] / 2.0) * 2.0 - 1.0,
                (r["y"] + r["h"] / 2.0) * 2.0 - 1.0,
                None,
                now,
            )
            self.local_facing, self.local_height = r["facing"], float(r["h"])
        else:
            self.local_face = BodyFace(False)
            self.local_facing, self.local_height = None, 0.0
        return rows
