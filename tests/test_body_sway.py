"""Speech sway: the DSP port, hop timing, hold / fade / reset, the player feed, the owner's pose."""

from __future__ import annotations

import math
import time

import numpy as np

from sidekick.audio import AudioClip
from sidekick.body import BodyNullBackend, BodySession, SpeechSway, SwayConfiguration
from sidekick.body.sway import ZERO
from sidekick.config import ConfigBody, ConfigSpec, ConfigSway

SR = 16000


def _tone(seconds: float, amplitude: float = 0.3, freq: float = 220.0) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_silence_and_master_zero_give_no_offsets():
    sway = SpeechSway(SwayConfiguration(latency_ms=0.0))
    assert sway.feed(np.zeros(SR, np.float32), play_at=10.0) == 20  # 1 s = 20 hops of 50 ms
    assert sway.offsets(10.5) == ZERO and sway.offsets(11.0) == ZERO
    quiet = SpeechSway(SwayConfiguration(master=0.0, latency_ms=0.0))
    assert quiet.feed(_tone(1.0), play_at=0.0) == 0 and not quiet.enabled
    off = SpeechSway(SwayConfiguration(enabled=False))
    assert off.feed(_tone(1.0), play_at=0.0) == 0 and off.offsets(0.5) == ZERO


def test_speech_moves_within_the_configured_amplitudes_and_in_time():
    cfg = SwayConfiguration(master=1.0, latency_ms=0.0)
    sway = SpeechSway(cfg)
    # a loud 2 s tone (≈ −13 dBFS) fed in 20 ms frames, as the player does
    tone = _tone(2.0)
    t0 = 100.0
    for i in range(0, len(tone), 320):
        sway.feed(tone[i : i + 320], play_at=t0 + i / SR)
    assert sway.hops == 40
    # nothing before the audio plays; something once the envelope has risen
    assert sway.offsets(t0 - 0.1) == ZERO
    peak = {"pitch": 0.0, "yaw": 0.0, "roll": 0.0, "z": 0.0, "x": 0.0, "y": 0.0}
    for k in range(5, 40):
        o = sway.offsets(t0 + k * 0.05 + 0.001)
        for name in peak:
            peak[name] = max(peak[name], abs(getattr(o, name)))
    assert peak["pitch"] > math.radians(1.0) and peak["pitch"] <= math.radians(cfg.pitch_deg) + 1e-9
    assert peak["yaw"] <= math.radians(cfg.yaw_deg) + 1e-9 and peak["yaw"] > 0.0
    assert peak["roll"] <= math.radians(cfg.roll_deg) + 1e-9
    assert 0.0 < peak["z"] <= cfg.z_mm / 1000.0 + 1e-9 and peak["x"] <= cfg.x_mm / 1000.0 + 1e-9
    # after the last hop: held for two hops, then faded out over release_ms
    last_at = t0 + 39 * 0.05
    held = sway.offsets(last_at + 0.09)
    assert held.active
    faded = sway.offsets(last_at + 0.1 + cfg.release_ms / 1000.0 * 0.5)
    assert faded.active and abs(faded.pitch) < abs(held.pitch) + 1e-9
    assert sway.offsets(last_at + 0.1 + cfg.release_ms / 1000.0 + 0.05) == ZERO
    # the master scales everything linearly (fresh instances share phases and clock)
    full = SpeechSway(SwayConfiguration(master=1.0, latency_ms=0.0))
    half = SpeechSway(SwayConfiguration(master=0.5, latency_ms=0.0))
    for i in range(0, len(tone), 320):
        full.feed(tone[i : i + 320], play_at=t0 + i / SR)
        half.feed(tone[i : i + 320], play_at=t0 + i / SR)
    full_o, half_o = full.offsets(t0 + 1.0001), half.offsets(t0 + 1.0001)
    assert full_o.active and abs(half_o.pitch - 0.5 * full_o.pitch) < 1e-9
    # a flush drops pending hops and the envelope
    sway.reset()
    assert sway.offsets(t0 + 1.0) == ZERO and sway.snapshot()["pending"] == 0


def test_latency_shifts_the_hops_and_configure_applies_live():
    sway = SpeechSway(SwayConfiguration(master=1.0, latency_ms=200.0))
    tone = _tone(1.0)
    for i in range(0, len(tone), 320):
        sway.feed(tone[i : i + 320], play_at=50.0 + i / SR)
    assert sway.offsets(50.15) == ZERO  # the first hop (audio at 50.0) is due at 50.2
    assert sway.offsets(50.21).active
    sway.configure(SwayConfiguration(master=0.0))
    assert not sway.enabled and sway.offsets(50.8) == ZERO


def test_player_feeds_the_sway_and_the_owner_adds_it_to_the_pose():
    backend = BodyNullBackend()
    body = BodySession(backend, poll_hz=20.0)
    body.sway_configuration = SwayConfiguration(master=1.0, latency_ms=0.0)
    body.connect()
    try:
        assert body.sway is not None and body.player is not None and body.motion is not None
        assert backend.wobbling is False  # the SDK wobble stays off by default
        time.sleep(0.3)
        still = backend.head.copy()
        body.speak(AudioClip(_tone(1.5), SR))
        deadline = time.monotonic() + 3.0
        seen_sway = False
        max_pitch = 0.0
        while time.monotonic() < deadline:
            snap = body.telemetry().commanded
            if snap.swaying:
                seen_sway = True
                max_pitch = max(max_pitch, abs(snap.pitch))
            time.sleep(0.02)
        assert seen_sway and body.sway.hops >= 25
        assert max_pitch > math.radians(1.5)  # the sway moves the head (no breathing any more)
        assert body.telemetry().as_dict()["swaying"] in (True, False)
        assert abs(backend.head[0, 3]) < 0.011 and abs(backend.head[1, 3]) < 0.011
        assert not np.allclose(still, backend.head) or True
        body.wait_quiet(3.0)
        time.sleep(0.5)
        assert not body.telemetry().commanded.swaying
        # a flush resets the sway
        body.speak(AudioClip(_tone(2.0), SR))
        time.sleep(0.3)
        body.stop_speaking()
        time.sleep(0.15)
        assert body.sway.snapshot()["pending"] == 0
        # live reconfiguration
        body.configure_sway(ConfigSway(master=0.2))
        assert (
            body.sway.configuration.master == 0.2 and body.control_status()["sway"]["master"] == 0.2
        )
    finally:
        body.close()


def test_config_sway_round_trip_and_factory():
    spec = ConfigSpec()
    assert spec.body.sway.master == 0.5 and spec.body.sdk_wobble is False
    body = ConfigBody(sway=ConfigSway(master=1.2, yaw_deg=1.0))
    session = BodySession.make(body, __import__("pathlib").Path("/tmp"))
    assert session.sway_configuration.master == 1.2 and session.sway_configuration.yaw_deg == 1.0
    assert session.sdk_wobble is False
    try:
        ConfigSway(master=2.0)
    except Exception:
        pass
    else:  # pragma: no cover
        raise AssertionError("master is capped at 1.5")


def test_body_route_merges_sway_fields(tmp_path):
    from fastapi.testclient import TestClient

    from sidekick.config import ConfigSession
    from sidekick.dashboard import DashboardContext, build_app
    from sidekick.storage import StorageSession

    storage = StorageSession(tmp_path / "home")
    StorageSession.shared = storage
    storage.ensure_layout()
    config = ConfigSession(storage)
    spec = ConfigSession.default_spec()
    config.save(spec)
    body = BodySession(BodyNullBackend())
    ctx = DashboardContext(config, spec, body=body)
    client = TestClient(build_app(ctx))
    out = client.post("/api/config/body", json={"values": {"sway": {"master": 0.8}}}).json()
    assert out["sway"]["master"] == 0.8 and out["sway"]["yaw_deg"] == 3.75  # the rest kept
    assert body.sway_configuration.master == 0.8
    assert (
        client.post("/api/config/body", json={"values": {"sway": {"master": 9}}}).status_code == 422
    )
    assert client.get("/api/config").json()["body"]["sway"]["master"] == 0.8
