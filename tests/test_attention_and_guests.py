"""Attention hysteresis / face priority, guest voices told apart, clips sliced from the ring."""

from __future__ import annotations

import asyncio
import math
import time

import numpy as np

from sidekick.audio import AudioClip
from sidekick.body import BodyDoA, BodyFace, BodyNullBackend, BodySession
from sidekick.interaction import InteractionSession
from sidekick.interaction.attention import Attention
from sidekick.perception import CameraWatcher


def _yaw(backend):
    return math.atan2(backend.head[1, 0], backend.head[0, 0]) if backend.head is not None else 0.0


def _wait(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_attention_turns_only_on_a_real_change_and_never_over_a_tracked_face():
    backend = BodyNullBackend()
    body = BodySession(backend, poll_hz=20.0)
    body.connect()
    try:
        attention = Attention(body)
        attention.daemon_tracking = True  # legacy mode: the daemon's tracker owns a seen face
        attention.set_engaged(True)
        attention.on_speech(BodyDoA(math.pi / 2 - 0.6, True), force=True)  # 0.6 rad left
        assert _wait(lambda: abs(_yaw(backend) - 0.6) < 0.08)
        attention._last_turn = 0.0
        attention.on_speech(BodyDoA(math.pi / 2 - 0.7, True))  # 6° away: ignored
        time.sleep(0.4)
        assert abs(_yaw(backend) - 0.6) < 0.08
        attention._last_turn = 0.0
        attention.on_speech(BodyDoA(math.pi / 2 + 0.5, True))  # 63° away, heard once: waits
        time.sleep(0.4)
        assert abs(_yaw(backend) - 0.6) < 0.08
        attention._last_turn = 0.0
        attention.on_speech(BodyDoA(math.pi / 2 + 0.5, True, agreement=0.4))  # readings disagree
        time.sleep(0.4)
        assert abs(_yaw(backend) - 0.6) < 0.08
        attention._last_turn = 0.0
        attention.on_speech(BodyDoA(math.pi / 2 + 0.5, True))  # the same direction again: turns
        assert _wait(lambda: abs(_yaw(backend) + 0.5) < 0.08)
        # a tracked face owns the head: no DoA turn, no servo
        backend.face = BodyFace(True, 0.0, 0.0)
        assert _wait(lambda: body.face().detected)  # the monitor thread mirrors it
        attention._last_turn = 0.0
        attention.on_speech(BodyDoA(math.pi / 2 - 0.6, True))
        time.sleep(0.4)
        assert abs(_yaw(backend) + 0.5) < 0.08
        backend.face = BodyFace(False)
        assert _wait(lambda: not body.face().detected)
        # the daemon is blind: our own detector sees a face on the right → the servo yaws right
        attention.set_engaged(False)
        assert _wait(lambda: abs(_yaw(backend)) < 0.08)
        attention._last_servo = 0.0
        assert attention.on_face(BodyFace(True, 0.5, 0.0))
        assert _wait(lambda: _yaw(backend) < -0.2)
    finally:
        body.close()


def test_face_servo_pursues_from_the_current_pose_with_a_dead_band():
    backend = BodyNullBackend()
    body = BodySession(backend, poll_hz=20.0)
    body.connect()
    try:
        attention = Attention(body)
        attention.start()
        assert attention.snapshot()["tracker"] == "own" and body.camera_fov() is None
        # a face half-way to the right edge: one step is gain × atan(0.5 · tan 45°) ≈ 0.32 rad
        step = 0.7 * math.atan(0.5)
        assert attention.on_face(BodyFace(True, 0.5, 0.0), now=1.0)
        assert abs(attention._yaw + step) < 1e-6
        # too soon: no second command; the same offset later steps again from where the head is
        assert not attention.on_face(BodyFace(True, 0.5, 0.0), now=1.02)
        assert _wait(lambda: abs(_yaw(backend) + step) < 0.03)
        assert attention.on_face(BodyFace(True, 0.5, 0.0), now=2.0)
        assert abs(attention._yaw + 2 * step) < 0.05  # base was the eased pose ≈ −step
        # the daemon's face does not stop the servo in own mode
        backend.face = BodyFace(True, 0.0, 0.0)
        assert _wait(lambda: body.face().detected)
        assert attention.on_face(BodyFace(True, -0.5, 0.0), now=3.0)
        assert attention._yaw > -2 * step  # stepped back toward the left
        # inside the dead band: no command, mode stays "face"
        yaw_before = attention._yaw
        assert not attention.on_face(BodyFace(True, 0.02, -0.01), now=4.0)
        assert attention._yaw == yaw_before and attention.mode == "face"
        # pitch: a face low in the image pitches the head down (positive)
        attention._last_servo = 0.0
        assert attention.on_face(BodyFace(True, 0.0, 0.6), now=5.0)
        assert attention._pitch > 0.1
        # a stale detection is ignored
        assert not attention.on_face(BodyFace(True, 0.5, 0.0, None, time.time() - 2.0), now=6.0)
        # lost for two seconds in idle: back to neutral
        attention.tick(True, 10.0)
        attention.tick(False, 10.5)
        attention.tick(False, 12.6)
        assert attention._yaw == 0.0 and attention._pitch == 0.0
        assert _wait(lambda: abs(_yaw(backend)) < 0.05, 4.0)
        assert attention.servo_steps == 4
    finally:
        body.close()


def test_body_frame_pump_shares_frames_and_counts_fps():
    backend = BodyNullBackend()
    body = BodySession(backend, poll_hz=20.0)
    body.connect()
    try:
        assert body.frame() is None
        frame = np.full((36, 64, 3), 20, dtype=np.uint8)
        backend.set_frame(frame)
        assert body.frame(wait_s=1.0) is not None
        # every reader gets the same latest frame, as often as it likes
        assert body.frame() is body.frame()
        assert _wait(lambda: body.camera_fps() > 20, 2.0)
        assert body.telemetry().camera_fps > 20
        backend.set_frame(None)
        assert _wait(lambda: body.frame(max_age_s=0.2) is None, 2.0)
    finally:
        body.close()


class _FakeContacts:
    """Voice embeddings by the clip's dominant frequency, so two speakers are two vectors."""

    ready = True
    voice_threshold = 0.5

    def __init__(self) -> None:
        self.guests = 0

    def embed_voice(self, clip):
        spectrum = np.abs(np.fft.rfft(clip.samples[:4000]))
        vector = np.zeros(8, dtype=np.float32)
        vector[(int(np.argmax(spectrum)) // 100) % 8] = 1.0  # 440 Hz → bin 1, 2200 Hz → bin 5
        return vector

    @staticmethod
    def voice_similarity(a, b):
        return float(np.dot(a, b))

    def new_guest(self):
        self.guests += 1
        return f"guest:{self.guests}"

    def display_name(self, speaker):
        return {"owner": "爸爸 (owner)"}.get(speaker, speaker)


def _tone(freq, seconds=1.0):
    t = np.arange(int(16000 * seconds)) / 16000.0
    return AudioClip((0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32), 16000)


def test_guest_voices_keep_their_ids_within_a_session():
    session = InteractionSession()
    session.contacts = _FakeContacts()
    a = asyncio.run(session._guest_for(_tone(440)))
    b = asyncio.run(session._guest_for(_tone(2200)))
    again = asyncio.run(session._guest_for(_tone(445)))
    assert a == "guest:1" and b == "guest:2" and again == "guest:1"
    session._session_ended = lambda reason: session._guest_voices.clear()  # type: ignore[method-assign]
    session._guest_voices.clear()
    assert asyncio.run(session._guest_for(_tone(2200))) == "guest:3"
    assert session._speaker_label("owner") == "爸爸 (owner)"
    assert session._speaker_label("guest:2") == "guest:2"


class _FakeDetector:
    def __init__(self, faces):
        self.faces = faces

    def detect(self, frame):
        return list(self.faces)


class _FakeFace:
    def __init__(self, x, y, w, h, score=0.9):
        self.x, self.y, self.w, self.h, self.score = x, y, w, h, score


class _FaceContacts:
    ready = True

    def __init__(self, faces):
        self.face = _FakeDetector(faces)

    def identify_face(self, frame):
        class _Ident:
            contact_id = "owner"
            score = 0.7

        return _Ident(), None

    def display_name(self, speaker):
        return "爸爸 (owner)"


def test_camera_watcher_uses_our_detector_when_the_daemon_is_blind():
    backend = BodyNullBackend()
    body = BodySession(backend, poll_hz=20.0)
    body.connect()
    try:
        backend.set_frame(np.full((360, 640, 3), 20, dtype=np.uint8))  # a dark room
        assert body.frame(wait_s=1.0) is not None  # the frame pump has picked it up
        contacts = _FaceContacts([_FakeFace(400, 90, 120, 160)])
        cam = CameraWatcher(body, contacts=contacts)
        rows = cam.detect()
        assert rows and rows[0]["name"] == "爸爸 (owner)" and 0.6 < rows[0]["x"] < 0.7
        assert cam.local_face.detected and cam.local_face.x > 0.3  # right of centre
        events = asyncio.run(cam.poll())
        assert cam.presence.face_visible and any(e.type == "face.seen" for e in events)
        contacts.face.faces = []
        cam.detect()
        assert cam.faces == [] and not cam.local_face.detected
        # detections reach the registered listeners (the face servo) from the poll
        seen = []
        cam.face_listeners.append(seen.append)
        contacts.face.faces = [_FakeFace(100, 90, 120, 160)]
        asyncio.run(cam.poll())
        assert seen and seen[-1].detected and seen[-1].x < -0.3
    finally:
        body.close()


def test_idle_scanning_glances_and_return_to_neutral():
    backend = BodyNullBackend()
    body = BodySession(backend, poll_hz=20.0)
    body.connect()
    try:
        attention = Attention(body)
        attention.rng.seed(7)
        attention.scan_min_s = attention.scan_max_s = 1.0
        attention.scan_hold_s = 0.3
        attention.start()
        now = 100.0
        attention._schedule_scan(now)  # the test drives its own clock
        attention.tick(False, now)  # not due yet
        assert attention.mode == "idle" and attention.glances == 0
        attention.tick(False, now + 1.1)
        assert attention.mode == "scan" and attention.glances == 1
        assert 0.35 <= abs(attention._yaw) <= 0.71
        side = math.copysign(1.0, attention._yaw)
        assert _wait(lambda: abs(_yaw(backend) - attention._yaw) < 0.1)
        attention.tick(False, now + 1.6)  # still holding
        assert attention.mode == "scan"
        attention.tick(False, now + 3.0)  # hold over → neutral
        assert attention.mode == "idle" and attention._yaw == 0.0
        assert _wait(lambda: abs(_yaw(backend)) < 0.1)
        attention.tick(False, now + 4.2)  # next glance alternates sides
        assert attention.glances == 2 and math.copysign(1.0, attention._yaw) == -side
        snap = attention.snapshot()
        assert snap["mode"] == "scan" and snap["glances"] == 2
        # a face pauses scanning, engagement stops it entirely
        attention.tick(True, now + 4.5)
        assert attention.mode == "face" and attention._glance is None
        attention.tick(False, now + 4.6)
        assert attention.mode == "idle" and attention.glances == 2  # the clock restarted
        attention.set_engaged(True)
        attention.tick(False, now + 200.0)
        assert attention.mode == "engaged" and attention.glances == 2
        attention.set_engaged(False)
        attention._schedule_scan(now + 300.0)
        attention.scan_enabled = False
        attention.tick(False, now + 400.0)
        assert attention.glances == 2 and attention.snapshot()["next_scan_s"] is None
    finally:
        body.close()


def test_sound_glance_needs_a_clear_sound_and_is_rate_limited():
    backend = BodyNullBackend()
    body = BodySession(backend, poll_hz=20.0)
    body.connect()
    try:
        attention = Attention(body)
        attention.start()
        now = 50.0
        left = BodyDoA(math.pi / 2 - 0.6, True)
        assert not attention.on_sound(left, -45.0, 1.0, now)  # too quiet
        assert not attention.on_sound(left, -20.0, 0.3, now)  # too short
        assert not attention.on_sound(None, -20.0, 1.0, now)  # no direction
        assert attention.on_sound(left, -20.0, 1.0, now)
        assert attention.mode == "sound" and abs(attention._yaw - 0.6) < 1e-6
        assert _wait(lambda: abs(_yaw(backend) - 0.6) < 0.1)
        right = BodyDoA(math.pi / 2 + 0.6, True)
        assert not attention.on_sound(right, -20.0, 1.0, now + 2.0)  # within the 8 s gap
        attention.tick(False, now + 5.0)  # glance over → neutral
        assert attention.mode == "idle" and _wait(lambda: abs(_yaw(backend)) < 0.1)
        assert attention.on_sound(right, -20.0, 1.0, now + 9.0)
        assert attention.mode == "sound" and attention._yaw < 0
        attention.set_engaged(True)
        assert not attention.on_sound(left, -20.0, 1.0, now + 30.0)  # engaged: no glances
        attention.set_engaged(False)
        attention.sound_enabled = False
        assert not attention.on_sound(left, -20.0, 1.0, now + 60.0)
    finally:
        body.close()
