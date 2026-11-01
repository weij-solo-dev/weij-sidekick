"""sidekick.vad.silero_sherpa — Silero VAD through sherpa-onnx

Overview
    The default detector: Silero VAD (ONNX) wrapped by sherpa-onnx's `VoiceActivityDetector`,
    which does the windowing, hangover and segment bookkeeping. Thresholds come from config so
    the listening monitor can be tuned without code changes.
Design
    `feed` buffers arbitrary-length input and pushes exact `window_size` frames; completed
    segments are read from the detector's queue. The 2 MB model is fetched from the sherpa-onnx
    release into `.derived_data/models/` by `ensure_model()`. A factory produces one detector per
    audio stream.
Depends on
    sidekick.audio, sidekick.log, sidekick.storage, sherpa-onnx, numpy.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from sidekick.audio import AudioClip
from sidekick.log import Log
from sidekick.storage import StorageSession

from .schemas import VADSegment

API_NAME = "silero_sherpa"
MODEL_FILE = "silero_vad.onnx"
MODEL_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{MODEL_FILE}"


@dataclass(frozen=True, slots=True)
class VADSileroConfiguration:
    """Model path and detection thresholds."""

    model_path: Path
    threshold: float = 0.5
    min_silence_s: float = 0.5
    min_speech_s: float = 0.25
    max_speech_s: float = 20.0
    sample_rate: int = 16000
    buffer_s: float = 60.0
    provider: str = "local"


class VADSileroBackend:
    """One stateful Silero detector."""

    def __init__(self, configuration: VADSileroConfiguration) -> None:
        import sherpa_onnx

        cfg = configuration
        if not cfg.model_path.exists():
            raise FileNotFoundError(f"silero model missing: {cfg.model_path}")
        model_config = sherpa_onnx.VadModelConfig()
        model_config.silero_vad.model = str(cfg.model_path)
        model_config.silero_vad.threshold = cfg.threshold
        model_config.silero_vad.min_silence_duration = cfg.min_silence_s
        model_config.silero_vad.min_speech_duration = cfg.min_speech_s
        model_config.silero_vad.max_speech_duration = cfg.max_speech_s
        model_config.sample_rate = cfg.sample_rate
        self.configuration = cfg
        self.sample_rate = cfg.sample_rate
        self.window_size = int(model_config.silero_vad.window_size)
        self._vad: Any = sherpa_onnx.VoiceActivityDetector(
            model_config, buffer_size_in_seconds=cfg.buffer_s
        )
        self._pending = np.empty(0, dtype=np.float32)

    @staticmethod
    def ensure_model(models_dir: Path) -> Path:
        """Download the model if needed; returns its path."""
        return StorageSession.shared.ensure_download(MODEL_URL, models_dir / MODEL_FILE)

    def feed(self, samples: npt.NDArray[np.float32]) -> None:
        """Push frames; whole windows go to the detector, the remainder waits."""
        data = np.concatenate([self._pending, np.asarray(samples, dtype=np.float32).ravel()])
        offset = 0
        while offset + self.window_size <= len(data):
            self._vad.accept_waveform(data[offset : offset + self.window_size])
            offset += self.window_size
        self._pending = data[offset:]

    def is_speech(self) -> bool:
        """Live speech state."""
        return bool(self._vad.is_speech_detected())

    def pop_segments(self) -> list[VADSegment]:
        """Drain completed segments."""
        segments: list[VADSegment] = []
        while not self._vad.empty():
            front = self._vad.front
            samples = np.asarray(front.samples, dtype=np.float32)
            start_s = float(front.start) / self.sample_rate
            segments.append(
                VADSegment(
                    AudioClip(samples, self.sample_rate),
                    start_s,
                    start_s + len(samples) / self.sample_rate,
                )
            )
            self._vad.pop()
        if segments:
            Log.debug(
                f"{len(segments)} segment(s), last {segments[-1].start_s:.2f}-{segments[-1].end_s:.2f}s"
            )
        return segments

    def flush(self) -> None:
        """Close an in-progress segment."""
        self._vad.flush()

    def reset(self) -> None:
        """Forget everything."""
        self._vad.reset()
        self._pending = np.empty(0, dtype=np.float32)


class VADSileroFactory:
    """Creates `VADSileroBackend`s for one configuration."""

    def __init__(self, configuration: VADSileroConfiguration) -> None:
        self.configuration = configuration

    def __call__(self) -> VADSileroBackend:
        """A fresh detector."""
        return VADSileroBackend(self.configuration)
