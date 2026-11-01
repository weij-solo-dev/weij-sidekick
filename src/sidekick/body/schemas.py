"""sidekick.body.schemas — body-agnostic types shared by the Reachy adapter, the null body and the façade

Overview
    The vocabulary `interaction` and `perception` speak to a body: connection and motor state,
    a face observation, a direction-of-arrival reading, a touch event, the gesture and pose
    requests the motion owner consumes (including the controller's manual poses and the limits
    they are clamped to), and the `BodyBackend` protocol both adapters implement.
Design
    Frozen dataclasses only (no pydantic in this module). Angles are radians, positions metres,
    frames follow the SDK: x forward, y left, z up; yaw positive turns left. DoA follows the
    ReSpeaker convention (0 = left, π/2 = front, π = right) and `doa_to_yaw()` converts it to a
    head yaw. `BodyBackend` is deliberately thin — the façade owns threads, pacing, hysteresis
    and queues — so a new body (MuJoCo, Wireless, another robot) is one adapter file.
Depends on
    numpy.

See Also
--------
    AGENTS.md "Body", PLAN.md block "[2026-10-26 #12]".

"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

Pose = npt.NDArray[np.float64]
FloatArray = npt.NDArray[np.float32]

INIT_ANTENNAS: tuple[float, float] = (-0.1745, 0.1745)
LISTENING_ANTENNAS: tuple[float, float] = (-0.75, 0.75)
ANTENNA_PRESS_RAD = 0.3
ANTENNA_RELEASE_RAD = 0.12

# Motion limits (radians / metres) the motion owner clamps every target to. The URDF allows
# ±160° of body yaw and ±180° on the antennas; the head limits keep the Stewart platform away
# from its singular poses.
# How big one reply is performed (`[style:…]` from the agent), on top of `body.expressiveness`.
STYLE_ENERGY = {"calm": 0.6, "natural": 1.0, "lively": 1.45}
YAW_LIMIT = math.radians(60.0)
PITCH_LIMIT = math.radians(35.0)
ROLL_LIMIT = math.radians(30.0)
Z_LIMIT = 0.015
BODY_YAW_LIMIT = math.radians(150.0)
ANTENNA_LIMIT = math.radians(150.0)


class BodyState(StrEnum):
    """Mirror of the daemon's motor state (invariant 11: the body never changes it)."""

    DISCONNECTED = "disconnected"
    ASLEEP = "asleep"
    AWAKE = "awake"
    GRAVITY = "gravity_compensation"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class BodyFace:
    """Daemon-side face tracking result; `x`, `y` are in [-1, 1] of the image."""

    detected: bool
    x: float | None = None
    y: float | None = None
    roll: float | None = None
    ts: float | None = None

    @property
    def frontal(self) -> bool:
        """A face roughly centred in the image counts as looking at the robot."""
        return self.detected and self.x is not None and abs(self.x) < 0.35


@dataclass(frozen=True, slots=True)
class BodyDoA:
    """Direction of arrival from the microphone array.

    A single reading is ±50° noisy; `BodySession.doa_between` gives a stretch of speech its
    median reading, with `agreement` = the share of readings within 15° of it (1.0 for a single
    reading).
    """

    angle: float
    speech: bool
    agreement: float = 1.0

    @property
    def yaw(self) -> float:
        """Head yaw that faces the sound (left positive)."""
        return doa_to_yaw(self.angle)


def doa_to_yaw(angle: float) -> float:
    """ReSpeaker angle (0 left, π/2 front, π right) → head yaw in radians (left positive)."""
    return float(math.pi / 2.0 - angle)


def yaw_distance(a: float, b: float) -> float:
    """Smallest absolute difference between two yaws."""
    d = (a - b + math.pi) % (2.0 * math.pi) - math.pi
    return abs(d)


@dataclass(frozen=True, slots=True)
class BodyStatus:
    """What `BodySession.status()` reports."""

    state: BodyState
    daemon_state: str = "unknown"
    motor_mode: str | None = None
    robot_name: str | None = None
    version: str | None = None
    media: bool = False
    simulated: bool = False
    error: str | None = None

    @property
    def connected(self) -> bool:
        """Whether a daemon answers."""
        return self.state not in (BodyState.DISCONNECTED, BodyState.ERROR)

    @property
    def awake(self) -> bool:
        """Motors on and not in gravity compensation."""
        return self.state == BodyState.AWAKE


@dataclass(frozen=True, slots=True)
class BodyTouch:
    """An antenna (later: head) was pushed."""

    source: str
    side: str
    delta_rad: float
    ts: float


class Gesture(StrEnum):
    """Conversational beats every caller may name; each is an entry of the expression library."""

    NOD = "nod"
    SHAKE = "shake"
    TILT = "tilt"
    LOOK_UP = "look_up"
    PERK = "perk"


@dataclass(frozen=True, slots=True)
class LookTarget:
    """Where the head should rest: yaw/pitch offsets from the neutral pose."""

    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    duration_s: float = 0.6
    z: float = 0.0


@dataclass(frozen=True, slots=True)
class MotionCommand:
    """What `BodySession` enqueues for the motion owner.

    `manual=True` marks a command from the controller (the Robot tab): while the owner is held
    (`control` with `manual=True`), every command without the mark is dropped.
    """

    kind: str
    look: LookTarget | None = None
    antennas: tuple[float, float] | None = None
    expression: str | None = None  # an `expression_library.json` entry
    layer: str = "express"  # `state`, `beat` or `express` (see `motion.py`)
    intensity: float = 1.0
    mirror: bool = False
    delay_s: float = 0.0
    duration_s: float | None = None
    body_yaw: float | None = None
    manual: bool = False


@dataclass(slots=True)
class MotionState:
    """Snapshot of what the motion owner is doing."""

    look: LookTarget = field(default_factory=LookTarget)
    antennas: tuple[float, float] = INIT_ANTENNAS
    busy_until: float = 0.0
    layers: dict[str, str] = field(default_factory=dict)  # layer → expression playing on it
    gaze_held: bool = False  # an expression is turning the head (the face servo waits)
    last_sent: float = 0.0
    manual: bool = False
    body_yaw: float = 0.0
    dropped: int = 0
    moving_until: float = 0.0  # monotonic: a look / expression / pose is in progress


@dataclass(frozen=True, slots=True)
class MotionPose:
    """The last pose the motion owner computed (what it sends while the body is awake)."""

    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    z: float = 0.0
    antennas: tuple[float, float] = INIT_ANTENNAS
    gesture: str | None = None
    emotion: str | None = None
    ts: float = 0.0
    body_yaw: float = 0.0
    manual: bool = False
    moving: bool = False  # inside the motion owner's moving window
    swaying: bool = False  # the speech sway is adding an offset right now


@dataclass(frozen=True, slots=True)
class BodyTelemetry:
    """One sample of everything the body knows about itself (Live view, recorder)."""

    ts: float
    state: str
    commanded: MotionPose
    head_measured: tuple[float, ...] | None  # 4x4 row-major, relative to the rest pose
    joints_measured: tuple[float, ...] | None  # body yaw + the six Stewart motors
    antennas_measured: tuple[float, float] | None
    mic_dbfs: float
    speaker_dbfs: float
    mic_peaks: tuple[float, ...]
    speaker_peaks: tuple[float, ...]
    speaking: bool
    gain_db: float
    doa_yaw: float | None
    face: BodyFace | None
    camera_fps: float = 0.0  # frames the pump pulled from the camera in the last second

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form (what `/api/live` and `telemetry.jsonl` carry)."""
        c = self.commanded
        return {
            "ts": round(self.ts, 3),
            "state": self.state,
            "head": [round(c.yaw, 4), round(c.pitch, 4), round(c.roll, 4), round(c.z, 4)],
            "antennas": [round(c.antennas[0], 4), round(c.antennas[1], 4)],
            "body_yaw": round(c.body_yaw, 4),
            "manual": c.manual,
            "moving": c.moving,
            "swaying": c.swaying,
            "gesture": c.gesture,
            "emotion": c.emotion,
            "head_measured": None
            if self.head_measured is None
            else [round(v, 5) for v in self.head_measured],
            "joints_measured": None
            if self.joints_measured is None
            else [round(v, 4) for v in self.joints_measured],
            "antennas_measured": None
            if self.antennas_measured is None
            else [round(self.antennas_measured[0], 4), round(self.antennas_measured[1], 4)],
            "mic_dbfs": round(self.mic_dbfs, 1),
            "speaker_dbfs": round(self.speaker_dbfs, 1),
            "mic_peaks": [round(v, 3) for v in self.mic_peaks],
            "speaker_peaks": [round(v, 3) for v in self.speaker_peaks],
            "speaking": self.speaking,
            "gain_db": round(self.gain_db, 1),
            "doa_yaw": None if self.doa_yaw is None else round(self.doa_yaw, 3),
            "face": None
            if self.face is None
            else {"x": self.face.x, "y": self.face.y, "roll": self.face.roll},
            "camera_fps": round(self.camera_fps, 1),
        }


def head_pose(
    yaw: float = 0.0,
    pitch: float = 0.0,
    roll: float = 0.0,
    z: float = 0.0,
    x: float = 0.0,
    y: float = 0.0,
) -> Pose:
    """Homogeneous head pose from Euler angles (radians, `xyz` order) and translations."""
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], dtype=np.float64)
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], dtype=np.float64)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]], dtype=np.float64)
    pose = np.eye(4, dtype=np.float64)
    pose[:3, :3] = rz @ ry @ rx
    pose[0, 3] = x
    pose[1, 3] = y
    pose[2, 3] = z
    return pose


def clamp(value: float, low: float, high: float) -> float:
    """Clamp a float."""
    return max(low, min(high, value))


class BodyBackend(Protocol):
    """The thin adapter contract; all methods are synchronous and may block briefly."""

    name: str

    def connect(self) -> BodyStatus:
        """Reach the daemon (or pretend to)."""
        ...

    def close(self) -> None:
        """Release everything."""
        ...

    def status(self) -> BodyStatus:
        """Current state as mirrored from the platform."""
        ...

    def set_target(
        self, head: Pose | None, antennas: Sequence[float] | None, body_yaw: float | None
    ) -> None:
        """Immediate target for the ~30 Hz owner loop."""
        ...

    def goto(self, head: Pose | None, antennas: Sequence[float] | None, duration_s: float) -> None:
        """Interpolated move; blocks until done."""
        ...

    def present_head_pose(self) -> Pose | None:
        """Measured head pose relative to the rest pose (4x4), if the backend streams it."""
        ...

    def present_joints(self) -> tuple[list[float], list[float]] | None:
        """Measured (head joints = body yaw + six motors, antenna joints) when available."""
        ...

    def present_antennas(self) -> tuple[float, float] | None:
        """Measured antenna joint angles (right, left)."""
        ...

    def track_face(self, enabled: bool, weight: float = 1.0) -> None:
        """Toggle daemon-side face tracking."""
        ...

    def tracked_face(self) -> BodyFace:
        """Latest face observation."""
        ...

    def doa(self) -> BodyDoA | None:
        """Latest direction of arrival."""
        ...

    def start_audio(self) -> None:
        """Open capture and playback."""
        ...

    def read_audio(self) -> FloatArray | None:
        """Next mono float32 chunk at 16 kHz, or None when nothing is pending."""
        ...

    def push_audio(self, samples: FloatArray) -> None:
        """Queue mono float32 samples for the speaker."""
        ...

    def clear_audio(self) -> None:
        """Drop queued playback immediately."""
        ...

    def stop_audio(self) -> None:
        """Close capture and playback."""
        ...

    def frame(self) -> npt.NDArray[np.uint8] | None:
        """Next camera frame (BGR), or None when none is pending (may block ~20 ms)."""
        ...

    def camera_matrix(self) -> tuple[npt.NDArray[np.float64], int, int] | None:
        """Intrinsics `K` for the current resolution plus (width, height), when known."""
        ...

    def set_wobbling(self, enabled: bool) -> None:
        """Audio-reactive head wobble while speaking."""
        ...
