import numpy as np
import pytest

from sidekick.audio import AudioClip, decode_wav
from sidekick.storage import StorageSession
from sidekick.vad import VADSession, VADSileroConfiguration, VADSileroFactory
from sidekick.vad.silero_sherpa import MODEL_FILE


def model_path():
    path = StorageSession().layout.models_dir / MODEL_FILE
    if not path.exists():
        pytest.skip("silero model not downloaded")
    return path


@pytest.mark.slow
def test_silence_produces_no_segments_and_session_factory_works():
    session = VADSession()
    with pytest.raises(RuntimeError):
        session.create()
    session.setup("primary", VADSileroFactory(VADSileroConfiguration(model_path())))
    detector = session.create()
    assert detector.window_size > 0 and detector.sample_rate == 16000
    detector.feed(AudioClip.silence(2.0).samples)
    detector.flush()
    assert detector.pop_segments() == [] and not detector.is_speech()
    detector.reset()


@pytest.mark.slow
def test_white_noise_is_not_speech():
    detector = VADSileroFactory(VADSileroConfiguration(model_path()))()
    rng = np.random.default_rng(0)
    detector.feed((rng.standard_normal(16000 * 2) * 0.05).astype(np.float32))
    detector.flush()
    assert detector.pop_segments() == []


@pytest.mark.slow
def test_real_speech_yields_one_segment_when_sample_exists():
    sample = StorageSession().layout.cache_dir / "test_speech_zh.wav"
    if not sample.exists():
        pytest.skip("no cached speech sample; produced by the live self-test")
    clip = decode_wav(sample.read_bytes())
    detector = VADSileroFactory(VADSileroConfiguration(model_path(), min_silence_s=0.6))()
    padded = AudioClip.silence(0.5).concat(clip).concat(AudioClip.silence(1.0))
    detector.feed(padded.samples)
    detector.flush()
    segments = detector.pop_segments()
    assert len(segments) >= 1
    assert 0.3 < segments[0].start_s < 0.8
    assert sum(s.clip.duration_s for s in segments) > 0.5 * clip.duration_s
