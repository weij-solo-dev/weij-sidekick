"""sidekick.body.expression — Banana's own expressions: keyframed overlays the motion owner plays

Overview
    An expression is a short set of offset curves — head yaw / pitch / roll, x / y / z and the
    two antennas — that the motion owner adds to the pose it composes (look, speech
    sway). Because it is an offset, an expression never takes the gaze away from the person it
    is looking at and composes with speech and with other layers. The library is a flat data
    file, `expression_library.json`, authored for Banana (block #50); the SDK's recorded moves
    and their sound effects are not used any more.
Design
    Channels: `yaw`, `pitch`, `roll` in degrees with the owner's signs (positive yaw turns left,
    positive pitch looks down), `x`, `y`, `z` in millimetres, `ant_r` / `ant_l` in degrees where
    positive swings the antenna outward on either side — about +30 is perked (the listening
    pose), +70 to +100 flung or flattened (surprise, fear), +110 and more hanging down at the
    side (sadness; seen on the Lite's 3D view, 2026-10-28) — and negative would cross it inward
    past vertical, which no entry does; `ant` in the file is both antennas together. `keys` are `[t, value]` pairs interpolated with a monotone cubic
    (Fritsch–Carlson): velocity is continuous, a hold stays flat and nothing overshoots what was
    authored, so the curve is exactly as big as written. `osc` adds enveloped sines for
    laughter, giggles and trembling (`ant_alt` drives the two antennas in opposition); each has
    a 0.1 s fade at both ends and an optional exponential decay. Kinds: `beat` (≤ 2 s,
    conversational), `emotion` (≤ 3 s, a real feeling), `performance` (long; never in the middle
    of a reply) and `state` (thinking, listening: `loop_from` repeats the tail until stopped,
    `then` chains to the next state when the play ends). `ExpressionPlay` samples a spec at an
    instant with an intensity, a speed, a fade in and — on cancel — a fade out; oscillators of a
    looping play run on unwrapped time so a loop never jumps. A play may be `mirror`ed (yaw,
    roll and y negated, the antennas swapped), so one entry serves both sides — thinking looks
    away to either side, chained states keep the side. Values come out in the file's units; the
    owner converts and clamps them to the body's limits.
Depends on
    stdlib only.

See Also
--------
    AGENTS.md "Body", PLAN.md block "[2026-10-28 #50]".

"""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHANNELS = ("yaw", "pitch", "roll", "x", "y", "z", "ant_r", "ant_l")
HEAD_CHANNELS = ("yaw", "pitch", "roll")
KINDS = ("beat", "emotion", "performance", "state")
LIBRARY_PATH = Path(__file__).with_name("expression_library.json")
OSC_EDGE_S = 0.1
_NEGATED = frozenset({"yaw", "roll", "y"})
_MIRROR = {"ant_r": "ant_l", "ant_l": "ant_r"}


def _smoothstep(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


@dataclass(frozen=True, slots=True)
class ExpressionOsc:
    """A sine added to one channel between `start` and `end` (seconds of the expression)."""

    channel: str
    amp: float
    hz: float
    start: float
    end: float
    phase: float = 0.0  # radians
    decay: float = 0.0  # 1/s, exponential from `start`

    def value(self, t: float, open_end: bool = False) -> float:
        """The sine at `t`; `open_end` skips the end fade (a looping state)."""
        if t < self.start or (t > self.end and not open_end):
            return 0.0
        rise = _smoothstep((t - self.start) / OSC_EDGE_S)
        fall = 1.0 if open_end else _smoothstep((self.end - t) / OSC_EDGE_S)
        envelope = rise * fall * (math.exp(-self.decay * (t - self.start)) if self.decay else 1.0)
        return (
            self.amp * envelope * math.sin(2.0 * math.pi * self.hz * (t - self.start) + self.phase)
        )


@dataclass(frozen=True, slots=True)
class ExpressionCurve:
    """One channel's keys with their monotone cubic tangents."""

    times: tuple[float, ...]
    values: tuple[float, ...]
    tangents: tuple[float, ...]

    @classmethod
    def from_keys(cls, keys: list[tuple[float, float]]) -> ExpressionCurve:
        """Fritsch–Carlson tangents: flat at extrema and holds, never overshooting."""
        times = tuple(float(t) for t, _ in keys)
        values = tuple(float(v) for _, v in keys)
        n = len(times)
        slopes = [
            (values[i + 1] - values[i]) / max(1e-6, times[i + 1] - times[i]) for i in range(n - 1)
        ]
        tangents = [0.0] * n
        for i in range(1, n - 1):
            a, b = slopes[i - 1], slopes[i]
            if a * b <= 0.0:
                continue
            ha, hb = times[i] - times[i - 1], times[i + 1] - times[i]
            w1, w2 = 2.0 * hb + ha, hb + 2.0 * ha
            tangents[i] = (w1 + w2) / (w1 / a + w2 / b)
        return cls(times, values, tuple(tangents))

    def value(self, t: float) -> float:
        """Interpolated value; before the first key and after the last the end values hold."""
        times, values = self.times, self.values
        if t <= times[0]:
            return values[0]
        if t >= times[-1]:
            return values[-1]
        lo, hi = 0, len(times) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if times[mid] <= t:
                lo = mid
            else:
                hi = mid
        h = times[hi] - times[lo]
        s = (t - times[lo]) / h
        s2, s3 = s * s, s * s * s
        return (
            (2.0 * s3 - 3.0 * s2 + 1.0) * values[lo]
            + (s3 - 2.0 * s2 + s) * h * self.tangents[lo]
            + (-2.0 * s3 + 3.0 * s2) * values[hi]
            + (s3 - s2) * h * self.tangents[hi]
        )

    @property
    def peak(self) -> float:
        """Largest absolute value."""
        return max(abs(v) for v in self.values)


@dataclass(frozen=True, slots=True)
class ExpressionSpec:
    """One expression of the library."""

    name: str
    kind: str
    description: str
    duration: float
    curves: Mapping[str, ExpressionCurve]
    osc: tuple[ExpressionOsc, ...] = ()
    loop_from: float | None = None
    then: str | None = None
    aliases: tuple[str, ...] = ()

    @property
    def moves_antennas(self) -> bool:
        """Whether either antenna is driven (the touch detector pauses meanwhile)."""
        return any(ch in self.curves for ch in ("ant_r", "ant_l")) or any(
            o.channel in ("ant_r", "ant_l") for o in self.osc
        )

    @property
    def head_peak_deg(self) -> float:
        """A bound on how far the head turns, in degrees (keys plus oscillator amplitudes)."""
        peaks = {ch: self.curves[ch].peak for ch in HEAD_CHANNELS if ch in self.curves}
        for o in self.osc:
            if o.channel in HEAD_CHANNELS:
                peaks[o.channel] = peaks.get(o.channel, 0.0) + abs(o.amp)
        return max(peaks.values(), default=0.0)

    def values(self, t: float, looping: bool = False) -> dict[str, float]:
        """Every driven channel at `t` (seconds of the expression, file units)."""
        out = {ch: curve.value(t) for ch, curve in self.curves.items()}
        for o in self.osc:
            out[o.channel] = out.get(o.channel, 0.0) + o.value(
                t, open_end=looping and o.end >= self.duration
            )
        return out

    def as_dict(self) -> dict[str, Any]:
        """For the dashboard and the agent's tool description."""
        return {
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "duration": round(self.duration, 2),
            "loop": self.loop_from is not None,
            "aliases": list(self.aliases),
            "antennas": self.moves_antennas,
            "head_deg": round(self.head_peak_deg, 1),
        }


class ExpressionPlay:
    """One running expression: the spec sampled at an instant, enveloped and scaled."""

    def __init__(
        self,
        spec: ExpressionSpec,
        started: float,
        intensity: float = 1.0,
        speed: float = 1.0,
        fade_in_s: float = 0.0,
        mirror: bool = False,
    ) -> None:
        self.spec = spec
        self.started = started
        self.intensity = intensity
        self.speed = max(0.1, speed)
        self.fade_in_s = fade_in_s
        self.mirror = mirror
        self.cancel_at: float | None = None
        self.fade_out_s = 0.25

    def cancel(self, now: float, fade_s: float = 0.25) -> None:
        """Fade out from now (a second cancel never extends the fade)."""
        if self.cancel_at is None:
            self.cancel_at = now
            self.fade_out_s = max(0.01, fade_s)

    def elapsed(self, now: float) -> float:
        """Seconds of the expression played so far (speed applied)."""
        return max(0.0, (now - self.started) * self.speed)

    def finished(self, now: float) -> bool:
        """Past its end (a non-looping spec) or past the cancel fade."""
        if self.cancel_at is not None and now >= self.cancel_at + self.fade_out_s:
            return True
        return self.spec.loop_from is None and self.elapsed(now) >= self.spec.duration

    def sample(self, now: float) -> dict[str, float]:
        """Channel values at `now`, in file units (empty once finished)."""
        if self.finished(now):
            return {}
        spec = self.spec
        t = self.elapsed(now)
        looping = spec.loop_from is not None and t > spec.duration
        if looping:
            assert spec.loop_from is not None
            span = max(1e-3, spec.duration - spec.loop_from)
            key_t = spec.loop_from + (t - spec.loop_from) % span
            values = {ch: curve.value(key_t) for ch, curve in spec.curves.items()}
            for o in spec.osc:
                values[o.channel] = values.get(o.channel, 0.0) + o.value(
                    t if o.end >= spec.duration else key_t, open_end=o.end >= spec.duration
                )
        else:
            # a looping spec's open-ended oscillators never fade at the end, even before the wrap
            values = spec.values(t, looping=spec.loop_from is not None)
        gain = self.intensity
        if self.fade_in_s > 0.0:
            gain *= _smoothstep((now - self.started) / self.fade_in_s)
        if self.cancel_at is not None:
            gain *= 1.0 - _smoothstep((now - self.cancel_at) / self.fade_out_s)
        out = {ch: v * gain for ch, v in values.items()}
        if self.mirror:
            out = {_MIRROR.get(ch, ch): -v if ch in _NEGATED else v for ch, v in out.items()}
        return out


def _parse_keys(raw: Any, name: str, channel: str) -> list[tuple[float, float]]:
    if not isinstance(raw, list) or len(raw) < 2:
        raise ValueError(f"{name}.{channel}: keys need at least two [t, value] pairs")
    keys = [(float(t), float(v)) for t, v in raw]
    if any(b[0] <= a[0] for a, b in itertools.pairwise(keys)):
        raise ValueError(f"{name}.{channel}: key times must increase")
    return keys


def parse_expression(name: str, raw: Mapping[str, Any]) -> ExpressionSpec:
    """One library entry; raises `ValueError` with the entry's name on a bad field."""
    kind = str(raw.get("kind", ""))
    if kind not in KINDS:
        raise ValueError(f"{name}: kind must be one of {KINDS}")
    duration = float(raw.get("duration", 0.0))
    if duration <= 0.0:
        raise ValueError(f"{name}: duration must be positive")
    curves: dict[str, ExpressionCurve] = {}
    for channel, keys in dict(raw.get("keys", {})).items():
        parsed = _parse_keys(keys, name, channel)
        targets = ("ant_r", "ant_l") if channel == "ant" else (channel,)
        for target in targets:
            if target not in CHANNELS:
                raise ValueError(f"{name}: unknown channel {channel!r}")
            curves[target] = ExpressionCurve.from_keys(parsed)
    oscs: list[ExpressionOsc] = []
    for entry in raw.get("osc", []):
        channel = str(entry["ch"])
        start = float(entry.get("from", 0.0))
        end = float(entry.get("to", duration))
        phase = math.radians(float(entry.get("phase", 0.0)))
        common = {
            "amp": float(entry["amp"]),
            "hz": float(entry["hz"]),
            "start": start,
            "end": end,
            "decay": float(entry.get("decay", 0.0)),
        }
        if channel == "ant":
            oscs += [
                ExpressionOsc("ant_r", phase=phase, **common),
                ExpressionOsc("ant_l", phase=phase, **common),
            ]
        elif channel == "ant_alt":
            oscs += [
                ExpressionOsc("ant_r", phase=phase, **common),
                ExpressionOsc("ant_l", phase=phase + math.pi, **common),
            ]
        elif channel in CHANNELS:
            oscs.append(ExpressionOsc(channel, phase=phase, **common))
        else:
            raise ValueError(f"{name}: unknown oscillator channel {channel!r}")
        if not 0.0 <= start < end:
            raise ValueError(f"{name}: oscillator span must be 0 ≤ from < to")
    loop_from = raw.get("loop_from")
    if loop_from is not None and not 0.0 <= float(loop_from) < duration:
        raise ValueError(f"{name}: loop_from must lie inside the duration")
    return ExpressionSpec(
        name=name,
        kind=kind,
        description=str(raw.get("description", "")),
        duration=duration,
        curves=curves,
        osc=tuple(oscs),
        loop_from=None if loop_from is None else float(loop_from),
        then=raw.get("then"),
        aliases=tuple(str(a) for a in raw.get("aliases", [])),
    )


def load_library(path: Path = LIBRARY_PATH) -> dict[str, ExpressionSpec]:
    """Every expression in the file, by name; chained states must exist."""
    data = json.loads(path.read_text(encoding="utf-8"))
    library = {name: parse_expression(name, raw) for name, raw in dict(data["expressions"]).items()}
    for spec in library.values():
        if spec.then is not None and spec.then not in library:
            raise ValueError(f"{spec.name}: chains to unknown {spec.then!r}")
    return library
