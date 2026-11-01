"""sidekick.interaction.attention — where the robot looks and how it signals listening

Overview
    Turns engagement events into body language through `BodySession`: turn toward the speech
    direction, **keep a face centred** (our own detector's observations at 10 Hz drive a
    proportional servo through the motion owner; the daemon's tracker is an option), lift the
    antennas while listening, and relax when the conversation ends. **Conversation** (block
    #50): a small `ack` when a turn is accepted ("I heard you"), then **thinking** — the
    `think` state tilts the head a little with the antennas swaying in turn, chains to
    `think_long` after 2.5 s (the tilt slowly changes side, a small "hmm", the antennas tick) —
    and the state ends the moment the first sentence is ready; if they talk again meanwhile the
    listening pose returns at once. Thinking no longer looks away: the owner read the sideways
    glances as looking around (「说话过程又有东张西望」, block #80), so in a conversation the eyes
    stay on the person and the face servo keeps running while Bobby thinks. A `yield` beat ends a reply (your turn); while they talk, a small `mm_hm`
    nod at their pauses. While idle it keeps a
    social presence on its own: **scanning glances** (every 8–15 s a slow look at a random
    direction within ±40°, held a few seconds, back to neutral — the camera's horizontal field
    is only 90°, so a person off to the side is never found without it) and **sound glances**
    (a look toward a clear sound the engagement machine rejected: orient, never speak). Both
    stop the moment a face is seen — a face owns the head.
Design
    Thin and rate-limited. A DoA turn happens only for an **accepted** segment or the wake name
    (never on a mere speech onset: ambient noise was re-aiming the head every 0.5 s on
    2026-10-26), only from a segment whose direction readings agree (`BodyDoA.agreement` ≥
    `DOA_MIN_AGREEMENT`; a segment's direction is the median of its readings, block #80), only
    when the new direction differs from the current look by ≥ 15°, and never while a face is
    tracked — by the daemon or by our own servo within the last `FACE_RECENT_S`. Inside a
    session the person is usually where Bobby already looks and even a median direction
    wanders ±15–30° for a source that does not move (a test from the Mac's speaker read −8°,
    24°, 2°), so a turn there needs ≥ 20° and **two accepted segments in a row** agreeing on
    the new direction within `TURN_AGREE_RAD`; one stray reading never moves the head. The **face servo** runs on every detection: the pixel offset of
    the face becomes an angle through the camera's field of view (intrinsics from the SDK,
    nominal 90° × 59° otherwise), the new look target is the owner's *current* eased pose plus
    `gain` × that angle (gain 0.7, dead band 0.03 ≈ 1.4°), and the owner's easing (0.35 s)
    smooths it into a pursuit — so nods and glances compose with the tracking. The
    servo waits while an expression turns the head (`BodySession.gaze_held()`), otherwise it
    would chase the face the expression moved in the image and cancel the expression.
    Measured before (2026-10-27): the daemon's tracker blended at weight 0.3 never centred the
    face, and our old servo stepped 11° every 0.5 s. Two seconds after the face is lost the
    head eases back to neutral. Glances are driven by the
    façade's 0.5 s tick (`tick()`); a glance is a `(kind, until)` pair, and the return to
    neutral happens when it expires. Sound glances need a level and a duration (the ReSpeaker
    direction is ±50° noisy on ambient sound) and at most one every `SOUND_GLANCE_GAP_S`.
    Knobs come from `ConfigInteraction` through `configure()`. All motion goes through
    `BodySession` verbs, never the SDK (invariant 10).
Depends on
    sidekick.body, sidekick.log.

See Also
--------
    AGENTS.md "Interaction" (IDLE social presence, attention), PLAN.md block "[2026-10-27 #38]".

"""

from __future__ import annotations

import math
import random
import time
from typing import Any

from sidekick.body import BodyDoA, BodyFace, BodySession, Gesture, doa_to_yaw, yaw_distance
from sidekick.log import Log

TURN_HYSTERESIS_RAD = math.radians(15.0)
SESSION_TURN_RAD = math.radians(20.0)  # inside a session the person is usually already in view
TURN_AGREE_RAD = math.radians(20.0)  # ...and two segments in a row must agree on the new direction
DOA_MIN_AGREEMENT = 0.5  # a segment whose readings agree less than this has no direction
FACE_RECENT_S = 1.5  # our servo saw a face this recently: the face owns the head
SERVO_MIN_PERIOD_S = 0.05  # detections arrive at ~10 Hz; never command faster than this
SERVO_MOVE_S = 0.35  # easing of each servo step (the owner's time constant is a third)
SERVO_DEAD_BAND = 0.03  # of the half image (≈ 1.4° at 90° field of view)
SERVO_YAW_LIMIT = 1.0
SERVO_PITCH_LIMIT = 0.45
SERVO_MAX_AGE_S = 0.5  # ignore a detection older than this
DEFAULT_FOV = (math.radians(90.0), math.radians(59.0))  # Lite camera at 16:9, nominal
FACE_LOST_RECENTER_S = 2.0
SCAN_MOVE_S = 1.2  # a glance eases over this long: slow, not a startle
SCAN_MIN_YAW_RAD = math.radians(20.0)  # a glance smaller than this is not worth the motors
SOUND_GLANCE_GAP_S = 8.0
SOUND_GLANCE_MOVE_S = 0.8
RETURN_S = 1.2
THINK_DELAY_S = 0.35  # the acknowledgement plays first, then the gaze moves away
THINK_RETURN_S = 0.35  # the gaze back on the person before the first word
BACKCHANNEL_GAP_S = 3.5
BACKCHANNEL_CHANCE = 0.7
ACK_AFTER_BACKCHANNEL_S = 0.8  # a backchannel nod this recent already said "I heard you"


class Attention:
    """Head, antennas and face tracking as a function of engagement."""

    def __init__(
        self, body: BodySession, idle_weight: float = 0.3, engaged_weight: float = 1.0
    ) -> None:
        self.body = body
        self.idle_weight = idle_weight
        self.engaged_weight = engaged_weight
        self._last_turn = 0.0
        self._last_servo = 0.0
        self._face_at = float("-inf")  # our servo's last detection (monotonic)
        self._turn_pending: float | None = None  # a session's new direction, heard once so far
        self._yaw = 0.0
        self._pitch = 0.0
        self.engaged = False
        self.rng = random.Random()
        # face servo
        self.daemon_tracking = False  # `face_tracker: daemon` — the daemon blends its own aim
        self.servo_gain = 0.7
        self._daemon_tracking_on: tuple[bool, float] | None = None
        self._face_lost_at: float | None = None
        self.servo_steps = 0
        # idle glances
        self.scan_enabled = True
        self.scan_min_s = 8.0
        self.scan_max_s = 15.0
        self.scan_yaw_rad = 0.7
        self.scan_hold_s = 2.5
        self.sound_enabled = True
        self.sound_min_dbfs = -35.0
        self.sound_min_s = 0.6
        self.sound_hold_s = 3.0
        self._glance: tuple[str, float] | None = None  # (kind, until)
        self._next_scan = 0.0
        self._scan_side = 1.0
        self._last_sound_glance = float("-inf")
        self._face_seen = False
        self.mode = "idle"
        self.glances = 0
        # conversation
        self.thinking_now = False
        self._spoke = False
        self._last_backchannel = float("-inf")
        self.backchannels = 0

    def configure(self, config: Any) -> None:
        """Take the knobs from `ConfigInteraction` (also after a Settings change)."""
        self.daemon_tracking = str(getattr(config, "face_tracker", "own")) == "daemon"
        self.servo_gain = float(getattr(config, "face_servo_gain", 0.7))
        self.idle_weight = float(getattr(config, "idle_face_tracking_weight", self.idle_weight))
        self.engaged_weight = float(
            getattr(config, "engaged_face_tracking_weight", self.engaged_weight)
        )
        self.scan_enabled = bool(getattr(config, "idle_scan", True))
        self.scan_min_s = float(getattr(config, "idle_scan_min_s", 8.0))
        self.scan_max_s = max(self.scan_min_s, float(getattr(config, "idle_scan_max_s", 15.0)))
        self.scan_yaw_rad = float(getattr(config, "idle_scan_yaw_rad", 0.7))
        self.scan_hold_s = float(getattr(config, "idle_scan_hold_s", 2.5))
        self.sound_enabled = bool(getattr(config, "sound_glance", True))
        self.sound_min_dbfs = float(getattr(config, "sound_glance_min_dbfs", -35.0))
        self.sound_min_s = float(getattr(config, "sound_glance_min_s", 0.6))
        self.sound_hold_s = float(getattr(config, "sound_glance_hold_s", 3.0))

    def start(self) -> None:
        """Idle posture."""
        self.set_engaged(False)

    def _schedule_scan(self, now: float) -> None:
        self._next_scan = now + self.rng.uniform(self.scan_min_s, self.scan_max_s)

    def _daemon_tracking(self, enabled: bool, weight: float = 1.0) -> None:
        """Toggle the daemon's tracker only when something changes (it logs and restarts)."""
        key = enabled and weight > 0
        state = (key, weight if key else 0.0)
        if self._daemon_tracking_on == state:
            return
        self._daemon_tracking_on = state
        self.body.track_face(key, weight)

    def set_engaged(self, engaged: bool) -> None:
        """Switch between idle glances and full attention."""
        self.end_thinking()
        self.engaged = engaged
        self._glance = None
        self._turn_pending = None
        if engaged:
            self.mode = "engaged"
            if self.daemon_tracking:
                self._daemon_tracking(True, self.engaged_weight)
            else:
                self._daemon_tracking(False)
            self.body.listening()
        else:
            self.mode = "idle"
            if self.daemon_tracking:
                self._daemon_tracking(self.idle_weight > 0, self.idle_weight)
            else:
                self._daemon_tracking(False)
            self.body.relax()
            self.body.look_neutral(RETURN_S)
            self._yaw = self._pitch = 0.0
            self._face_lost_at = None
            self._schedule_scan(time.monotonic())

    def face_tracked(self) -> bool:
        """Whether the daemon's tracker currently has a face (then it owns the head)."""
        return bool(self.body.face().detected)

    # ------------------------------------------------------------- idle glances

    def tick(self, face_visible: bool, now: float | None = None) -> None:
        """Every 0.5 s while idle: run or end a glance, or start the next scanning glance."""
        now = time.monotonic() if now is None else now
        if self.engaged:
            return
        if face_visible:
            # a face owns the head (tracker or servo); glances pause and the clock restarts
            if self._glance is not None or not self._face_seen:
                self._glance = None
                self._schedule_scan(now)
            self._face_seen = True
            self._face_lost_at = None
            self.mode = "face"
            return
        if self._face_seen:
            self._face_seen = False
            self._face_lost_at = now
        if self._face_lost_at is not None and now - self._face_lost_at >= FACE_LOST_RECENTER_S:
            # the person left the frame: ease back to neutral instead of staring at the wall
            self._face_lost_at = None
            if self._glance is None:
                self.body.look_neutral(RETURN_S)
                self._yaw = self._pitch = 0.0
                self._schedule_scan(now)
        if self._glance is not None:
            kind, until = self._glance
            if now >= until:
                self._glance = None
                self.body.look_neutral(RETURN_S)
                self._yaw = self._pitch = 0.0
                self.mode = "idle"
                self._schedule_scan(now)
                Log.debug(f"{kind} glance over, back to neutral")
            return
        if self.mode == "face":
            self.mode = "idle"
        if not self.scan_enabled or now < self._next_scan:
            return
        self._scan_side = -self._scan_side
        yaw = self._scan_side * self.rng.uniform(
            SCAN_MIN_YAW_RAD, max(SCAN_MIN_YAW_RAD, self.scan_yaw_rad)
        )
        pitch = self.rng.uniform(-0.08, 0.05)
        self._look_glance("scan", yaw, pitch, SCAN_MOVE_S, self.scan_hold_s, now)

    def on_sound(
        self, doa: BodyDoA | None, level_dbfs: float, duration_s: float, now: float | None = None
    ) -> bool:
        """Idle only: glance toward a clear sound the machine rejected (orient, never speak)."""
        now = time.monotonic() if now is None else now
        if (
            not self.sound_enabled
            or self.engaged
            or doa is None
            or level_dbfs < self.sound_min_dbfs
            or duration_s < self.sound_min_s
            or now - self._last_sound_glance < SOUND_GLANCE_GAP_S
            or self.face_tracked()
        ):
            return False
        yaw = max(-1.0, min(1.0, doa_to_yaw(doa.angle)))
        if self._glance is not None and yaw_distance(yaw, self._yaw) < TURN_HYSTERESIS_RAD:
            return False
        self._last_sound_glance = now
        self._look_glance("sound", yaw, 0.0, SOUND_GLANCE_MOVE_S, self.sound_hold_s, now)
        return True

    def _look_glance(
        self, kind: str, yaw: float, pitch: float, move_s: float, hold_s: float, now: float
    ) -> None:
        self.glances += 1
        self._yaw, self._pitch = yaw, pitch
        self._glance = (kind, now + move_s + hold_s)
        self.mode = kind
        self.body.look(yaw=yaw, pitch=pitch, duration_s=move_s)
        Log.debug(f"{kind} glance to yaw {math.degrees(yaw):.0f}°")

    def snapshot(self) -> dict[str, Any]:
        """For the rail's Conversation card."""
        now = time.monotonic()
        return {
            "mode": self.mode,
            "tracker": "daemon" if self.daemon_tracking else "own",
            "servo_steps": self.servo_steps,
            "glance_s": None if self._glance is None else round(max(0.0, self._glance[1] - now), 1),
            "next_scan_s": None
            if self.engaged or not self.scan_enabled
            else round(max(0.0, self._next_scan - now), 1),
            "yaw": round(self._yaw, 2),
            "glances": self.glances,
        }

    # ---------------------------------------------------------------- speech

    def on_speech(self, doa: BodyDoA | None, force: bool = False) -> None:
        """Turn toward an accepted speaker (or the wake name); a tracked face wins."""
        if doa is None or doa.agreement < DOA_MIN_AGREEMENT or not (self.engaged or force):
            return
        now = time.monotonic()
        if not force and (self.face_tracked() or now - self._face_at < FACE_RECENT_S):
            return
        if now - self._last_turn < 0.5:
            return
        yaw = doa_to_yaw(doa.angle)
        min_turn = SESSION_TURN_RAD if self.engaged and not force else TURN_HYSTERESIS_RAD
        if not force and yaw_distance(yaw, self._yaw) < min_turn:
            self._turn_pending = None
            return
        if self.engaged and not force:
            pending, self._turn_pending = self._turn_pending, yaw
            if pending is None or yaw_distance(yaw, pending) > TURN_AGREE_RAD:
                return  # heard from there once: wait for a second segment to agree
            yaw = (yaw + pending) / 2.0
            self._turn_pending = None
        self._last_turn = now
        self._glance = None
        self._yaw, self._pitch = yaw, 0.0
        self.body.look(yaw=yaw, duration_s=0.5)
        Log.debug(f"turn toward doa {doa.angle:.2f} rad (yaw {yaw:.2f})")

    def on_face(self, face: BodyFace | None, now: float | None = None) -> bool:
        """Keep the face centred: one proportional step per detection of our own detector."""
        if face is None or not face.detected or face.x is None or face.y is None:
            return False
        if self.daemon_tracking and self.face_tracked():
            return False  # the daemon's tracker owns the head in that mode
        now = time.monotonic() if now is None else now
        if face.ts is not None and time.time() - face.ts > SERVO_MAX_AGE_S:
            return False
        self._face_at = now
        if self.body.gaze_held():
            return False  # an expression moved the camera
        if now - self._last_servo < SERVO_MIN_PERIOD_S:
            return False
        self._last_servo = now
        self._glance = None
        self._face_lost_at = None
        dx, dy = float(face.x), float(face.y)
        if abs(dx) < SERVO_DEAD_BAND and abs(dy) < SERVO_DEAD_BAND:
            self.mode = "face"
            return False
        hfov, vfov = self.body.camera_fov() or DEFAULT_FOV
        base = self.body.current_look()
        # x > 0: the face is on the right of the image → yaw right (negative); y > 0: lower →
        # pitch down (positive, the SDK's "look up" is negative pitch). The pixel offset is an
        # angle through the field of view; the step is a fraction of it from the pose the
        # head is actually at now, so the owner's easing turns the steps into a pursuit.
        yaw = base.yaw
        pitch = base.pitch
        if abs(dx) >= SERVO_DEAD_BAND:
            yaw -= self.servo_gain * math.atan(dx * math.tan(hfov / 2.0))
        if abs(dy) >= SERVO_DEAD_BAND:
            pitch += self.servo_gain * math.atan(dy * math.tan(vfov / 2.0))
        self._yaw = max(-SERVO_YAW_LIMIT, min(SERVO_YAW_LIMIT, yaw))
        self._pitch = max(-SERVO_PITCH_LIMIT, min(SERVO_PITCH_LIMIT, pitch))
        self.servo_steps += 1
        self.mode = "face"
        self.body.look(yaw=self._yaw, pitch=self._pitch, duration_s=SERVO_MOVE_S)
        return True

    def acknowledge(self) -> None:
        """A turn was accepted: a small nod and antenna flick ("I heard you")."""
        if time.monotonic() - self._last_backchannel >= ACK_AFTER_BACKCHANNEL_S:
            self.body.beat("ack")

    def thinking(self) -> None:
        """Waiting for the agent: the thinking state (a tilt, the antennas), after the ack."""
        self.thinking_now = True
        self.mode = "thinking"
        self.body.hold_state("think", mirror=self.rng.random() < 0.5, delay_s=THINK_DELAY_S)

    def end_thinking(self, fade_s: float = THINK_RETURN_S) -> None:
        """The gaze comes back onto the person (the face servo resumes)."""
        if self.thinking_now:
            self.thinking_now = False
            self.body.end_state(fade_s)
            if self.mode == "thinking":
                self.mode = "engaged" if self.engaged else "idle"

    def heard_again(self) -> None:
        """They talk while Bobby thinks: back to the listening pose at once."""
        if self.thinking_now:
            self.end_thinking(0.25)
            self.body.listening()

    def backchannel(self, now: float | None = None) -> bool:
        """A pause while they talk: sometimes a small "mm-hm" nod."""
        now = time.monotonic() if now is None else now
        if (
            not self.engaged
            or self.thinking_now
            or self._spoke
            or now - self._last_backchannel < BACKCHANNEL_GAP_S
        ):
            return False
        self._last_backchannel = now
        if self.rng.random() >= BACKCHANNEL_CHANCE:
            return False
        self.backchannels += 1
        return self.body.beat("mm_hm")

    def speaking(self, on: bool) -> None:
        """Gaze back before the first word; at the end a turn-yield beat and antennas up."""
        self.end_thinking()
        if on:
            self._spoke = True
            self.body.relax()
            return
        if self.engaged:
            self.body.listening()
            if self._spoke:
                self.body.beat("yield")
        self._spoke = False

    def ducked(self, on: bool) -> None:
        """Listening cue during barge-in stage 1."""
        if on:
            self.body.gesture(Gesture.PERK)
