"""sidekick.body.sway — audio-reactive head sway while the robot speaks (our own, parameterised)

Overview
    The SDK's "head wobbling" moves the head with the speaker audio, but exposes no parameter
    and composes its offsets inside the daemon behind the motion owner's back. This submodule
    is the same idea under our control: the paced player hands every 20 ms frame it pushes to
    `SpeechSway.feed()` together with the instant that frame will be heard, the DSP turns the
    audio into one offset per 50 ms hop, and the motion owner adds the offset for "now" to the
    pose it composes (like the expressions, before the limits). Every number is a
    `SwayConfiguration` field, bound from `ConfigBody.sway` and changeable live.
Design
    A faithful port of the SDK's `SwayRollRT` (itself from the conversation app), measured
    against it in block #41: per hop the RMS in dBFS of the last 20 ms → a VAD with hysteresis
    (on / off thresholds, attack / release in hops) → an envelope that follows a ramp
    (`follow` per hop) → a loudness gain normalised between `loud_low_db` and `loud_high_db`
    (with offset and gamma) × `master` → six free-running sinusoids with random phases, each
    scaled by loudness × envelope. Defaults keep the SDK's frequencies and amplitudes but a
    master of 0.5 (the SDK uses 1.5) and half the yaw, because the yaw is what reads as "shaking
    the head". Hops are timestamped with the audio's playback time plus `latency_ms` (speaker
    sink delay), so `offsets(now)` is in sync with what is heard; after the last hop the offset
    holds briefly and fades over `release_ms`, and a flush resets everything. The VAD also marks
    **phrase onsets** — speech after at least `ONSET_GAP_MS` of quiet — at their playback time;
    the motion owner takes them as they come due and sometimes adds a small beat nod (block
    #50). Thread-safe: the player feeds, the motion thread reads.
Depends on
    numpy only.

See Also
--------
    AGENTS.md "Body", PLAN.md blocks "[2026-10-27 #41]" and "[2026-10-27 #42]".

"""

from __future__ import annotations

import collections
import dataclasses
import math
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

from .schemas import FloatArray


@dataclass(frozen=True, slots=True)
class SwayConfiguration:
    """Every knob of the speech sway (mirrors `ConfigBody.sway`)."""

    enabled: bool = True
    master: float = 0.5  # overall liveliness; the SDK's wobble corresponds to 1.5
    pitch_deg: float = 4.5
    yaw_deg: float = 3.75  # the SDK uses 7.5; halved, the yaw is what looks like head-shaking
    roll_deg: float = 2.25
    x_mm: float = 4.5
    y_mm: float = 3.75
    z_mm: float = 2.25
    pitch_hz: float = 2.2
    yaw_hz: float = 0.6
    roll_hz: float = 1.3
    x_hz: float = 0.35
    y_hz: float = 0.45
    z_hz: float = 0.25
    loud_low_db: float = -46.0
    loud_high_db: float = -18.0
    loud_offset_db: float = 4.0
    loud_gamma: float = 0.9
    vad_on_db: float = -35.0
    vad_off_db: float = -45.0
    vad_attack_ms: float = 40.0
    vad_release_ms: float = 250.0
    attack_ms: float = 50.0
    release_ms: float = 250.0
    follow: float = 0.65
    latency_ms: float = 80.0  # from the player's schedule to the speaker cone
    hop_ms: float = 50.0
    frame_ms: float = 20.0

    @classmethod
    def from_config(cls, config: Any) -> SwayConfiguration:
        """Build from a `ConfigSway`-shaped object (duck-typed: `body` stays below `config`)."""
        if config is None:
            return cls()
        values = {
            f.name: getattr(config, f.name)
            for f in dataclasses.fields(cls)
            if hasattr(config, f.name)
        }
        return cls(**values)


@dataclass(frozen=True, slots=True)
class SwayOffsets:
    """Head offsets for one instant: metres and radians."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0

    @property
    def active(self) -> bool:
        """Whether anything is non-zero."""
        return any(abs(v) > 1e-9 for v in (self.x, self.y, self.z, self.roll, self.pitch, self.yaw))

    def scaled(self, factor: float) -> SwayOffsets:
        """Fade helper."""
        return SwayOffsets(
            self.x * factor,
            self.y * factor,
            self.z * factor,
            self.roll * factor,
            self.pitch * factor,
            self.yaw * factor,
        )


ZERO = SwayOffsets()


ONSET_GAP_MS = 350.0  # quiet before speech that makes a phrase onset


class SpeechSway:
    """Audio in (with its playback time), head offsets out (for any instant)."""

    def __init__(
        self,
        configuration: SwayConfiguration | None = None,
        sample_rate: int = 16000,
        seed: int = 7,
    ) -> None:
        self.configuration = configuration or SwayConfiguration()
        self.sample_rate = int(sample_rate)
        self._lock = threading.Lock()
        rng = np.random.default_rng(seed)
        self._phases = tuple(float(rng.random() * 2.0 * math.pi) for _ in range(6))
        self._carry: FloatArray = np.zeros(0, dtype=np.float32)
        self._carry_at: float | None = None  # playback instant of carry[0]
        self._hops: collections.deque[tuple[float, SwayOffsets]] = collections.deque(maxlen=400)
        self._last: tuple[float, SwayOffsets] | None = None
        self._vad_on = False
        self._vad_above = 0
        self._vad_below = 0
        self._env = 0.0
        self._up = 0
        self._down = 0
        self._t = 0.0
        self._quiet_run = 10**6  # quiet hops before the last loud one (the first phrase counts)
        self._onset = False
        self._onsets: collections.deque[float] = collections.deque(maxlen=64)
        self.hops = 0
        self.last_db = -100.0

    # ------------------------------------------------------------------ config

    def configure(self, configuration: SwayConfiguration) -> None:
        """Replace the knobs live (phases and the oscillator clock carry on)."""
        with self._lock:
            self.configuration = configuration

    @property
    def enabled(self) -> bool:
        """Whether offsets are produced at all."""
        return self.configuration.enabled and self.configuration.master > 0.0

    def reset(self) -> None:
        """A flush: forget queued audio and pending hops, zero the envelope."""
        with self._lock:
            self._carry = np.zeros(0, dtype=np.float32)
            self._carry_at = None
            self._hops.clear()
            self._last = None
            self._vad_on = False
            self._vad_above = self._vad_below = 0
            self._env = 0.0
            self._up = self._down = 0
            self._quiet_run = 10**6
            self._onsets.clear()

    def take_onsets(self, now: float) -> int:
        """How many phrase onsets have come due since the last call (playback time ≤ `now`)."""
        with self._lock:
            due = 0
            while self._onsets and self._onsets[0] <= now:
                self._onsets.popleft()
                due += 1
            return due

    # -------------------------------------------------------------------- feed

    def feed(self, samples: FloatArray, play_at: float) -> int:
        """Analyse a pushed frame; `play_at` is the monotonic instant its first sample plays."""
        if not self.enabled or len(samples) == 0:
            return 0
        cfg = self.configuration
        hop = max(1, int(self.sample_rate * cfg.hop_ms / 1000.0))
        frame = max(1, int(self.sample_rate * cfg.frame_ms / 1000.0))
        made = 0
        with self._lock:
            if self._carry.size == 0 or self._carry_at is None:
                self._carry_at = play_at
                self._carry = np.asarray(samples, dtype=np.float32)
            else:
                self._carry = np.concatenate([self._carry, np.asarray(samples, dtype=np.float32)])
            while self._carry.size >= hop:
                chunk = self._carry[:hop]
                self._carry = self._carry[hop:]
                at = self._carry_at + cfg.latency_ms / 1000.0
                self._carry_at += hop / self.sample_rate
                offsets = self._hop(chunk[-frame:], cfg)
                self._hops.append((at, offsets))
                if self._onset:
                    self._onset = False
                    self._onsets.append(at)
                self.hops += 1
                made += 1
        return made

    def _hop(self, window: FloatArray, cfg: SwayConfiguration) -> SwayOffsets:
        """One 50 ms step of the SDK's DSP."""
        hop_s = cfg.hop_ms / 1000.0
        rms = float(np.sqrt(np.mean(window.astype(np.float32) ** 2, dtype=np.float32) + 1e-12))
        db = 20.0 * math.log10(rms + 1e-12)
        self.last_db = db
        attack_fr = max(1, int(cfg.vad_attack_ms / cfg.hop_ms))
        release_fr = max(1, int(cfg.vad_release_ms / cfg.hop_ms))
        if db >= cfg.vad_on_db:
            if self._vad_below:
                self._quiet_run = self._vad_below  # the quiet that just ended
            self._vad_above += 1
            self._vad_below = 0
            if not self._vad_on and self._vad_above >= attack_fr:
                self._vad_on = True
                self._onset = self._quiet_run * cfg.hop_ms >= ONSET_GAP_MS
        elif db <= cfg.vad_off_db:
            self._vad_below += 1
            self._vad_above = 0
            if self._vad_on and self._vad_below >= release_fr:
                self._vad_on = False
        up_fr = max(1, int(cfg.attack_ms / cfg.hop_ms))
        down_fr = max(1, int(cfg.release_ms / cfg.hop_ms))
        if self._vad_on:
            self._up = min(up_fr, self._up + 1)
            self._down = 0
        else:
            self._down = min(down_fr, self._down + 1)
            self._up = 0
        target = self._up / up_fr if self._vad_on else 1.0 - self._down / down_fr
        self._env = min(1.0, max(0.0, self._env + cfg.follow * (target - self._env)))
        span = max(1e-6, cfg.loud_high_db - cfg.loud_low_db)
        loud = min(1.0, max(0.0, (db + cfg.loud_offset_db - cfg.loud_low_db) / span))
        loud = (loud**cfg.loud_gamma if cfg.loud_gamma != 1.0 else loud) * cfg.master
        gain = loud * self._env
        self._t += hop_s
        if gain <= 0.0:
            return ZERO
        t = self._t
        p = self._phases
        two_pi = 2.0 * math.pi
        return SwayOffsets(
            x=cfg.x_mm / 1000.0 * gain * math.sin(two_pi * cfg.x_hz * t + p[3]),
            y=cfg.y_mm / 1000.0 * gain * math.sin(two_pi * cfg.y_hz * t + p[4]),
            z=cfg.z_mm / 1000.0 * gain * math.sin(two_pi * cfg.z_hz * t + p[5]),
            roll=math.radians(cfg.roll_deg) * gain * math.sin(two_pi * cfg.roll_hz * t + p[2]),
            pitch=math.radians(cfg.pitch_deg) * gain * math.sin(two_pi * cfg.pitch_hz * t + p[0]),
            yaw=math.radians(cfg.yaw_deg) * gain * math.sin(two_pi * cfg.yaw_hz * t + p[1]),
        )

    # ----------------------------------------------------------------- offsets

    def offsets(self, now: float) -> SwayOffsets:
        """The offset to apply at `now` (monotonic): the latest due hop, held then faded."""
        if not self.enabled:
            return ZERO
        cfg = self.configuration
        hop_s = cfg.hop_ms / 1000.0
        with self._lock:
            due: tuple[float, SwayOffsets] | None = None
            while self._hops and self._hops[0][0] <= now:
                due = self._hops.popleft()
            if due is not None:
                self._last = due
            last = self._last
        if last is None:
            return ZERO
        age = now - last[0]
        if age <= 2.0 * hop_s:
            return last[1]
        fade = cfg.release_ms / 1000.0
        remaining = 1.0 - (age - 2.0 * hop_s) / max(1e-3, fade)
        if remaining <= 0.0:
            return ZERO
        return last[1].scaled(remaining)

    def snapshot(self) -> dict[str, Any]:
        """For the dashboard."""
        return {
            "enabled": self.enabled,
            "master": self.configuration.master,
            "hops": self.hops,
            "pending": len(self._hops),
            "last_db": round(self.last_db, 1),
        }
