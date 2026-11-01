"""sidekick.contact.face — face detection (YuNet) and embeddings (SFace) with OpenCV

Overview
    Finds faces in a BGR frame, aligns and embeds them (128-d), and matches against enrolled
    centroids (cosine, OpenCV's reference threshold 0.363). A TV zone (normalised rectangle from
    the onboarding wizard) masks detections that lie inside it.
Design
    `cv2.FaceDetectorYN` + `cv2.FaceRecognizerSF`, both loaded lazily from
    `.derived_data/models/`; the detector is resized to the incoming frame size. Pure functions
    over numpy frames so tests can use synthetic images. Face identification is advisory: the
    engagement machine fuses it with the voice and the DoA.
Depends on
    sidekick.log, sidekick.storage, numpy, opencv-python-headless (lazy).

See Also
--------
    AGENTS.md "Contact and identification", PLAN.md block "[2026-10-26 #18]".

"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from sidekick.log import Log
from sidekick.storage import StorageSession

from .schemas import Embedding, Identification, Vector, cosine, normalized

DETECTOR_NAME = "face_detection_yunet_2023mar.onnx"
RECOGNIZER_NAME = "face_recognition_sface_2021dec.onnx"
DETECTOR_URL = (
    f"https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/{DETECTOR_NAME}"
)
RECOGNIZER_URL = (
    f"https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/{RECOGNIZER_NAME}"
)
Frame = npt.NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class FaceConfiguration:
    """Model paths and thresholds."""

    detector_path: Path
    recognizer_path: Path
    threshold: float = 0.363
    score_threshold: float = 0.8
    tv_zone: tuple[float, float, float, float] | None = None  # x, y, w, h in [0, 1]


@dataclass(frozen=True, slots=True)
class DetectedFace:
    """One detection: box in pixels, five landmarks, confidence, plus the raw row for alignment."""

    x: int
    y: int
    w: int
    h: int
    score: float
    row: npt.NDArray[np.float32]

    @property
    def center(self) -> tuple[float, float]:
        """Box centre in pixels."""
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)


def brighten_frame(
    frame: npt.NDArray[np.uint8], min_mean: float = 60.0, target_mean: float = 100.0
) -> npt.NDArray[np.uint8]:
    """Gamma-lift a dark BGR frame (mean below `min_mean`) so faces stay detectable.

    A frame that is bright enough comes back untouched, so the call is safe to repeat. The
    evening living room measured 19/255 on the Lite's camera, where YuNet finds nothing; the
    lift (gamma ≈ 0.36 there) brings the mean to about `target_mean`.
    """
    mean = float(frame.mean())
    if mean >= min_mean or mean <= 0.5:
        return frame
    import cv2

    gamma = math.log(target_mean / 255.0) / math.log(max(mean, 1.0) / 255.0)
    lut = ((np.arange(256, dtype=np.float64) / 255.0) ** gamma * 255.0).clip(0, 255)
    return np.asarray(cv2.LUT(frame, lut.astype(np.uint8)), dtype=np.uint8)


class FaceIdentifier:
    """Detect, embed and match faces."""

    def __init__(self, configuration: FaceConfiguration) -> None:
        self.configuration = configuration
        self._detector: Any = None
        self._recognizer: Any = None
        self._size: tuple[int, int] | None = None
        self._lock = threading.Lock()
        self.model = RECOGNIZER_NAME

    @staticmethod
    def ensure_models(models_dir: Path) -> tuple[Path, Path]:
        """Download both models if needed."""
        storage = StorageSession.shared
        return storage.ensure_download(
            DETECTOR_URL, models_dir / DETECTOR_NAME
        ), storage.ensure_download(RECOGNIZER_URL, models_dir / RECOGNIZER_NAME)

    @staticmethod
    def models_present(models_dir: Path) -> bool:
        """Whether both files exist."""
        return (models_dir / DETECTOR_NAME).exists() and (models_dir / RECOGNIZER_NAME).exists()

    def release(self) -> None:
        """Drop both models (the service stopped); the next detection loads them again."""
        with self._lock:
            self._detector = None
            self._recognizer = None
            self._size = None

    def _load(self, size: tuple[int, int]) -> tuple[Any, Any]:
        with self._lock:
            import cv2

            if self._detector is None:
                cfg = self.configuration
                if not cfg.detector_path.exists() or not cfg.recognizer_path.exists():
                    raise FileNotFoundError("face models missing")
                self._detector = cv2.FaceDetectorYN.create(
                    str(cfg.detector_path), "", size, cfg.score_threshold, 0.3, 50
                )
                self._recognizer = cv2.FaceRecognizerSF.create(str(cfg.recognizer_path), "")
                self._size = size
                Log.info("loaded face detector + recognizer")
            if self._size != size:
                self._detector.setInputSize(size)
                self._size = size
            return self._detector, self._recognizer

    def detect(self, frame: Frame) -> list[DetectedFace]:
        """Faces in a BGR frame, largest first, TV zone excluded."""
        height, width = frame.shape[:2]
        detector, _ = self._load((int(width), int(height)))
        _, rows = detector.detect(frame)
        faces: list[DetectedFace] = []
        if rows is None:
            return faces
        zone = self.configuration.tv_zone
        for row in rows:
            x, y, w, h = (int(v) for v in row[:4])
            face = DetectedFace(x, y, w, h, float(row[14]), np.asarray(row, dtype=np.float32))
            if zone is not None:
                cx, cy = face.center
                zx, zy, zw, zh = (
                    zone[0] * width,
                    zone[1] * height,
                    zone[2] * width,
                    zone[3] * height,
                )
                if zx <= cx <= zx + zw and zy <= cy <= zy + zh:
                    continue
            faces.append(face)
        faces.sort(key=lambda f: -(f.w * f.h))
        return faces

    def embed(self, frame: Frame, face: DetectedFace) -> Vector:
        """Aligned SFace feature (unit norm)."""
        _, recognizer = self._load((int(frame.shape[1]), int(frame.shape[0])))
        aligned = recognizer.alignCrop(frame, face.row)
        feature = recognizer.feature(aligned)
        return normalized(np.asarray(feature, dtype=np.float32).reshape(-1))

    def match(
        self, vector: Vector, centroids: list[Embedding], threshold: float | None = None
    ) -> Identification:
        """Best contact above the threshold."""
        threshold = self.configuration.threshold if threshold is None else threshold
        scored = sorted(
            ((e.contact_id, cosine(vector, e.vector)) for e in centroids), key=lambda item: -item[1]
        )
        best = scored[0] if scored else (None, 0.0)
        contact_id = best[0] if best[1] >= threshold else None
        return Identification(
            contact_id,
            round(best[1], 3),
            "face",
            threshold,
            tuple((c, round(s, 3)) for c, s in scored[:5]),
        )

    def identify(
        self, frame: Frame, centroids: list[Embedding]
    ) -> tuple[Identification, DetectedFace | None]:
        """Largest face in the frame matched against the contacts."""
        try:
            faces = self.detect(frame)
        except Exception as exc:
            Log.debug(f"face detect failed: {exc!r}")
            return Identification(None, 0.0, "face", self.configuration.threshold), None
        if not faces:
            return Identification(None, 0.0, "face", self.configuration.threshold), None
        if not centroids:
            return Identification(None, 0.0, "face", self.configuration.threshold), faces[0]
        return self.match(self.embed(frame, faces[0]), centroids), faces[0]
