"""sidekick.vad.schemas — speech segments and the detector protocol

Overview
    A detector consumes 16 kHz float32 frames and emits completed speech segments; `is_speech`
    exposes the live state the engagement machine and barge-in need between segments.
Design
    Detectors are stateful per audio stream, so the session hands out a factory and each
    consumer owns its instance. The protocol is synchronous because it runs on the audio
    thread.
Depends on
    sidekick.audio, numpy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import numpy.typing as npt

from sidekick.audio import AudioClip


@dataclass(frozen=True, slots=True)
class VADSegment:
    """A completed speech segment with its position in the stream."""

    clip: AudioClip
    start_s: float
    end_s: float


class VADBackend(Protocol):
    """One stateful detector."""

    sample_rate: int
    window_size: int

    def feed(self, samples: npt.NDArray[np.float32]) -> None:
        """Push frames (any length)."""
        ...

    def is_speech(self) -> bool:
        """Whether speech is currently detected."""
        ...

    def pop_segments(self) -> list[VADSegment]:
        """Completed segments since the last call."""
        ...

    def flush(self) -> None:
        """Close an in-progress segment."""
        ...

    def reset(self) -> None:
        """Forget everything."""
        ...


class VADFactory(Protocol):
    """Creates detectors."""

    def __call__(self) -> VADBackend:
        """A fresh detector."""
        ...
