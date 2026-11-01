"""sidekick.record.video — H.264 MP4 chunk writer over a GStreamer `appsrc` pipeline

Overview
    `VideoWriter` opens one MP4 per chunk, accepts BGR frames (scaled to the configured size)
    and closes with a clean EOS so the file is playable. The encoder is picked from what the
    installed GStreamer offers: Apple VideoToolbox (`vtenc_h264_hw`, then `vtenc_h264`), the
    Raspberry Pi's `v4l2h264enc`, software `x264enc`, `openh264enc`.
Design
    `appsrc is-live do-timestamp` stamps each frame with the pipeline running time, so a camera
    that stalls (daemon restart) leaves a frozen picture instead of a broken timeline. The muxer
    writes fragmented MP4 (2 s fragments) so a crash loses at most a fragment and the file still
    plays; the dashboard's `<video>` seeks within it through range requests. GStreamer (PyGObject)
    comes with the `reachy-mini` SDK and is imported lazily; without it the writer reports an
    error and the recorder keeps audio and telemetry. One frame copy per push (`tobytes`), no
    other work on the recorder thread; errors are polled from the bus, never raised.
Depends on
    sidekick.log, numpy, opencv (lazy, resize only), gi/GStreamer (lazy).

See Also
--------
    AGENTS.md "Recording", PLAN.md block "[2026-10-26 #25]".

"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from sidekick.log import Log

ENCODERS: tuple[tuple[str, str], ...] = (
    (
        "vtenc_h264_hw",
        "vtenc_h264_hw bitrate={kbps} realtime=true allow-frame-reordering=false max-keyframe-interval={gop}",
    ),
    (
        "vtenc_h264",
        "vtenc_h264 bitrate={kbps} realtime=true allow-frame-reordering=false max-keyframe-interval={gop}",
    ),
    (
        "v4l2h264enc",
        'v4l2h264enc extra-controls="controls,video_bitrate={bps},h264_i_frame_period={gop}" ! video/x-h264,level=(string)4',
    ),
    (
        "x264enc",
        "x264enc bitrate={kbps} speed-preset=veryfast tune=zerolatency key-int-max={gop} threads=2",
    ),
    ("openh264enc", "openh264enc bitrate={bps} gop-size={gop} complexity=low"),
)
FRAGMENT_MS = 2000

_lock = threading.Lock()
_gst: Any = None
_checked = False


def gstreamer() -> Any | None:
    """The initialised `Gst` namespace, or None when PyGObject / GStreamer is missing."""
    global _gst, _checked
    with _lock:
        if _checked:
            return _gst
        _checked = True
        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst

            if not Gst.is_initialized():
                Gst.init(None)
            _gst = Gst
        except Exception as exc:
            Log.warning(f"GStreamer unavailable, video recording off: {exc!r}")
            _gst = None
        return _gst


def pick_encoder(gst: Any) -> tuple[str, str] | None:
    """First available H.264 encoder as `(name, launch fragment)`."""
    for name, launch in ENCODERS:
        if gst.ElementFactory.find(name) is not None:
            return name, launch
    return None


def encoder_name() -> str | None:
    """What `VideoWriter` would use on this host (None = video off)."""
    gst = gstreamer()
    picked = pick_encoder(gst) if gst is not None else None
    return picked[0] if picked else None


class VideoWriter:
    """One MP4 file; `push()` frames, then `close()`."""

    def __init__(self, path: Path, width: int, height: int, fps: float, bitrate_kbps: int) -> None:
        self.path = path
        self.width = width
        self.height = height
        self.fps = fps
        self.frames = 0
        self.error: str | None = None
        self.encoder = ""
        self._pipeline: Any = None
        self._src: Any = None
        gst = gstreamer()
        if gst is None:
            self.error = "gstreamer unavailable"
            return
        picked = pick_encoder(gst)
        if picked is None:
            self.error = "no H.264 encoder"
            return
        self.encoder, launch = picked
        gop = max(1, round(fps * 2))
        enc = launch.format(kbps=bitrate_kbps, bps=bitrate_kbps * 1000, gop=gop)
        desc = (
            "appsrc name=src is-live=true format=time do-timestamp=true block=true "
            f"max-bytes={width * height * 3 * 4} "
            f"caps=video/x-raw,format=BGR,width={width},height={height},framerate={max(1, round(fps))}/1 "
            "! queue max-size-buffers=8 ! videoconvert ! video/x-raw,format=NV12 "
            f"! {enc} ! h264parse ! mp4mux fragment-duration={FRAGMENT_MS} streamable=true "
            f'! filesink location="{path}"'
        )
        try:
            self._pipeline = gst.parse_launch(desc)
            self._src = self._pipeline.get_by_name("src")
            self._pipeline.set_state(gst.State.PLAYING)
        except Exception as exc:
            self.error = f"pipeline: {exc!r}"
            self._pipeline = None
            self._src = None

    @property
    def ok(self) -> bool:
        """Whether frames can be pushed."""
        return self._pipeline is not None and self.error is None

    def push(self, frame: npt.NDArray[np.uint8]) -> bool:
        """Encode one BGR frame (scaled if needed)."""
        gst = gstreamer()
        if not self.ok or gst is None:
            return False
        image: Any = frame
        h, w = frame.shape[:2]
        if (w, h) != (self.width, self.height):
            import cv2

            image = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_AREA)
        buffer = gst.Buffer.new_wrapped(np.ascontiguousarray(image).tobytes())
        result = self._src.emit("push-buffer", buffer)
        if result != gst.FlowReturn.OK:
            self.error = f"push-buffer: {result}"
            return False
        self.frames += 1
        if self.frames % 30 == 0:
            message = self._pipeline.get_bus().pop_filtered(gst.MessageType.ERROR)
            if message is not None:
                err, _ = message.parse_error()
                self.error = f"gstreamer: {err.message}"
                return False
        return True

    def close(self, timeout_s: float = 8.0) -> None:
        """Send EOS, wait for the muxer, release the pipeline."""
        gst = gstreamer()
        if self._pipeline is None or gst is None:
            return
        try:
            if self._src is not None and self.error is None:
                self._src.emit("end-of-stream")
                message = self._pipeline.get_bus().timed_pop_filtered(
                    int(timeout_s * gst.SECOND), gst.MessageType.EOS | gst.MessageType.ERROR
                )
                if message is not None and message.type == gst.MessageType.ERROR:
                    err, _ = message.parse_error()
                    self.error = f"gstreamer: {err.message}"
                elif message is None and self.frames:
                    self.error = "eos timeout"
        finally:
            self._pipeline.set_state(gst.State.NULL)
            self._pipeline = None
            self._src = None
