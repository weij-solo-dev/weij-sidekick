"""TouchDetector hysteresis and body schema helpers."""

from __future__ import annotations

import math

from sidekick.body import BodyState, TouchDetector, doa_to_yaw, yaw_distance
from sidekick.body.reachy import face_from_payload, status_from_payload


def test_touch_detector_hysteresis_and_debounce():
    det = TouchDetector(press_rad=0.3, release_rad=0.1, debounce_s=0.5, settle_s=0.0)
    det.resume(now=0.0)
    cmd = (-0.17, 0.17)
    assert det.update(cmd, (-0.17, 0.17), now=0.1) is None
    event = det.update(cmd, (-0.17, 0.6), now=0.2)
    assert event is not None and event.side == "left" and abs(event.delta_rad - 0.43) < 1e-6
    assert det.update(cmd, (-0.17, 0.6), now=0.3) is None  # still held
    assert det.update(cmd, (-0.17, 0.4), now=0.4) is None  # above release, no new press
    assert det.update(cmd, (-0.17, 0.2), now=0.5) is None  # released
    assert det.update(cmd, (-0.17, 0.6), now=0.6) is None  # within debounce
    assert det.update(cmd, (-0.17, 0.2), now=0.65) is None
    assert det.update(cmd, (-0.17, 0.6), now=0.8) is not None


def test_touch_detector_pause_and_settle():
    det = TouchDetector(settle_s=0.4)
    det.pause()
    assert det.update((0, 0), (0, 1.0), now=1.0) is None
    det.resume(now=1.0)
    assert det.update((0, 0), (0, 0.0), now=1.2) is None  # settling
    assert det.update((0, 0), (0, 0.0), now=1.5) is None  # arrived: armed
    assert det.update((0, 0), (0, 1.0), now=1.6) is not None  # pushed away


def test_touch_detector_ignores_an_antenna_that_never_arrives():
    """A blocked antenna (head looking up, 2026-10-30) or one still held never fires again."""
    det = TouchDetector(settle_s=0.0)
    for second in range(5):  # every acknowledgement re-armed the detector, once a second
        det.pause(now=float(second))
        det.resume(now=float(second))
        for tick in range(10):
            assert det.update((-0.75, 0.75), (-0.75, 0.18), now=second + tick / 10) is None
    # the right antenna, which did arrive, still reports a push
    det.update((-0.75, 0.75), (-0.75, 0.18), now=6.0)
    assert det.update((-0.75, 0.75), (-0.2, 0.18), now=6.1) is not None


def test_doa_between_is_the_median_of_the_speech_readings():
    """Block #80: the reading at the end of a sentence is the room; the median is the speaker."""
    from sidekick.body import BodyDoA, BodySession
    from sidekick.body.null import BodyNullBackend

    body = BodySession(BodyNullBackend())
    front, left = math.pi / 2, math.pi / 2 - 1.0  # straight ahead, and 57° off
    for ts, angle, speech in [
        (1.0, front, True),
        (1.2, front + 0.05, True),
        (1.4, left, True),  # one stray reading inside the sentence
        (1.6, front - 0.03, True),
        (1.8, left, False),  # the silence after it, where the old single reading came from
        (2.0, left, False),
    ]:
        body._doa_history.append((ts, BodyDoA(angle, speech)))
    doa = body.doa_between(0.9, 2.1)
    assert doa is not None and abs(doa.angle - front) < 0.06 and doa.speech
    assert doa.agreement == 0.75  # three of the four speech readings agree
    unflagged = body.doa_between(1.75, 2.1)
    assert unflagged is not None and unflagged.angle == left and not unflagged.speech
    assert body.doa_between(5.0, 6.0) is None


def test_doa_to_yaw_convention():
    assert abs(doa_to_yaw(math.pi / 2)) < 1e-9  # front
    assert doa_to_yaw(0.0) > 0  # left is positive yaw
    assert doa_to_yaw(math.pi) < 0
    assert abs(yaw_distance(3.0, -3.0) - (2 * math.pi - 6.0)) < 1e-9


def test_status_mapping_from_daemon_payload():
    running = {
        "state": "running",
        "robot_name": "reachy_mini",
        "version": "1.12.0",
        "no_media": False,
        "backend_status": {"motor_control_mode": "enabled"},
        "face_target": {"detected": True, "x": 0.1, "y": -0.2},
    }
    status = status_from_payload(running)
    assert status.state == BodyState.AWAKE and status.awake and status.connected
    assert status.version == "1.12.0" and status.media
    asleep = status_from_payload({**running, "backend_status": {"motor_control_mode": "disabled"}})
    assert asleep.state == BodyState.ASLEEP and not asleep.awake
    assert status_from_payload({"state": "starting"}).state == BodyState.ASLEEP
    assert status_from_payload({"state": "stopped"}).state == BodyState.DISCONNECTED
    assert status_from_payload({"state": "error", "error": "boom"}).state == BodyState.ERROR
    assert status_from_payload(None).state == BodyState.DISCONNECTED
    face = face_from_payload(running["face_target"])
    assert face.detected and face.frontal
    assert not face_from_payload(None).detected
