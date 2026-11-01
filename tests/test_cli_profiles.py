"""Deployment presets (the first config `sidekick startup` writes) and the backup round-trip."""

from __future__ import annotations

import tarfile

import pytest

from sidekick.config import ConfigSession
from sidekick.storage import StorageSession


def test_presets_validate_and_classify():
    for preset in ConfigSession.PRESETS:
        spec = ConfigSession.preset_spec(preset)
        assert spec.robot.name == "Bobby"
    wireless = ConfigSession.preset_spec("wireless")
    assert wireless.body.media_backend == "webrtc" and not wireless.body.manage_daemon
    assert ConfigSession.profile_of(wireless) == "wireless"
    pi = ConfigSession.preset_spec("pi")
    assert pi.perception.poll_hz == 1.0 and pi.slot("vad", "primary").params["threshold"] == 0.4
    assert ConfigSession.profile_of(pi) == "pi"
    assert ConfigSession.profile_of(ConfigSession.preset_spec("lite-mac")) == "lite-mac"
    with pytest.raises(ValueError):
        ConfigSession.preset_spec("toaster")


def test_backup_round_trip(tmp_path):
    home = tmp_path / "home"
    storage = StorageSession(home)
    layout = storage.ensure_layout()
    storage.write_json(
        layout.config_path, {"version": 1, "credentials": {"minimax": {"api_key": "k"}}}
    )
    (home / "dialogue_v1.db").write_bytes(b"sqlite")
    (layout.models_dir / "big.onnx").write_bytes(b"0" * 1000)
    (layout.logs_dir / "sidekick.log").write_text("log")
    (layout.cache_dir / "x").write_text("c")
    (home / "reachy_daemon.pid").write_text("1")
    archive = tmp_path / "b.tar.gz"
    storage.backup(archive)
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
    assert "config.json" in names and "dialogue_v1.db" in names
    assert not any(n.startswith(("models", "logs", "cache")) or n.endswith(".pid") for n in names)
    other = StorageSession(tmp_path / "restored")
    other.ensure_layout()
    assert other.restore(archive) and (tmp_path / "restored" / "config.json").exists()
    assert oct((tmp_path / "restored" / "config.json").stat().st_mode & 0o777) == "0o600"
    with pytest.raises(FileExistsError):
        other.restore(archive)
    assert len(other.restore(archive, force=True)) >= 2
