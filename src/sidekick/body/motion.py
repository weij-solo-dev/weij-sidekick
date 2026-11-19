"""sidekick.body.motion — the single motion owner: one thread, one `set_target` caller

Overview
    Composes the head pose every tick from a resting look direction, the
    speech sway (`sway.py`, offsets timed to the speaker audio) and Banana's own expressions
    (`expression.py`), keeps the antennas at their commanded pose, and reads the antennas back
    for touch detection. Everyone else only
    enqueues `MotionCommand`s (invariant 10). A controller (the dashboard's Robot tab) can take
    the owner over: while held, only commands marked `manual` are honoured and a `pose`
    command carries the whole target — head, height, body yaw and both antennas.
Design
    A dedicated daemon thread at ~30 Hz. Look targets ease in with a critically damped smoothing
    whose time constant comes from the requested duration. There is no idle breathing: the owner
    retired the 0.2 Hz head bob (block #80) — an idle Banana looks around instead (`interaction`).
    **Expressions** are offset curves added after the look's easing, in three
    layers that sum: `state` (thinking: held until stopped, chains to its next state), `beat`
    (small automatic motions: acknowledgements, backchannel nods, the beat nod the owner adds on
    a phrase onset of Banana's own speech, which the sway DSP reports) and `express` (what the
    agent or the dashboard asks for). A new expression on a busy layer fades the old one out in
    0.15 s; intensities are multiplied by `energy` (the household's expressiveness × the
    reply's style) when they start, and the sway by the same energy every tick. Antenna offsets
    are added after the antennas' own smoothing so a fast wiggle is not filtered away, and the
    touch detector pauses while an expression drives them. The head never stops looking at its
    target: an expression is an offset, and `state.gaze_held` tells the face servo to wait
    while an expression on the `express` layer turns the head (the thinking state keeps the
    eyes on the person since block #80, so the servo keeps tracking while Banana thinks). The SDK's `play_move()` (which
    blocked this thread and played a sound effect) is not used any more (block #50). Attention (DoA turns, face
    tracking) is decided in `interaction` and expressed through `look()` / `track_face()`.
    Manual mode drops (and counts) unmarked commands, eases the height and
    the body yaw like the look pose, and sends the body yaw to the daemon only while held and
    for a few seconds after release (easing back to zero), so the normal behaviour — body yaw
    never commanded — is unchanged. The owner also keeps a **moving window**
    (`state.moving_until`): every look that actually changes the direction, every gesture,
    expression of at least 6° and controller pose extends it by its duration plus a short tail
    (the small beats — acknowledgement, backchannel, speech beats — and the slow thinking state
    are not motion), so the voice
    front end can tell speech that starts and ends while the head motors run ("self motion")
    from the room. Antenna moves are deliberately not motion: the antennas are small quiet
    motors that move at every engagement change.
Depends on
    sidekick.log, numpy.

See Also
--------
    AGENTS.md "Body", PLAN.md block "[2026-10-26 #12]".

"""

from __future__ import annotations

import math
import queue
import random
import threading
import time
from collections.abc import Callable

from sidekick.log import Log

from .expression import ExpressionPlay, ExpressionSpec
from .schemas import (
    ANTENNA_LIMIT,
    BODY_YAW_LIMIT,
    INIT_ANTENNAS,
    PITCH_LIMIT,
    ROLL_LIMIT,
    YAW_LIMIT,
    Z_LIMIT,
    BodyBackend,
    BodyTouch,
    Gesture,
    LookTarget,
    MotionCommand,
    MotionPose,
    MotionState,
    clamp,
    head_pose,
)
from .sway import SpeechSway
from .touch import TouchDetector

SWAY_XY_LIMIT = 0.01  # metres of x / y translation the speech sway may add
BODY_YAW_SETTLE_S = 3.0  # keep sending the body yaw this long after release so it eases home
MOVING_TAIL_S = 0.3  # the moving window outlasts a command by this much (motors settle, audio lag)
MOVING_MIN_DELTA_RAD = math.radians(
    2.0
)  # a look closer than this to the current pose is not motion

EXPRESSION_XY_LIMIT = 0.012  # metres of x / y translation (sway included)
EXPRESSION_REPLACE_FADE_S = 0.15  # a new expression on a busy layer: the old one fades this fast
GAZE_HOLD_DEG = 3.0  # an expression turning the head this far holds the face servo
MOVING_MIN_DEG = 6.0  # an expression or beat this big is motion (the motors are heard)
LAYERS = ("state", "beat", "express")
SPEECH_BEAT = "emphasis"  # the beat nod on a phrase onset of Banana's own speech
SPEECH_BEAT_GAP_S = 2.2
SPEECH_BEAT_CHANCE = 0.55  # at energy 1.0; scaled by the energy, at most 0.9


class MotionOwner(threading.Thread):
    """The only thread that calls `backend.set_target`."""

    def __init__(
        self,
        backend: BodyBackend,
        rate_hz: float = 30.0,
        on_touch: Callable[[BodyTouch], None] | None = None,
    ) -> None:
        super().__init__(name="sidekick-motion", daemon=True)
        self.backend = backend
        self.period = 1.0 / rate_hz
        self.commands: queue.Queue[MotionCommand] = queue.Queue()
        self.state = MotionState()
        self.on_touch = on_touch
        self.touch = TouchDetector()
        self._stop_event = threading.Event()
        self._enabled = threading.Event()
        self._current = LookTarget()
        self._antenna_target: tuple[float, float] = INIT_ANTENNAS
        self._antenna_current: tuple[float, float] = INIT_ANTENNAS
        self._antenna_until = 0.0
        self._body_yaw_current = 0.0
        self._body_yaw_send_until = 0.0
        self.sway: SpeechSway | None = None  # set by the façade; read every tick
        self.library: dict[str, ExpressionSpec] = {}  # set by the façade
        self.energy = 1.0  # expressiveness × the reply's style, set by the façade
        self._plays: dict[str, ExpressionPlay] = {}  # layer → the play on it
        self._fading: list[ExpressionPlay] = []  # replaced or stopped plays fading out
        self._last_speech_beat = float("-inf")
        self.rng = random.Random()
        self.ticks = 0
        self.pose_snapshot = MotionPose()

    # ---------------------------------------------------------------- commands

    def look(self, target: LookTarget, manual: bool = False) -> None:
        """Rest the head on a new direction."""
        self.commands.put(MotionCommand("look", look=target, manual=manual))

    def gesture(self, gesture: Gesture, manual: bool = False) -> None:
        """Play a conversational beat by its `Gesture` name."""
        self.expression(gesture.value, layer="beat", manual=manual)

    def expression(
        self,
        name: str,
        layer: str = "express",
        intensity: float = 1.0,
        mirror: bool = False,
        delay_s: float = 0.0,
        manual: bool = False,
    ) -> None:
        """Play a library expression on a layer (replacing what that layer plays)."""
        self.commands.put(
            MotionCommand(
                "expression",
                expression=name,
                layer=layer,
                intensity=intensity,
                mirror=mirror,
                delay_s=delay_s,
                manual=manual,
            )
        )

    def stop_expression(self, layer: str, fade_s: float = 0.3, manual: bool = False) -> None:
        """Fade out whatever plays on a layer."""
        self.commands.put(
            MotionCommand("stop_expression", layer=layer, duration_s=fade_s, manual=manual)
        )

    def antennas(
        self,
        pose: tuple[float, float] | None,
        duration_s: float | None = None,
        manual: bool = False,
    ) -> None:
        """Hold the antennas at `pose` (None = neutral), optionally only for `duration_s`."""
        self.commands.put(
            MotionCommand("antennas", antennas=pose, duration_s=duration_s, manual=manual)
        )

    def control(self, manual: bool) -> None:
        """Take the owner over (`True`) or hand it back (`False`, posture returns to neutral)."""
        self.commands.put(MotionCommand("control", manual=manual))

    def pose(
        self,
        look: LookTarget,
        antennas: tuple[float, float] | None = None,
        body_yaw: float | None = None,
    ) -> None:
        """The controller's full target (only honoured while held)."""
        self.commands.put(
            MotionCommand("pose", look=look, antennas=antennas, body_yaw=body_yaw, manual=True)
        )

    def current_look(self) -> LookTarget:
        """The eased look pose right now (no gesture overlay): the servo's base."""
        return self._current

    def moving(self, now: float | None = None) -> bool:
        """Whether a look, an expression or a controller pose is in progress."""
        return (time.monotonic() if now is None else now) < self.state.moving_until

    def _mark_moving(self, now: float, seconds: float) -> None:
        self.state.moving_until = max(self.state.moving_until, now + seconds + MOVING_TAIL_S)

    def enable(self, enabled: bool = True) -> None:
        """Only an awake body receives targets; the façade toggles this from status polls."""
        if enabled:
            self._enabled.set()
        else:
            self._enabled.clear()

    def stop(self) -> None:
        """Ask the thread to exit."""
        self._stop_event.set()

    # -------------------------------------------------------------------- loop

    def run(self) -> None:
        """Tick until stopped."""
        Log.info0(f"motion owner at {1.0 / self.period:.0f} Hz")
        self.touch.resume()
        next_tick = time.monotonic()
        while not self._stop_event.is_set():
            now = time.monotonic()
            self._drain_commands(now)
            if self._enabled.is_set():
                self._tick(now)
            next_tick += self.period
            delay = next_tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_tick = time.monotonic()
        Log.info("motion owner stopped")

    def _drain_commands(self, now: float) -> None:
        while True:
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                return
            if command.kind == "control":
                self._set_manual(command.manual, now)
                continue
            if self.state.manual and not command.manual:
                self.state.dropped += 1
                continue
            if command.kind == "pose" and command.look is not None:
                self.state.look = command.look
                self._mark_moving(now, max(command.look.duration_s, 0.2))
                if command.antennas is not None:
                    self._antenna_target = (
                        clamp(command.antennas[0], -ANTENNA_LIMIT, ANTENNA_LIMIT),
                        clamp(command.antennas[1], -ANTENNA_LIMIT, ANTENNA_LIMIT),
                    )
                    self._antenna_until = 0.0
                    self.state.antennas = self._antenna_target
                if command.body_yaw is not None:
                    self.state.body_yaw = clamp(command.body_yaw, -BODY_YAW_LIMIT, BODY_YAW_LIMIT)
            elif command.kind == "look" and command.look is not None:
                self.state.look = command.look
                if self._differs(command.look):
                    self._mark_moving(now, max(command.look.duration_s, 0.2))
            elif command.kind == "expression" and command.expression is not None:
                self._start_expression(command, now)
            elif command.kind == "stop_expression":
                self._stop_layer(command.layer, now, command.duration_s or 0.3)
            elif command.kind == "antennas":
                self._antenna_target = command.antennas or INIT_ANTENNAS
                self._antenna_until = now + command.duration_s if command.duration_s else 0.0
                self.state.antennas = self._antenna_target
                self.touch.pause(now)
                # antenna moves are not motion for the voice front end: the two small
                # low-stiffness motors are quiet, and they move at every engagement change

    def _differs(self, look: LookTarget) -> bool:
        """Whether a look target is far enough from the current pose to move the motors."""
        c = self._current
        return (
            abs(look.yaw - c.yaw) >= MOVING_MIN_DELTA_RAD
            or abs(look.pitch - c.pitch) >= MOVING_MIN_DELTA_RAD
            or abs(look.roll - c.roll) >= MOVING_MIN_DELTA_RAD
            or abs(look.z - c.z) >= 0.002
        )

    def _set_manual(self, manual: bool, now: float) -> None:
        if manual == self.state.manual:
            return
        self.state.manual = manual
        self._mark_moving(now, 1.0)
        if manual:
            for layer in LAYERS:
                self._stop_layer(layer, now, EXPRESSION_REPLACE_FADE_S)
            self.state.look = LookTarget(
                self._current.yaw, self._current.pitch, self._current.roll, 0.6, self._current.z
            )
            self.touch.pause(now)
            Log.info("motion owner held by the controller")
        else:
            self.state.look = LookTarget(duration_s=1.0)
            self._antenna_target = INIT_ANTENNAS
            self._antenna_until = 0.0
            self.state.antennas = INIT_ANTENNAS
            self.state.body_yaw = 0.0
            self._body_yaw_send_until = now + BODY_YAW_SETTLE_S
            for layer in LAYERS:
                self._stop_layer(layer, now, EXPRESSION_REPLACE_FADE_S)
            self.touch.pause(now)
            Log.info(f"motion owner released ({self.state.dropped} commands dropped meanwhile)")
            self.state.dropped = 0

    # ------------------------------------------------------------- expressions

    def _start_expression(self, command: MotionCommand, now: float) -> None:
        spec = self.library.get(command.expression or "")
        if spec is None:
            Log.info(f"unknown expression {command.expression!r} ignored")
            return
        self._stop_layer(command.layer, now, EXPRESSION_REPLACE_FADE_S)
        started = now + max(0.0, command.delay_s)
        play = ExpressionPlay(
            spec, started, intensity=command.intensity * self.energy, mirror=command.mirror
        )
        self._plays[command.layer] = play
        if command.layer != "state" and spec.head_peak_deg * play.intensity >= MOVING_MIN_DEG:
            self._mark_moving(started, spec.duration / play.speed)
        if spec.moves_antennas:
            self.touch.pause(now)
        Log.debug(f"expression {spec.name} on {command.layer} ×{play.intensity:.2f}")

    def _stop_layer(self, layer: str, now: float, fade_s: float) -> None:
        play = self._plays.pop(layer, None)
        if play is not None:
            play.cancel(now, fade_s)
            self._fading.append(play)

    def _expression_offsets(self, now: float) -> dict[str, float]:
        """The summed channels of every layer and every fading play (file units)."""
        total: dict[str, float] = {}

        def add(play: ExpressionPlay) -> None:
            for channel, value in play.sample(now).items():
                total[channel] = total.get(channel, 0.0) + value

        for layer, play in list(self._plays.items()):
            if play.finished(now):
                del self._plays[layer]
                following = self.library.get(play.spec.then or "")
                if following is None or play.cancel_at is not None:
                    continue
                play = ExpressionPlay(following, now, play.intensity, mirror=play.mirror)
                self._plays[layer] = play
            add(play)
        self._fading = [play for play in self._fading if not play.finished(now)]
        for play in self._fading:
            add(play)
        self.state.layers = {layer: play.spec.name for layer, play in self._plays.items()}
        self.state.gaze_held = any(
            layer == "express" and play.spec.head_peak_deg * play.intensity >= GAZE_HOLD_DEG
            for layer, play in self._plays.items()
        )
        return total

    def _antenna_plays(self) -> bool:
        return any(p.spec.moves_antennas for p in (*self._plays.values(), *self._fading))

    def _speech_beat(self, now: float) -> None:
        """A phrase of Banana's speech starts: sometimes a small beat nod with it."""
        if now - self._last_speech_beat < SPEECH_BEAT_GAP_S or self.state.manual:
            return
        self._last_speech_beat = now
        if "express" in self._plays or "beat" in self._plays:
            return
        if self.rng.random() < min(0.9, SPEECH_BEAT_CHANCE * self.energy):
            self._start_expression(
                MotionCommand("expression", expression=SPEECH_BEAT, layer="beat"), now
            )

    def _tick(self, now: float) -> None:
        self.ticks += 1
        look = self.state.look
        alpha = 1.0 - math.exp(-self.period / max(0.05, look.duration_s / 3.0))
        self._current = LookTarget(
            yaw=self._current.yaw + (look.yaw - self._current.yaw) * alpha,
            pitch=self._current.pitch + (look.pitch - self._current.pitch) * alpha,
            roll=self._current.roll + (look.roll - self._current.roll) * alpha,
            duration_s=look.duration_s,
            z=self._current.z + (look.z - self._current.z) * alpha,
        )
        yaw, pitch, roll = self._current.yaw, self._current.pitch, self._current.roll
        z = self._current.z
        body_yaw: float | None = None
        if self.state.manual or now < self._body_yaw_send_until:
            self._body_yaw_current += (self.state.body_yaw - self._body_yaw_current) * alpha
            body_yaw = self._body_yaw_current
        x = y = 0.0
        swaying = False
        if self.sway is not None:
            sway = self.sway.offsets(now)
            if sway.active:
                swaying = True
                if self.energy != 1.0:
                    sway = sway.scaled(self.energy)
                yaw, pitch, roll = yaw + sway.yaw, pitch + sway.pitch, roll + sway.roll
                z += sway.z
                x = clamp(sway.x, -SWAY_XY_LIMIT, SWAY_XY_LIMIT)
                y = clamp(sway.y, -SWAY_XY_LIMIT, SWAY_XY_LIMIT)
            if self.sway.take_onsets(now):
                self._speech_beat(now)
        offsets = self._expression_offsets(now)
        if offsets:
            yaw += math.radians(offsets.get("yaw", 0.0))
            pitch += math.radians(offsets.get("pitch", 0.0))
            roll += math.radians(offsets.get("roll", 0.0))
            z += offsets.get("z", 0.0) / 1000.0
            x = clamp(x + offsets.get("x", 0.0) / 1000.0, -EXPRESSION_XY_LIMIT, EXPRESSION_XY_LIMIT)
            y = clamp(y + offsets.get("y", 0.0) / 1000.0, -EXPRESSION_XY_LIMIT, EXPRESSION_XY_LIMIT)
        if self._antenna_until and now >= self._antenna_until:
            self._antenna_target = INIT_ANTENNAS
            self._antenna_until = 0.0
            self.state.antennas = INIT_ANTENNAS
        right, left = self._antenna_target
        a = 1.0 - math.exp(-self.period / 0.12)
        self._antenna_current = (
            self._antenna_current[0] + (right - self._antenna_current[0]) * a,
            self._antenna_current[1] + (left - self._antenna_current[1]) * a,
        )
        # expression offsets after the smoothing (a 5 Hz wiggle would be filtered away);
        # positive raises either antenna: the right one's angle goes down, the left one's up
        antennas = (
            clamp(
                self._antenna_current[0] - math.radians(offsets.get("ant_r", 0.0)),
                -ANTENNA_LIMIT,
                ANTENNA_LIMIT,
            ),
            clamp(
                self._antenna_current[1] + math.radians(offsets.get("ant_l", 0.0)),
                -ANTENNA_LIMIT,
                ANTENNA_LIMIT,
            ),
        )
        yaw = clamp(yaw, -YAW_LIMIT, YAW_LIMIT)
        pitch = clamp(pitch, -PITCH_LIMIT, PITCH_LIMIT)
        roll = clamp(roll, -ROLL_LIMIT, ROLL_LIMIT)
        z = clamp(z, -Z_LIMIT, Z_LIMIT)
        pose = head_pose(yaw, pitch, roll, z, x, y)
        self.pose_snapshot = MotionPose(
            yaw,
            pitch,
            roll,
            z,
            antennas,
            self.state.layers.get("beat") or self.state.layers.get("state"),
            self.state.layers.get("express"),
            now,
            self._body_yaw_current,
            self.state.manual,
            now < self.state.moving_until,
            swaying,
        )
        if now >= self.state.busy_until:
            self.backend.set_target(pose, antennas, body_yaw)
            self.state.last_sent = now
        if (
            self.touch.paused
            and self._antenna_until == 0.0
            and not self._antenna_plays()
            and abs(self._antenna_current[0] - right) < 0.02
        ):
            self.touch.resume(now)
        if self.on_touch is not None and not self.touch.paused:
            present = self.backend.present_antennas()
            if present is not None:
                event = self.touch.update(antennas, present, now)
                if event is not None:
                    Log.info(f"touch {event.side} antenna delta={event.delta_rad:.2f} rad")
                    self.on_touch(event)
