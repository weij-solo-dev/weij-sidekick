import numpy as np

from sidekick.audio import AudioClip, decode_wav, encode_wav, float_to_int16, int16_to_float


def test_wav_round_trip_preserves_samples_within_quantization():
    t = np.linspace(0, 1, 16000, endpoint=False, dtype=np.float32)
    clip = AudioClip(0.5 * np.sin(2 * np.pi * 440 * t), 16000)
    decoded = decode_wav(encode_wav(clip))
    assert decoded.sample_rate == 16000
    assert len(decoded.samples) == 16000
    assert np.max(np.abs(decoded.samples - clip.samples)) < 1e-4
    assert abs(decoded.duration_s - 1.0) < 1e-9


def test_stereo_input_is_mixed_to_mono():
    stereo = np.zeros((100, 2), dtype=np.float32)
    stereo[:, 0] = 1.0
    clip = AudioClip(stereo, 16000)
    assert clip.samples.shape == (100,)
    assert abs(float(clip.samples[0]) - 0.5) < 1e-6


def test_int16_conversions_clip_and_scale():
    out = float_to_int16(np.array([2.0, -2.0, 0.0], dtype=np.float32))
    assert list(out) == [32767, -32767, 0]
    back = int16_to_float(np.array([32767, -32768], dtype=np.int16))
    assert back[0] > 0.99 and back[1] == -1.0


def test_silence_and_concat():
    a = AudioClip.silence(0.5)
    b = AudioClip.silence(0.25)
    assert abs(a.concat(b).duration_s - 0.75) < 1e-9
