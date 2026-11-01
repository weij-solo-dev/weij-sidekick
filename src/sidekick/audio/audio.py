"""sidekick.audio.audio — audio clip type and WAV encode/decode

Overview
    The one audio representation every module agrees on: mono float32 samples in [-1, 1] at a
    known sample rate. Cloud ASR wants a WAV container, the robot speaker wants float32 16 kHz,
    VAD wants float32 frames, so the conversions live here once.
Design
    `AudioClip` is a frozen dataclass around a numpy array. WAV encoding uses the stdlib `wave`
    module with 16-bit PCM, which every vendor accepts. No resampling here yet; callers must
    produce 16 kHz, which is what the robot's mic array and MiniMax both use. This module sits in
    layer 0 and imports nothing from sidekick, so any layer may depend on it.
Depends on
    numpy, stdlib wave/io.

See Also
--------
    AGENTS.md "Module yellow pages" (audio), PLAN.md block "[2026-10-26 #10]".

"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float32]


def float_to_int16(samples: npt.NDArray[np.floating]) -> npt.NDArray[np.int16]:
    """Clip float samples to [-1, 1] and scale to 16-bit PCM."""
    clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16)


def int16_to_float(samples: npt.NDArray[np.int16]) -> FloatArray:
    """Scale 16-bit PCM to float32 in [-1, 1]."""
    return (np.asarray(samples, dtype=np.int16).astype(np.float32) / 32768.0).astype(np.float32)


@dataclass(frozen=True, slots=True)
class AudioClip:
    """Mono float32 audio at `sample_rate` Hz."""

    samples: FloatArray
    sample_rate: int = 16000

    def __post_init__(self) -> None:
        arr = np.asarray(self.samples, dtype=np.float32)
        if arr.ndim == 2:
            arr = arr.mean(axis=1).astype(np.float32)
        if arr.ndim != 1:
            raise ValueError(f"AudioClip expects 1-D samples, got shape {arr.shape}")
        object.__setattr__(self, "samples", np.ascontiguousarray(arr))

    @property
    def duration_s(self) -> float:
        """Length in seconds."""
        return float(len(self.samples)) / float(self.sample_rate)

    @classmethod
    def silence(cls, seconds: float, sample_rate: int = 16000) -> AudioClip:
        """A clip of zeros, handy for probes and tests."""
        return cls(np.zeros(int(seconds * sample_rate), dtype=np.float32), sample_rate)

    @classmethod
    def from_pcm16_bytes(
        cls, data: bytes, sample_rate: int = 16000, channels: int = 1
    ) -> AudioClip:
        """Build a clip from raw little-endian 16-bit PCM bytes."""
        arr = np.frombuffer(data, dtype="<i2")
        if channels > 1:
            arr = arr.reshape(-1, channels).mean(axis=1).astype(np.int16)
        return cls(int16_to_float(arr), sample_rate)

    def to_pcm16_bytes(self) -> bytes:
        """Raw little-endian 16-bit PCM bytes."""
        return float_to_int16(self.samples).astype("<i2").tobytes()

    def to_wav_bytes(self) -> bytes:
        """16-bit PCM WAV container, mono."""
        return encode_wav(self)

    def concat(self, other: AudioClip) -> AudioClip:
        """Append another clip of the same sample rate."""
        if other.sample_rate != self.sample_rate:
            raise ValueError("sample rates differ")
        return AudioClip(np.concatenate([self.samples, other.samples]), self.sample_rate)


def tone(
    seconds: float, freq: float = 440.0, level_dbfs: float = -12.0, sample_rate: int = 16000
) -> FloatArray:
    """A sine with 20 ms fades (speaker tests, the readiness loopback)."""
    n = max(1, int(seconds * sample_rate))
    t = np.arange(n, dtype=np.float32) / sample_rate
    amp = float(10.0 ** (level_dbfs / 20.0))
    out = (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)
    fade = min(n // 2, int(sample_rate * 0.02))
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        out[:fade] *= ramp
        out[-fade:] *= ramp[::-1]
    return out


def encode_wav(clip: AudioClip) -> bytes:
    """Encode a clip as 16-bit PCM WAV."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(clip.sample_rate)
        wav.writeframes(clip.to_pcm16_bytes())
    return buf.getvalue()


def decode_wav(data: bytes) -> AudioClip:
    """Decode a 16-bit PCM WAV (any channel count, mixed to mono)."""
    with wave.open(io.BytesIO(data), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise ValueError(f"only 16-bit WAV is supported, got {wav.getsampwidth() * 8}-bit")
        frames = wav.readframes(wav.getnframes())
        return AudioClip.from_pcm16_bytes(frames, wav.getframerate(), wav.getnchannels())
