"""sidekick.record.tracks — audio track writers for one chunk: WAV (stdlib) or FLAC (GStreamer)

Overview
    An `AudioTrack` takes float32 mono chunks and appends them to one file: `WavTrack` writes
    PCM16 with the stdlib `wave` module (the default, browser-native, ~2.7 GB per 24 h at 16 kHz),
    `FlacTrack` pushes the same PCM16 through `appsrc ! audioconvert ! flacenc` for hosts with a
    small disk (Raspberry Pi). `open_track()` picks by codec and falls back to WAV when GStreamer
    is missing. `pad()` appends silence so the speaker track stays aligned with wall-clock time
    while nothing is playing.
Design
    Both writers count samples so the recorder can align tracks and the chunk descriptor can
    report durations. WAV headers are finalised on `close()`; a crash leaves a file with a stale
    header that `wave` still reads up to the stated length (the recorder rewrites the header for
    a chunk it finds open on the next start). FLAC is closed with EOS like the video writer.
Depends on
    sidekick.audio (PCM conversion), numpy, gi/GStreamer (lazy, FLAC only).

See Also
--------
    AGENTS.md "Recording", PLAN.md block "[2026-10-26 #25]".

"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from sidekick.audio import float_to_int16

from .video import gstreamer

FloatArray = npt.NDArray[np.float32]


class AudioTrack(Protocol):
    """What the recorder needs from a track."""

    path: Path
    samples: int
    sample_rate: int

    def write(self, samples: FloatArray) -> None:
        """Append mono float32 samples."""
        ...

    def pad(self, count: int) -> None:
        """Append `count` samples of silence."""
        ...

    def close(self) -> None:
        """Finalise the file."""
        ...


class WavTrack:
    """PCM16 mono WAV through the stdlib."""

    def __init__(self, path: Path, sample_rate: int = 16000) -> None:
        self.path = path
        self.sample_rate = sample_rate
        self.samples = 0
        self._wave = wave.open(str(path), "wb")
        self._wave.setnchannels(1)
        self._wave.setsampwidth(2)
        self._wave.setframerate(sample_rate)

    def write(self, samples: FloatArray) -> None:
        """Append samples."""
        if len(samples) == 0:
            return
        self._wave.writeframes(float_to_int16(samples).tobytes())
        self.samples += len(samples)

    def pad(self, count: int) -> None:
        """Append silence."""
        if count > 0:
            self._wave.writeframes(bytes(2 * count))
            self.samples += count

    def close(self) -> None:
        """Finalise the header."""
        self._wave.close()


class FlacTrack:
    """FLAC through GStreamer (`appsrc ! audioconvert ! flacenc ! filesink`)."""

    def __init__(self, path: Path, sample_rate: int = 16000) -> None:
        self.path = path
        self.sample_rate = sample_rate
        self.samples = 0
        self.error: str | None = None
        gst = gstreamer()
        if gst is None or gst.ElementFactory.find("flacenc") is None:
            raise RuntimeError("flacenc unavailable")
        self._gst = gst
        self._pipeline: Any = gst.parse_launch(
            "appsrc name=src is-live=false format=time block=true "
            f"caps=audio/x-raw,format=S16LE,rate={sample_rate},channels=1,layout=interleaved "
            f'! audioconvert ! flacenc ! filesink location="{path}"'
        )
        self._src = self._pipeline.get_by_name("src")
        self._pipeline.set_state(gst.State.PLAYING)

    def _push(self, data: bytes, count: int) -> None:
        buffer = self._gst.Buffer.new_wrapped(data)
        buffer.pts = int(self.samples * self._gst.SECOND / self.sample_rate)
        buffer.duration = int(count * self._gst.SECOND / self.sample_rate)
        if self._src.emit("push-buffer", buffer) != self._gst.FlowReturn.OK:
            self.error = "push-buffer failed"
        self.samples += count

    def write(self, samples: FloatArray) -> None:
        """Append samples."""
        if len(samples):
            self._push(float_to_int16(samples).tobytes(), len(samples))

    def pad(self, count: int) -> None:
        """Append silence."""
        if count > 0:
            self._push(bytes(2 * count), count)

    def close(self) -> None:
        """EOS and release."""
        gst = self._gst
        try:
            self._src.emit("end-of-stream")
            self._pipeline.get_bus().timed_pop_filtered(
                5 * gst.SECOND, gst.MessageType.EOS | gst.MessageType.ERROR
            )
        finally:
            self._pipeline.set_state(gst.State.NULL)


def open_track(stem: Path, codec: str, sample_rate: int = 16000) -> AudioTrack:
    """`stem.wav` or `stem.flac`; FLAC falls back to WAV when GStreamer cannot encode it."""
    if codec == "flac":
        try:
            return FlacTrack(stem.with_suffix(".flac"), sample_rate)
        except Exception:
            pass
    return WavTrack(stem.with_suffix(".wav"), sample_rate)


def repair_wav_header(path: Path) -> int:
    """Rewrite the data-length fields of a WAV left open by a crash; returns the sample count."""
    size = path.stat().st_size
    if size < 44:
        return 0
    data_bytes = size - 44
    with path.open("r+b") as handle:
        handle.seek(4)
        handle.write(np.uint32(size - 8).tobytes())
        handle.seek(40)
        handle.write(np.uint32(data_bytes).tobytes())
    return data_bytes // 2
