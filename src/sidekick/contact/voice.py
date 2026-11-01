"""sidekick.contact.voice — speaker embeddings with sherpa-onnx (3D-Speaker CAM++ zh/en)

Overview
    Turns a clip into a 192-d speaker embedding and matches it against the enrolled centroids
    (cosine). Enrollment averages several utterances; identification returns the best contact
    above the threshold plus the ranked candidates so the dashboard can show margins. The robot's
    own TTS voice is enrolled as `self` so echo residuals are recognised as the robot. A named
    voice (a contact or `self`) at or above the threshold wins over a closer unnamed person, and
    a voice in the uncertain band below the threshold reports that contact as `near` (block #80):
    the owner, befriended at night, scored 0.41–0.54 the next morning and became a new person
    whose centroid then beat theirs on every sentence.
Design
    Thin wrapper over `SpeakerEmbeddingExtractor` (≈ 15 ms per 2 s clip on this Mac, model loaded
    lazily, downloaded on demand into `.derived_data/models/`). Clips shorter than `min_clip_s`
    are refused for enrollment and scored with reduced confidence. Matching is done here over the
    store's centroids rather than through `SpeakerEmbeddingManager` so the same code serves faces.
Depends on
    sidekick.log, sidekick.storage, sidekick.audio, numpy, sherpa-onnx (lazy).

See Also
--------
    AGENTS.md "Contact and identification", PLAN.md block "[2026-10-26 #18]".

"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from sidekick.audio import AudioClip
from sidekick.log import Log
from sidekick.storage import StorageSession

from .schemas import SELF_ID, Embedding, Identification, Vector, cosine, is_person, normalized

MODEL_NAME = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
MODEL_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/{MODEL_NAME}"


@dataclass(frozen=True, slots=True)
class VoiceConfiguration:
    """Model path and thresholds."""

    model_path: Path
    threshold: float = 0.5
    uncertain: float = 0.35  # a contact this close is `near`: not identified, not a stranger
    min_clip_s: float = 1.0
    enroll_min_clip_s: float = 1.5
    num_threads: int = 1


class VoiceIdentifier:
    """Embed and match voices."""

    def __init__(self, configuration: VoiceConfiguration) -> None:
        self.configuration = configuration
        self._extractor: Any = None
        self._lock = threading.Lock()
        self.model = MODEL_NAME

    @staticmethod
    def ensure_model(models_dir: Path) -> Path:
        """Download the model if needed."""
        return StorageSession.shared.ensure_download(MODEL_URL, models_dir / MODEL_NAME)

    @staticmethod
    def model_present(models_dir: Path) -> bool:
        """Whether the model file exists."""
        return (models_dir / MODEL_NAME).exists()

    def release(self) -> None:
        """Drop the model (the service stopped); the next embedding loads it again."""
        with self._lock:
            self._extractor = None

    def _load(self) -> Any:
        with self._lock:
            if self._extractor is None:
                import sherpa_onnx

                if not self.configuration.model_path.exists():
                    raise FileNotFoundError(
                        f"speaker model missing: {self.configuration.model_path}"
                    )
                started = time.monotonic()
                config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                    model=str(self.configuration.model_path),
                    num_threads=self.configuration.num_threads,
                    debug=False,
                    provider="cpu",
                )
                self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
                Log.info(
                    f"loaded speaker model in {(time.monotonic() - started) * 1000:.0f}ms dim={self._extractor.dim}"
                )
            return self._extractor

    @property
    def dim(self) -> int:
        """Embedding size."""
        return int(self._load().dim)

    def embed(self, clip: AudioClip) -> Vector:
        """Unit-norm embedding of a clip (synchronous, ~15 ms)."""
        extractor = self._load()
        stream = extractor.create_stream()
        stream.accept_waveform(clip.sample_rate, clip.samples.astype(np.float32, copy=False))
        stream.input_finished()
        if not extractor.is_ready(stream):
            raise ValueError("clip too short for an embedding")
        return normalized(np.asarray(extractor.compute(stream), dtype=np.float32))

    def match(
        self, vector: Vector, centroids: list[Embedding], threshold: float | None = None
    ) -> Identification:
        """A named voice at or above the threshold, else an unnamed person, else `near`.

        Unnamed people (`person:n`) are more often fragments of a known voice heard at another
        hour or place in the room than someone new, so a contact (or `self`) that clears the
        threshold wins over a closer one.
        """
        threshold = self.configuration.threshold if threshold is None else threshold
        scored = sorted(
            ((e.contact_id, cosine(vector, e.vector)) for e in centroids), key=lambda item: -item[1]
        )
        named = [item for item in scored if not is_person(item[0])]
        people = [item for item in scored if is_person(item[0])]
        contact_id: str | None = None
        score = scored[0][1] if scored else 0.0
        if named and named[0][1] >= threshold:
            contact_id, score = named[0]
        elif people and people[0][1] >= threshold:
            contact_id, score = people[0]
        contacts = [item for item in named if item[0] != SELF_ID]
        near = (
            contacts[0][0]
            if contact_id is None and contacts and contacts[0][1] >= self.configuration.uncertain
            else None
        )
        return Identification(
            contact_id,
            round(score, 3),
            "voice",
            threshold,
            tuple((c, round(s, 3)) for c, s in scored[:5]),
            near=near,
        )

    def identify(self, clip: AudioClip, centroids: list[Embedding]) -> Identification:
        """Embed + match; too-short clips never match."""
        if clip.duration_s < self.configuration.min_clip_s or not centroids:
            return Identification(None, 0.0, "voice", self.configuration.threshold)
        try:
            vector = self.embed(clip)
        except Exception as exc:
            Log.debug(f"voice embed failed: {exc!r}")
            return Identification(None, 0.0, "voice", self.configuration.threshold)
        return self.match(vector, centroids)
