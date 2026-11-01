"""BodySession over the null backend: motion owner, touch, paced playback, ducking, flush."""

from __future__ import annotations

import math
import time

import numpy as np

from sidekick.audio import AudioClip
from sidekick.body import (
    INIT_ANTENNAS,
    LISTENING_ANTENNAS,
    BodyNullBackend,
    BodySession,
    BodyState,
    Gesture,
    head_pose,
)


def wait_for(predicate, timeout=3.0, step=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def make_session():
    backend = BodyNullBackend()
    session = BodySession(backend, poll_hz=20.0)
    status = session.connect()
    assert status.state == BodyState.AWAKE
    return backend, session


def test_motion_owner_sends_targets_and_looks():
    backend, session = make_session()
    try:
        assert wait_for(lambda: backend.targets_sent > 5)
        session.look(yaw=0.5, pitch=0.0, duration_s=0.1)
        assert wait_for(
            lambda: (
                backend.head is not None
                and abs(math.atan2(backend.head[1, 0], backend.head[0, 0]) - 0.5) < 0.08
            ),
            2.0,
        )
        session.gesture(Gesture.NOD)
        time.sleep(0.3)
        assert backend.head is not None
        session.listening()
        assert wait_for(lambda: abs(backend.antennas[1] - LISTENING_ANTENNAS[1]) < 0.05, 2.0)
        session.relax()
        assert wait_for(lambda: abs(backend.antennas[1] - INIT_ANTENNAS[1]) < 0.05, 2.0)
    finally:
        session.close()


def test_touch_event_from_pushed_antenna():
    backend, session = make_session()
    events = []
    session.on_touch(events.append)
    try:
        time.sleep(0.6)  # detector settle time after start
        backend.push_antenna("left", 0.6)
        assert wait_for(lambda: len(events) == 1, 2.0)
        assert events[0].side == "left" and events[0].source == "antenna"
        time.sleep(0.3)
        assert len(events) == 1  # held press fires once
        backend.push_antenna("left", 0.0)
        time.sleep(0.2)
        backend.push_antenna("left", 0.6)
        assert wait_for(lambda: len(events) == 2, 2.0)
    finally:
        session.close()


def test_player_paces_ducks_and_flushes():
    backend, session = make_session()
    try:
        clip = AudioClip(np.full(16000, 0.5, dtype=np.float32))  # 1 s
        started = time.monotonic()
        session.speak(clip)
        assert wait_for(lambda: backend.spoken_seconds() >= 0.2, 1.0)
        # pacing: after ~0.25 s lead we must not have pushed the whole second yet
        assert backend.spoken_seconds() < 0.6
        session.duck(-12.0)
        time.sleep(0.15)
        session.unduck()
        assert wait_for(lambda: backend.spoken_seconds() >= 0.99, 2.0)
        elapsed = time.monotonic() - started
        assert 0.6 < elapsed < 1.6
        levels = {round(float(np.abs(chunk).max()), 3) for chunk in backend.spoken}
        assert 0.5 in levels and any(abs(level - 0.5 * 10 ** (-12 / 20)) < 0.01 for level in levels)
        session.speak(AudioClip(np.full(32000, 0.3, dtype=np.float32)))
        time.sleep(0.1)
        assert session.is_speaking()
        session.stop_speaking()
        assert backend.cleared == 1
        assert wait_for(lambda: not session.is_speaking(), 1.0)
        assert backend.spoken_seconds() < 2.0
    finally:
        session.close()


def test_expressions_never_block_the_motion_thread():
    backend = BodyNullBackend()
    session = BodySession(backend, poll_hz=20.0)
    session.connect()
    try:
        assert wait_for(lambda: backend.targets_sent > 2)
        assert session.express("laugh")
        before = backend.targets_sent
        time.sleep(0.5)
        assert backend.targets_sent - before >= 10  # ~30 Hz all through the expression
        assert session.telemetry().commanded.emotion == "laugh"
    finally:
        session.close()


def test_state_change_disables_motion():
    backend, session = make_session()
    seen = []
    session.on_state_change(lambda old, new: seen.append((old.state, new.state)))
    try:
        backend.awake = False
        assert wait_for(lambda: seen and seen[-1][1] == BodyState.ASLEEP, 2.0)
        count = backend.targets_sent
        time.sleep(0.2)
        assert backend.targets_sent == count
    finally:
        session.close()


def test_head_pose_matrix_is_rotation():
    pose = head_pose(0.3, -0.2, 0.1, 0.003)
    rot = pose[:3, :3]
    assert np.allclose(rot @ rot.T, np.eye(3), atol=1e-9)
    assert abs(pose[2, 3] - 0.003) < 1e-12


def test_manual_control_drops_other_sources_and_restores():
    backend, session = make_session()
    try:
        assert wait_for(lambda: backend.targets_sent > 5)
        session.take_control("test")
        assert wait_for(lambda: session.motion.state.manual)
        assert session.control_status()["held"] and session.control_status()["holder"] == "test"
        session.look(yaw=0.6, duration_s=0.1)  # attention: dropped while held
        session.listening()  # dropped too
        time.sleep(0.2)
        assert abs(math.atan2(backend.head[1, 0], backend.head[0, 0])) < 0.05
        assert session.motion.state.dropped == 2
        session.manual_pose(yaw=0.4, z=0.01, body_yaw=0.8, antennas=(0.3, -0.3), duration_s=0.1)
        assert wait_for(
            lambda: abs(math.atan2(backend.head[1, 0], backend.head[0, 0]) - 0.4) < 0.05
        )
        assert wait_for(lambda: abs(backend.body_yaw - 0.8) < 0.05)
        assert wait_for(lambda: abs(backend.antennas[0] - 0.3) < 0.05)
        assert abs(backend.head[2, 3] - 0.01) < 0.003
        sample = session.telemetry()
        assert sample.commanded.manual and abs(sample.commanded.body_yaw - 0.8) < 0.1
        session.manual_pose(yaw=5.0, z=0.5, body_yaw=9.0, duration_s=0.1)  # clamped
        assert wait_for(lambda: math.atan2(backend.head[1, 0], backend.head[0, 0]) > 0.9)
        assert math.atan2(backend.head[1, 0], backend.head[0, 0]) < 1.1
        assert wait_for(lambda: backend.body_yaw > 2.5) and backend.body_yaw < 2.7
        session.release_control()
        assert wait_for(lambda: not session.motion.state.manual)
        assert wait_for(lambda: abs(math.atan2(backend.head[1, 0], backend.head[0, 0])) < 0.05)
        assert wait_for(lambda: abs(backend.body_yaw) < 0.05)
        assert wait_for(lambda: abs(backend.antennas[0] - INIT_ANTENNAS[0]) < 0.05)
        assert session.control_status()["held"] is False
        session.look(yaw=0.3, duration_s=0.1)
        assert wait_for(
            lambda: abs(math.atan2(backend.head[1, 0], backend.head[0, 0]) - 0.3) < 0.05
        )
    finally:
        session.close()


def test_moving_window_follows_head_commands_not_antennas():
    backend, session = make_session()
    try:
        assert wait_for(lambda: backend.targets_sent > 5)
        time.sleep(0.4)
        assert not session.moving()  # resting: no idle motion (breathing retired, block #80)
        session.listening()
        time.sleep(0.1)
        assert not session.moving()  # nor are the antennas
        session.look(yaw=0.5, duration_s=0.4)
        assert wait_for(lambda: session.moving(), 0.5)
        assert session.telemetry().commanded.moving
        assert wait_for(lambda: not session.moving(), 2.0)  # 0.4 s + 0.3 s tail
        session.look(yaw=0.5, duration_s=0.4)  # already there: not motion
        time.sleep(0.1)
        assert not session.moving()
        session.gesture(Gesture.NOD)
        assert wait_for(lambda: session.moving(), 0.5)
        assert wait_for(lambda: not session.moving(), 2.0)
        session.beat("mm_hm")  # a small listening nod is not motion
        time.sleep(0.2)
        assert not session.moving()
        session.take_control("test")
        assert wait_for(lambda: session.moving(), 0.5)
        session.release_control()
    finally:
        session.close()
