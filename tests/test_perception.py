"""Perception: presence from face readings, speech events, bus fan-out and persistence, event jobs."""

from __future__ import annotations

import asyncio
import math

from sidekick.body import BodyDoA, BodyFace, BodyNullBackend, BodySession
from sidekick.perception import (
    AudioWatcher,
    CameraWatcher,
    PerceptionEvent,
    PerceptionSession,
    Severity,
)
from sidekick.perception.camera import facing_camera


def test_camera_presence_state_machine():
    body = BodySession(BodyNullBackend())
    cam = CameraWatcher(body, enter_s=1.0, leave_s=10.0)
    assert [e.type for e in cam.observe(BodyFace(True, 0.1, 0.0), now=0.0)] == [
        "face.seen",
        "gaze.frontal",
    ]
    assert cam.observe(BodyFace(True, 0.1, 0.0), now=0.5) == []
    assert [e.type for e in cam.observe(BodyFace(True, 0.6, 0.0), now=1.2)] == ["presence.enter"]
    assert cam.presence.someone_present and cam.presence.face_visible and not cam.presence.frontal
    assert cam.observe(BodyFace(False), now=5.0) == []
    assert cam.presence.someone_present and not cam.presence.face_visible
    assert [e.type for e in cam.observe(BodyFace(False), now=12.0)] == ["presence.leave"]
    assert not cam.presence.someone_present
    # a brief glimpse does not count as presence
    cam.observe(BodyFace(True, 0.0, 0.0), now=20.0)
    assert cam.observe(BodyFace(False), now=20.4) == [] and not cam.presence.someone_present


def test_audio_speech_events():
    body = BodySession(BodyNullBackend())
    aw = AudioWatcher(body)
    assert aw.observe(None) == []
    events = aw.observe(BodyDoA(math.pi / 2, True), now=0.0)
    assert [e.type for e in events] == ["audio.speech"] and abs(events[0].data["yaw"]) < 1e-9
    assert aw.observe(BodyDoA(math.pi / 2, True), now=0.2) == []  # still speaking
    aw.observe(BodyDoA(1.0, False), now=0.5)
    assert aw.observe(BodyDoA(1.0, True), now=0.8) == []  # rate limited
    aw.observe(BodyDoA(1.0, False), now=1.2)
    assert [e.type for e in aw.observe(BodyDoA(1.0, True), now=1.5)] == ["audio.speech"]


async def test_bus_subscribe_persist_and_snapshot(tmp_path):
    backend = BodyNullBackend()
    body = BodySession(backend, poll_hz=20.0)
    body.connect()
    session = PerceptionSession()
    session.setup(body, tmp_path / "events_v1.db")
    seen = []

    async def on_presence(event):
        seen.append(event.type)

    async def boom(event):
        raise RuntimeError("subscriber failure must not break the bus")

    session.subscribe("presence.*", on_presence)
    session.subscribe("*", boom)
    await session.publish(PerceptionEvent("presence.enter", Severity.NOTICE))
    await session.publish(PerceptionEvent("face.seen", Severity.DEBUG))
    assert seen == ["presence.enter"]
    assert [e["type"] for e in session.stored()] == ["presence.enter"]  # debug not persisted
    assert (
        len(session.recent()) == 2
        and session.recent(min_severity=Severity.NOTICE)[0]["type"] == "presence.enter"
    )
    # live watcher: inject a face and let the camera watcher tick
    backend.face = BodyFace(True, 0.0, 0.0)
    await session.start()
    try:
        for _ in range(40):
            if session.presence().someone_present:
                break
            await asyncio.sleep(0.1)
        assert (
            session.presence().someone_present
            and session.snapshot()["watchers"]["camera"]["polls"] > 0
        )
    finally:
        await session.stop()
        body.close()
    assert PerceptionEvent("feed.update", data={"source": "hn"}).matches("feed.*", {"source": "hn"})
    assert not PerceptionEvent("feed.update", data={"source": "rss"}).matches(
        "feed.update", {"source": "hn"}
    )


def test_facing_camera_from_yunet_landmarks():
    # x, y, w, h, right eye, left eye, nose, mouth right, mouth left, score
    frontal = [100, 100, 80, 100, 120, 140, 160, 140, 140, 165, 125, 185, 155, 185, 0.9]
    turned = [100, 100, 80, 100, 120, 140, 160, 140, 158, 165, 125, 185, 155, 185, 0.9]
    assert facing_camera(frontal) is True
    assert facing_camera(turned) is False
    assert facing_camera(None) is None and facing_camera([1, 2, 3]) is None


def test_mutual_gaze_fires_once_per_episode_and_rearms():
    body = BodySession(BodyNullBackend())
    cam = CameraWatcher(body, enter_s=1.0, leave_s=10.0, mutual_gaze_s=2.0, mutual_min_height=0.1)
    face = BodyFace(True, 0.05, 0.0)
    kw = {"facing": True, "height": 0.3, "contact": "owner"}

    def mutual(events):
        return [e for e in events if e.type == "gaze.mutual"]

    assert mutual(cam.observe(face, now=0.0, **kw)) == []
    assert mutual(cam.observe(face, now=1.5, **kw)) == []
    events = mutual(cam.observe(face, now=2.1, **kw))
    assert len(events) == 1
    assert events[0].data["contact"] == "owner" and events[0].data["duration_s"] == 2.1
    assert mutual(cam.observe(face, now=5.0, **kw)) == []  # same episode: once
    # looking away briefly does not end the episode; a second does
    cam.observe(face, now=5.5, facing=False, height=0.3, contact="owner")
    assert mutual(cam.observe(face, now=6.0, **kw)) == []
    cam.observe(BodyFace(False), now=7.0)
    cam.observe(BodyFace(False), now=8.5)
    cam.observe(face, now=9.0, **kw)
    assert len(mutual(cam.observe(face, now=11.1, **kw))) == 1
    # a small (far) face or a face turned away never counts
    far = CameraWatcher(body, mutual_gaze_s=1.0, mutual_min_height=0.2)
    for t in (0.0, 0.6, 1.2, 2.0):
        assert "gaze.mutual" not in [
            e.type for e in far.observe(face, now=t, facing=True, height=0.1)
        ]
    away = CameraWatcher(body, mutual_gaze_s=1.0)
    for t in (0.0, 0.6, 1.2, 2.0):
        assert "gaze.mutual" not in [e.type for e in away.observe(face, now=t, facing=False)]
    # the daemon's tracker alone (no landmarks): a centred face counts as facing
    plain = CameraWatcher(body, mutual_gaze_s=1.0)
    plain.observe(face, now=0.0)
    assert len(mutual(plain.observe(face, now=1.1))) == 1
