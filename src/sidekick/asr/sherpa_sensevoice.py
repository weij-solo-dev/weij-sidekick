"""sidekick.asr.sherpa_sensevoice — local SenseVoice recognizer via sherpa-onnx

Overview
    On-host ASR with one model for Cantonese, Mandarin, English, Japanese and Korean. It has two
    jobs: transcribe every IDLE speech segment locally so the wake name "Banana" can be spotted
    without any cloud call (invariant 17), and serve as the fallback / shadow transcript next to
    the cloud ASR for quality comparison on the dashboard.
Design
    The recognizer is built lazily on first use and guarded by a lock; decoding runs in a worker
    thread through `asyncio.to_thread` because sherpa-onnx is synchronous. The language is fixed
    at construction — per-call `language` is recorded in the result but does not rebuild the
    model, which costs ~250 MB each. The local preset takes it from the household language:
    `zh` for a Mandarin household, `auto` otherwise. In `auto` some Mandarin sentences were
    decoded as Cantonese (「把那个拿来」 → 「爸妈佢妈嚟」, block #94); the wake name, an English
    word, is written much the same either way. The model archive is fetched from the
    sherpa-onnx GitHub release into `.derived_data/models/` by `ensure_model()`.
Depends on
    sidekick.audio, sidekick.log, sidekick.storage, sherpa-onnx, numpy.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from sidekick.audio import AudioClip
from sidekick.log import Log
from sidekick.storage import StorageSession

from .schemas import ASRResult

API_NAME = "sherpa_sensevoice"
MODEL_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"
MODEL_URL = (
    f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{MODEL_NAME}.tar.bz2"
)


@dataclass(frozen=True, slots=True)
class ASRSenseVoiceConfiguration:
    """Where the model lives and how to decode."""

    model_dir: Path
    language: str = "auto"
    use_itn: bool = True
    num_threads: int = 2
    provider: str = "local"


class ASRSenseVoiceBackend:
    """Offline SenseVoice recognizer."""

    def __init__(self, configuration: ASRSenseVoiceConfiguration) -> None:
        self.configuration = configuration
        self._recognizer: Any = None
        self._lock = threading.Lock()

    @staticmethod
    def ensure_model(models_dir: Path) -> Path:
        """Download and extract the model archive if needed; returns the model directory."""
        return StorageSession.shared.ensure_download(
            MODEL_URL, models_dir / f"{MODEL_NAME}.tar.bz2", extract=True
        )

    @staticmethod
    def model_present(models_dir: Path) -> bool:
        """Whether the model files are already on disk."""
        directory = models_dir / MODEL_NAME
        return (directory / "model.int8.onnx").exists() and (directory / "tokens.txt").exists()

    def _load(self) -> Any:
        with self._lock:
            if self._recognizer is None:
                import sherpa_onnx

                cfg = self.configuration
                model = cfg.model_dir / "model.int8.onnx"
                tokens = cfg.model_dir / "tokens.txt"
                if not model.exists() or not tokens.exists():
                    raise FileNotFoundError(f"SenseVoice model missing under {cfg.model_dir}")
                started = time.monotonic()
                self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=str(model),
                    tokens=str(tokens),
                    num_threads=cfg.num_threads,
                    language=cfg.language if cfg.language != "auto" else "",
                    use_itn=cfg.use_itn,
                )
                Log.info(f"loaded SenseVoice in {(time.monotonic() - started) * 1000:.0f}ms")
            return self._recognizer

    def preload(self) -> None:
        """Load the model now (the service's start), not on the first utterance."""
        self._load()

    @property
    def loaded(self) -> bool:
        """Whether the model is in memory."""
        return self._recognizer is not None

    def close(self) -> None:
        """Drop the model (the slot was replaced or the service stopped)."""
        with self._lock:
            self._recognizer = None

    def _decode(self, clip: AudioClip) -> tuple[str, str | None]:
        recognizer = self._load()
        with self._lock:
            stream = recognizer.create_stream()
            stream.accept_waveform(
                clip.sample_rate, np.ascontiguousarray(clip.samples, dtype=np.float32)
            )
            recognizer.decode_stream(stream)
            result = stream.result
        text = str(getattr(result, "text", "") or "").strip()
        lang = getattr(result, "lang", None)
        if isinstance(lang, str):
            lang = lang.strip("<|>") or None
        return text, lang

    async def transcribe(self, clip: AudioClip, language: str | None = None) -> ASRResult:
        """Decode in a worker thread; never raises for model errors."""
        cfg = self.configuration
        started = time.monotonic()
        Log.info(f"decode: audio={clip.duration_s:.2f}s language={language or cfg.language}")
        try:
            text, detected = await asyncio.to_thread(self._decode, clip)
        except Exception as exc:
            Log.error(f"decode failed: {exc!r}")
            return ASRResult(
                False,
                None,
                cfg.provider,
                API_NAME,
                MODEL_NAME,
                "<local>",
                language=language,
                error_message=repr(exc),
                latency_ms=_elapsed(started),
            )
        latency = _elapsed(started)
        Log.info(f"ok: chars={len(text)} lang={detected} latency={latency:.0f}ms")
        return ASRResult(
            True,
            text,
            cfg.provider,
            API_NAME,
            MODEL_NAME,
            "<local>",
            language=detected or language,
            duration_s=clip.duration_s,
            status_code=None,
            latency_ms=latency,
        )


def _elapsed(started: float) -> float:
    return (time.monotonic() - started) * 1000.0
