"""sidekick.body.null — a body made of state only, for development and tests without a robot

Overview
    Implements `BodyBackend` with in-memory state: targets are recorded, antennas can be
    "pushed" by tests, audio input is whatever the test feeds, audio output is collected, face
    and DoA readings are injectable (expressions are played by the motion owner as targets).
Design
    Everything is synchronous and thread-safe enough for the façade's threads (a lock around
    the queues). The null body is also what sidekick runs with `body.mode = "null"`, so
    the voice pipeline can be exercised from the dashboard without hardware.
Depends on
    numpy.

See Also
--------
    AGENTS.md "Body".

"""

from __future__ import annotations

import collections
import threading
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from .schemas import INIT_ANTENNAS, BodyDoA, BodyFace, BodyState, BodyStatus, FloatArray, Pose


class BodyNullBackend:
    """`BodyBackend` with no hardware behind it."""

    name = "null"

    def __init__(self, awake: bool = True) -> None:
        self._lock = threading.Lock()
        self.awake = awake
        self.connected = False
        self.head: Pose | None = None
        self.antennas: tuple[float, float] = INIT_ANTENNAS
        self.antenna_offset: tuple[float, float] = (0.0, 0.0)
        self.body_yaw: float | None = None
        self.targets_sent = 0
        self.gotos: list[tuple[Pose | None, tuple[float, ...] | None, float]] = []
        self.tracking: tuple[bool, float] = (False, 0.0)
        self.face = BodyFace(False)
        self.doa_value: BodyDoA | None = None
        self.wobbling = False
        self.audio_started = False
        self._inbox: collections.deque[FloatArray] = collections.deque()
        self.spoken: list[FloatArray] = []
        self.cleared = 0
        self._frame: npt.NDArray[np.uint8] | None = None

    def connect(self) -> BodyStatus:
        """Always succeeds."""
        self.connected = True
        return self.status()

    def close(self) -> None:
        """Forget the connection."""
        self.connected = False
        self.audio_started = False

    def status(self) -> BodyStatus:
        """Awake unless told otherwise."""
        if not self.connected:
            return BodyStatus(BodyState.DISCONNECTED, daemon_state="stopped")
        state = BodyState.AWAKE if self.awake else BodyState.ASLEEP
        return BodyStatus(
            state,
            daemon_state="running",
            motor_mode="enabled" if self.awake else "disabled",
            robot_name="null",
            version="0",
            media=True,
            simulated=True,
        )

    def set_target(
        self, head: Pose | None, antennas: Sequence[float] | None, body_yaw: float | None
    ) -> None:
        """Record the target."""
        with self._lock:
            if head is not None:
                self.head = np.array(head, dtype=np.float64)
            if antennas is not None:
                self.antennas = (float(antennas[0]), float(antennas[1]))
            if body_yaw is not None:
                self.body_yaw = body_yaw
            self.targets_sent += 1

    def goto(self, head: Pose | None, antennas: Sequence[float] | None, duration_s: float) -> None:
        """Record the move and apply it instantly."""
        self.gotos.append(
            (head, tuple(float(a) for a in antennas) if antennas is not None else None, duration_s)
        )
        self.set_target(head, antennas, None)

    def present_antennas(self) -> tuple[float, float] | None:
        """Commanded pose plus the test's push offset."""
        with self._lock:
            return (
                self.antennas[0] + self.antenna_offset[0],
                self.antennas[1] + self.antenna_offset[1],
            )

    def present_head_pose(self) -> Pose | None:
        """The last commanded head pose (there are no sensors here)."""
        with self._lock:
            return None if self.head is None else np.array(self.head, dtype=np.float64)

    def present_joints(self) -> tuple[list[float], list[float]] | None:
        """No joint stream on the null body."""
        return None

    def push_antenna(self, side: str, delta_rad: float) -> None:
        """Test hook: simulate a finger on an antenna (`right` or `left`)."""
        with self._lock:
            right, left = self.antenna_offset
            self.antenna_offset = (delta_rad, left) if side == "right" else (right, delta_rad)

    def track_face(self, enabled: bool, weight: float = 1.0) -> None:
        """Record the toggle."""
        self.tracking = (enabled, weight)

    def tracked_face(self) -> BodyFace:
        """Whatever the test injected."""
        return self.face

    def doa(self) -> BodyDoA | None:
        """Whatever the test injected."""
        return self.doa_value

    def start_audio(self) -> None:
        """Mark audio as started."""
        self.audio_started = True

    def feed_audio(self, samples: FloatArray, chunk: int = 320) -> None:
        """Test hook: queue capture audio in `chunk`-sample pieces (20 ms at 16 kHz)."""
        arr = np.asarray(samples, dtype=np.float32)
        with self._lock:
            for start in range(0, len(arr), chunk):
                self._inbox.append(arr[start : start + chunk])

    def read_audio(self) -> FloatArray | None:
        """Pop the next fed chunk."""
        with self._lock:
            if not self._inbox:
                return None
            return self._inbox.popleft()

    def push_audio(self, samples: FloatArray) -> None:
        """Collect played audio."""
        with self._lock:
            self.spoken.append(np.asarray(samples, dtype=np.float32))

    def spoken_seconds(self, sample_rate: int = 16000) -> float:
        """Total audio pushed so far."""
        with self._lock:
            return sum(len(s) for s in self.spoken) / float(sample_rate)

    def clear_audio(self) -> None:
        """Count flushes."""
        self.cleared += 1

    def stop_audio(self) -> None:
        """Mark audio as stopped."""
        self.audio_started = False

    def frame(self) -> npt.NDArray[np.uint8] | None:
        """Injected frame, if any."""
        return self._frame

    def set_frame(self, frame: npt.NDArray[np.uint8] | None) -> None:
        """Test hook."""
        self._frame = frame

    def camera_matrix(self) -> tuple[npt.NDArray[np.float64], int, int] | None:
        """No camera model (the servo falls back to the Lite's nominal field of view)."""
        return None

    def set_wobbling(self, enabled: bool) -> None:
        """Record the toggle."""
        self.wobbling = enabled
