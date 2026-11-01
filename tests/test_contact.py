"""Contacts: store CRUD, centroid folding, cosine matching; slow: real speaker model on bundled clips."""

from __future__ import annotations

import numpy as np
import pytest

from sidekick.audio import decode_wav
from sidekick.contact import (
    SELF_ID,
    Contact,
    ContactSession,
    ContactStore,
    Embedding,
    VoiceConfiguration,
    VoiceIdentifier,
    cosine,
    slugify,
)
from sidekick.storage import StorageSession


def test_slugify_and_store(tmp_path):
    assert (
        slugify("Dad Wong") == "dad_wong"
        and slugify("爸爸") == "爸爸"
        and slugify("  ") == "contact"
    )
    store = ContactStore(tmp_path / "contact_v1.db")
    dad = store.upsert(
        Contact("dad", "爸爸", ("daddy", "老爸"), "likes milk tea", "yue", True, {"telegram": "42"})
    )
    store.upsert(Contact("mum", "媽媽", language="yue"))
    assert (
        store.get("dad") == dad
        and store.by_name("老爸").id == "dad"
        and store.by_name("Daddy").id == "dad"
    )
    assert (
        store.by_remote_id("telegram", "42").id == "dad"
        and store.by_remote_id("wechat", "x") is None
    )
    assert [c.id for c in store.list_contacts()] == ["dad", "mum"]  # owner first
    v1 = np.array([1.0, 0.0, 0.0], np.float32)
    v2 = np.array([0.0, 1.0, 0.0], np.float32)
    e = store.add_sample("dad", "voice", "m", v1)
    assert e.samples == 1 and np.allclose(e.vector, v1)
    e = store.add_sample("dad", "voice", "m", v2)
    assert e.samples == 2 and np.allclose(e.vector, np.array([1, 1, 0], np.float32) / np.sqrt(2))
    assert len(store.embeddings("voice", "m")) == 1 and store.embeddings("voice", "other") == []
    store.set_embedding("mum", "voice", "m", v2, 3)
    assert store.embeddings("voice", "m", "mum")[0].samples == 3
    summary = {s["id"]: s for s in store.summary()}
    assert summary["dad"]["voice_samples"] == 2 and summary["mum"]["face_samples"] == 0
    assert (
        store.clear_embeddings("dad", "voice") == 1
        and store.delete("mum")
        and store.get("mum") is None
    )


def test_matching_math(tmp_path):
    ident = VoiceIdentifier(VoiceConfiguration(tmp_path / "missing.onnx", threshold=0.5))
    a = np.array([1.0, 0.0], np.float32)
    b = np.array([0.0, 1.0], np.float32)
    centroids = [Embedding("dad", "voice", "m", a), Embedding("mum", "voice", "m", b)]
    close = np.array([0.9, 0.1], np.float32)
    result = ident.match(close, centroids)
    assert (
        result.contact_id == "dad"
        and result.score > 0.9
        and result.candidates[0][0] == "dad"
        and result.known
    )
    far = np.array([0.6, 0.6], np.float32)
    assert ident.match(far, centroids, threshold=0.8).contact_id is None
    assert abs(cosine(a, b)) < 1e-9 and cosine(a, np.zeros(2, np.float32)) == 0.0


def test_session_contacts_and_remote_resolution(tmp_path):
    StorageSession.shared = StorageSession(tmp_path / "home")
    session = ContactSession()
    session.setup(tmp_path / "contact_v1.db", tmp_path / "models")
    dad = session.create("爸爸", aliases=["daddy"], language="yue", is_owner=True)
    assert session.get(dad.id).is_owner and session.owner().id == dad.id
    assert session.bind_remote(dad.id, "telegram", "tg:42").remote_ids == {"telegram": "42"}
    assert (
        session.resolve_speaker("tg:42") == dad.id
        and session.resolve_speaker("tg:7") == "tg:7"
        and session.resolve_speaker("dad") == "dad"
    )
    assert (
        session.display_name(dad.id) == "爸爸 (owner)"
        and session.display_name("guest:1") == "guest:1"
    )
    assert session.new_guest() == "guest:1" and session.new_guest() == "guest:2"
    assert not session.self_enrolled() and session.snapshot()["contacts"][0]["name"] == "爸爸"
    # no models: identification degrades to unknown instead of raising
    from sidekick.audio import AudioClip

    assert session.identify_voice(AudioClip.silence(2.0)).contact_id is None
    assert session.identify_face(np.zeros((120, 160, 3), np.uint8))[0].contact_id is None


@pytest.mark.slow
def test_speaker_model_separates_bundled_clips():
    """Uses the KWS model's bundled LibriSpeech / WenetSpeech clips: same clip → high score."""
    storage = StorageSession()
    StorageSession.shared = storage
    models = storage.ensure_layout().models_dir
    model_path = VoiceIdentifier.ensure_model(models)
    from sidekick.asr import ASRKeywordBackend

    kws_dir = ASRKeywordBackend.ensure_model(models) / "test_wavs"
    ident = VoiceIdentifier(VoiceConfiguration(model_path, threshold=0.5))
    en0 = decode_wav((kws_dir / "en_0.wav").read_bytes())
    zh0 = decode_wav((kws_dir / "zh_0.wav").read_bytes())
    e_en, e_zh = ident.embed(en0), ident.embed(zh0)
    assert e_en.shape == (192,) and abs(float(np.linalg.norm(e_en)) - 1.0) < 1e-3
    centroids = [
        Embedding("en", "voice", ident.model, e_en),
        Embedding("zh", "voice", ident.model, e_zh),
    ]
    # the same clip matches itself far better than a different speaker's clip
    assert (
        ident.identify(en0, centroids).contact_id == "en"
        and ident.identify(zh0, centroids).contact_id == "zh"
    )
    assert cosine(e_en, e_zh) < 0.5
    # a half-second slice is too short to identify
    from sidekick.audio import AudioClip

    assert ident.identify(AudioClip(en0.samples[:8000], 16000), centroids).contact_id is None
    session = ContactSession()
    session.setup(storage.layout.home / "contact_test_v1.db", models)
    try:
        assert session.enroll_self([en0, AudioClip(en0.samples[: 16000 * 2], 16000)]) == 2
        assert session.self_enrolled() and session.identify_voice(en0).is_self
        assert session.get(SELF_ID) is not None
    finally:
        (storage.layout.home / "contact_test_v1.db").unlink(missing_ok=True)
