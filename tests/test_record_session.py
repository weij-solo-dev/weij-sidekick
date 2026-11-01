"""Recorder on the null body: chunks roll, tracks and telemetry land, pruning and the disk floor."""

from __future__ import annotations

import json
import time
import wave
from pathlib import Path

import numpy as np

from sidekick.body import BodyNullBackend, BodySession
from sidekick.config import ConfigSession
from sidekick.record import RecordSession, RecordSettings
from sidekick.record.chunks import list_chunks, prune
from sidekick.record.video import encoder_name


def _settings(root: Path, **overrides) -> RecordSettings:
    base: dict[str, object] = {
        "root": root,
        "chunk_s": 1.2,
        "retention_hours": 24.0,
        "min_free_gb": 0.0,
        "width": 320,
        "height": 180,
        "fps": 5.0,
        "bitrate_kbps": 200,
        "telemetry_hz": 10.0,
    }
    base.update(overrides)
    return RecordSettings(**base)  # type: ignore[arg-type]


def test_chunks_roll_with_video_audio_and_telemetry(tmp_path):
    backend = BodyNullBackend()
    body = BodySession(backend)
    body.connect()
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    frame[:, :320] = (0, 255, 0)
    backend.set_frame(frame)
    extra_calls = {"n": 0}

    def extra():
        extra_calls["n"] += 1
        return {"state": "engaged", "who": "owner"}

    record = RecordSession()
    record.setup(_settings(tmp_path / "rec"), body, extra=extra)
    try:
        record.start()
        deadline = time.time() + 6.0
        while time.time() < deadline and len(list_chunks(tmp_path / "rec")) < 2:
            backend.feed_audio(np.full(1600, 0.3, dtype=np.float32))
            body.speak(np.full(800, 0.5, dtype=np.float32))
            time.sleep(0.1)
        assert record.state == "recording"
    finally:
        record.stop()
    chunks = list_chunks(tmp_path / "rec")
    assert len(chunks) >= 2 and all(not c.open for c in chunks)
    first = chunks[0]
    assert first.telemetry_rows >= 5 and first.mic_samples > 0 and first.speaker_samples > 0
    assert extra_calls["n"] >= 5
    rows = record.telemetry(first.id)
    assert rows and rows[0]["x"]["state"] == "engaged" and "head" in rows[0]
    with wave.open(str(first.path / "mic.wav")) as w:
        assert w.getframerate() == 16000 and w.getnframes() == first.mic_samples
    with wave.open(str(first.path / "speaker.wav")) as w:
        # silence-padded to the chunk duration: within a tick of the mic track
        assert abs(w.getnframes() - 16000 * first.duration_s) < 16000 * 0.6
    descriptor = json.loads((first.path / "chunk.json").read_text())
    assert descriptor["id"] == first.id and descriptor["open"] is False
    if encoder_name():
        assert first.video == encoder_name() and first.frames >= 3
        assert (first.path / "video.mp4").stat().st_size > 500
    else:
        assert any("video" in e for e in first.errors)
    assert record.chunk(first.id) is not None and record.chunk("../x") is None
    assert record.chunk_file(first.id, "mic.wav") == first.path / "mic.wav"
    assert record.chunk_file(first.id, "chunk.json") is None
    status = record.status()
    assert status.chunks == len(chunks) and status.size_gb > 0 and status.state == "stopped"
    assert record.days() == [first.id.split("/")[0]]
    body.close()


def test_prune_by_retention_and_disk_floor(tmp_path):
    root = tmp_path / "rec"
    now = time.time()
    for age_h in (30.0, 2.0, 0.1):
        start = now - age_h * 3600
        path = root / time.strftime("%Y-%m-%d/%H-%M-%S", time.localtime(start))
        path.mkdir(parents=True)
        (path / "chunk.json").write_text(
            json.dumps(
                {
                    "id": f"{path.parent.name}/{path.name}",
                    "start_ts": start,
                    "end_ts": start + 300,
                    "open": False,
                }
            )
        )
        (path / "mic.wav").write_bytes(b"x" * 1000)
    assert len(list_chunks(root)) == 3
    removed = prune(root, retention_hours=24.0, min_free_gb=0.0, now=now)
    assert len(removed) == 1 and len(list_chunks(root)) == 2
    # an impossible floor removes the oldest closed chunks one by one
    removed = prune(root, retention_hours=24.0, min_free_gb=1e9, now=now)
    assert len(removed) == 2 and list_chunks(root) == []
    record = RecordSession()
    body = BodySession(BodyNullBackend())
    body.connect()
    record.setup(_settings(root, min_free_gb=1e9), body)
    record.start()
    time.sleep(0.5)
    assert record.state == "paused"
    record.stop()
    body.close()


def test_settings_from_config_and_presets(tmp_path):
    spec = ConfigSession.default_spec()
    settings = RecordSettings.from_config(spec.recording, tmp_path / "recordings")
    assert settings.root == tmp_path / "recordings" and settings.chunk_s == 300.0
    assert settings.width == 1280 and settings.audio_codec == "wav"
    pi = ConfigSession.preset_spec("pi")
    assert pi.recording.audio_codec == "flac" and pi.recording.width == 960
    spec.recording.root = "~/rec"
    assert RecordSettings.from_config(spec.recording, tmp_path).root == Path("~/rec").expanduser()


def test_ring_status_and_prune_without_a_running_recorder(tmp_path):
    """The ring's status and pruning (once `sidekick record status | prune`; the Record page now)
    work on a recorder that is set up but not started — the service stopped (block #87)."""
    from sidekick.config import ConfigSession

    spec = ConfigSession.default_spec()
    session = RecordSession()
    session.setup(RecordSettings.from_config(spec.recording, tmp_path / "rec"), None)
    status = session.status()
    assert status.chunks == 0 and status.retention_hours == 24
    assert session.prune() == []
    assert session.check()[0]["level"] == "warn"  # enabled but not recording


def test_read_mic_slices_closed_and_open_chunks(tmp_path):
    import io

    from sidekick.record import RecordChunk
    from sidekick.record.tracks import WavTrack

    root = tmp_path / "rec"
    settings = RecordSettings(root=root)
    session = RecordSession()
    session.setup(settings, None)
    start = time.time() - 120.0
    day = time.strftime("%Y-%m-%d", time.localtime(start))
    moment = time.strftime("%H-%M-%S", time.localtime(start))
    path = root / day / moment
    path.mkdir(parents=True)
    rate = settings.sample_rate
    track = WavTrack(path / "mic.wav", rate)
    ramp = (np.arange(rate * 10) / (rate * 10)).astype(np.float32)  # 10 s, 0 → 1
    track.write(ramp)
    track.close()
    chunk = RecordChunk(id=f"{day}/{moment}", path=path, start_ts=start, end_ts=start + 10.0)
    (path / "chunk.json").write_text(json.dumps(chunk.as_dict()))
    clip = session.read_mic(start + 2.0, start + 3.0)
    assert clip is not None and abs(clip.duration_s - 1.0) < 0.01
    assert 0.19 < float(clip.samples[0]) < 0.21 and 0.29 < float(clip.samples[-1]) < 0.31
    # a chunk left open (zero-length header, as after a crash or while recording) reads raw
    header = io.BytesIO()
    with wave.open(header, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
    raw = header.getvalue()[:44] + (ramp * 32767).astype("<i2").tobytes()
    (path / "mic.wav").write_bytes(raw)
    open_chunk = RecordChunk(id=chunk.id, path=path, start_ts=start, open=True)
    (path / "chunk.json").write_text(json.dumps(open_chunk.as_dict()))
    clip2 = session.read_mic(start + 9.0, start + 9.5)
    assert clip2 is not None and abs(clip2.duration_s - 0.5) < 0.02
    assert 0.89 < float(clip2.samples[0]) < 0.91
    assert session.read_mic(start + 200.0, start + 201.0) is None
