"""Keyword spotting backend on the model's own English test clip (downloads the model once)."""

from __future__ import annotations

import pytest

from sidekick.asr import ASRKeywordBackend, ASRKeywordConfiguration, ASRSession
from sidekick.audio import AudioClip, decode_wav
from sidekick.storage import StorageSession


@pytest.mark.slow
async def test_keyword_spotting_on_bundled_clip():
    storage = StorageSession()
    StorageSession.shared = storage
    models = storage.ensure_layout().models_dir
    model_dir = ASRKeywordBackend.ensure_model(models)
    backend = ASRKeywordBackend(
        ASRKeywordConfiguration(
            model_dir,
            keywords=(
                "light up @light_up",
                "L AH1 V L IY0 CH AY1 L D @lovely_child",
                "b ǎo b ǐ @寶比",
            ),
        )
    )
    lines = backend.keyword_lines()
    assert lines[0] == "L AY1 T AH1 P @light_up"  # resolved through the lexicon
    clip = decode_wav((model_dir / "test_wavs" / "en_0.wav").read_bytes())
    result = await backend.transcribe(clip)
    assert result.success and "light_up" in (result.text or "")
    quiet = await backend.transcribe(AudioClip.silence(1.0))
    assert quiet.success and quiet.text == ""
    session = ASRSession()
    session.setup("kws", backend)
    assert (await session.transcribe("kws", clip)).text
