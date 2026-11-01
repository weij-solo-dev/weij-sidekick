"""sidekick.tts.minimax_ws — MiniMax bidirectional streaming TTS (`/ws/v1/t2a_v2_bidi`)

Overview
    The robot's main voice path: LLM tokens are pushed into one WebSocket session as they arrive,
    the server buffers them into sentences and streams PCM 16 kHz back. `flush` ends a turn
    without reconnecting, `cancel` implements barge-in, `finish` closes.
Design
    Protocol: connect → `connected_success` → `task_start{model, voice_setting, audio_setting,
    language_boost}` → `task_started` → N × `task_continue{text}` → server `sentence_start`,
    `task_continued{data.audio hex, is_final}`, `sentence_end` → `task_flush` / `task_cancel` /
    `task_finish`. A reader task turns server messages into `TTSStreamEvent`s on a queue; the
    `websockets` client pings every 20 s so the 120 s idle timeout never fires. `infer(text)` is
    implemented on top of a one-shot session so the same backend also serves blocking callers and
    the save-time probe. Provider failures become `error` events or failed results, never
    exceptions to the caller.
Depends on
    sidekick.log, websockets.

See Also
--------
    PLAN.md block "[2026-10-26 #10]" for the protocol notes.

"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, cast

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from sidekick.log import Log, mask_secret

from .schemas import TTSResult, TTSStreamEvent

API_NAME = "minimax_ws"


@dataclass(frozen=True, slots=True)
class TTSMiniMaxWSConfiguration:
    """Endpoint, key, model, voice and audio format for the bidirectional session."""

    url: str
    api_key: str
    voice_id: str
    model: str = "speech-2.8-turbo"
    speed: float = 1.0
    language_boost: str | None = "auto"
    emotion: str | None = None
    sample_rate: int = 16000
    format: str = "pcm"
    provider: str = "minimax"
    connect_timeout_s: float = 15.0


class TTSMiniMaxWSStream:
    """One live bidirectional session."""

    def __init__(self, configuration: TTSMiniMaxWSConfiguration, ws: ClientConnection) -> None:
        self.configuration = configuration
        self._ws = ws
        self._queue: asyncio.Queue[TTSStreamEvent | None] = asyncio.Queue()
        self._reader: asyncio.Task[None] | None = None
        self.audio_bytes = 0
        self.usage_chars: int | None = None
        self.closed = False

    @classmethod
    async def start(cls, configuration: TTSMiniMaxWSConfiguration) -> TTSMiniMaxWSStream:
        """Connect, wait for `connected_success`, send `task_start`, wait for `task_started`."""
        cfg = configuration
        Log.info(
            f"connect: provider={cfg.provider} model={cfg.model} voice={cfg.voice_id} key={mask_secret(cfg.api_key)}"
        )
        ws = await asyncio.wait_for(
            connect(
                cfg.url,
                additional_headers={"Authorization": f"Bearer {cfg.api_key}"},
                ping_interval=20,
                max_size=None,
            ),
            timeout=cfg.connect_timeout_s,
        )
        stream = cls(cfg, ws)
        try:
            hello = await asyncio.wait_for(stream._recv_json(), timeout=cfg.connect_timeout_s)
            stream._raise_if_failed(hello, "connected_success")
            await stream._send_json(stream.task_start_message())
            started = await asyncio.wait_for(stream._recv_json(), timeout=cfg.connect_timeout_s)
            stream._raise_if_failed(started, "task_started")
        except BaseException:
            await ws.close()
            raise
        stream._reader = asyncio.create_task(stream._read_loop())
        return stream

    def task_start_message(self) -> dict[str, Any]:
        """The `task_start` payload."""
        cfg = self.configuration
        voice: dict[str, Any] = {"voice_id": cfg.voice_id, "speed": cfg.speed}
        if cfg.emotion:
            voice["emotion"] = cfg.emotion
        message: dict[str, Any] = {
            "event": "task_start",
            "model": cfg.model,
            "voice_setting": voice,
            "audio_setting": {"format": cfg.format, "sample_rate": cfg.sample_rate, "channel": 1},
        }
        if cfg.language_boost:
            message["language_boost"] = cfg.language_boost
        return message

    @staticmethod
    def _raise_if_failed(message: dict[str, Any], expected: str) -> None:
        base = message.get("base_resp") or {}
        code = base.get("status_code", 0)
        if message.get("event") != expected or code not in (0, None):
            raise RuntimeError(
                f"expected {expected}, got {message.get('event')} status {code}: {base.get('status_msg')}"
            )

    async def _send_json(self, message: dict[str, Any]) -> None:
        await self._ws.send(json.dumps(message, ensure_ascii=False))

    async def _recv_json(self) -> dict[str, Any]:
        raw = await self._ws.recv()
        data = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}

    async def _read_loop(self) -> None:
        try:
            while True:
                message = await self._recv_json()
                event = message.get("event")
                base = message.get("base_resp") or {}
                code = base.get("status_code", 0)
                if event == "task_failed" or code not in (0, None):
                    Log.error(f"server error {code}: {base.get('status_msg')} (event={event})")
                    await self._queue.put(
                        TTSStreamEvent(
                            "error",
                            message=str(base.get("status_msg") or event),
                            api_code=int(code) if isinstance(code, int) else None,
                        )
                    )
                    break
                if event == "task_continued":
                    data = message.get("data") or {}
                    audio_hex = data.get("audio") if isinstance(data, dict) else None
                    extra = message.get("extra_info") or {}
                    if isinstance(extra, dict) and isinstance(extra.get("usage_characters"), int):
                        self.usage_chars = (self.usage_chars or 0) + int(extra["usage_characters"])
                    if isinstance(audio_hex, str) and audio_hex:
                        try:
                            audio = bytes.fromhex(audio_hex)
                        except ValueError:
                            Log.warning("audio chunk is not hex; dropped")
                            continue
                        self.audio_bytes += len(audio)
                        await self._queue.put(TTSStreamEvent("audio", audio=audio))
                elif event in (
                    "sentence_start",
                    "sentence_end",
                    "task_flushed",
                    "task_canceled",
                    "task_finished",
                ):
                    kind = {
                        "task_flushed": "flushed",
                        "task_canceled": "canceled",
                        "task_finished": "finished",
                    }.get(event, event)
                    await self._queue.put(
                        TTSStreamEvent(
                            cast(
                                Literal[
                                    "sentence_start",
                                    "sentence_end",
                                    "flushed",
                                    "canceled",
                                    "finished",
                                ],
                                kind,
                            )
                        )
                    )
                    if event == "task_finished":
                        break
                else:
                    Log.debug(f"ignored event {event}")
        except ConnectionClosed as exc:
            if not self.closed:
                Log.warning(f"connection closed: {exc!r}")
                await self._queue.put(
                    TTSStreamEvent(
                        "error",
                        message=f"connection closed: {exc.code if hasattr(exc, 'code') else exc!r}",
                    )
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            Log.error(f"reader failed: {exc!r}")
            await self._queue.put(TTSStreamEvent("error", message=repr(exc)))
        finally:
            await self._queue.put(None)

    async def send(self, text: str) -> None:
        """`task_continue` with a text fragment."""
        if text:
            await self._send_json({"event": "task_continue", "text": text})

    async def flush(self) -> None:
        """`task_flush`."""
        await self._send_json({"event": "task_flush"})

    async def cancel(self) -> None:
        """`task_cancel` — drop buffered text and in-flight audio."""
        await self._send_json({"event": "task_cancel"})

    async def finish(self) -> None:
        """`task_finish` — flush then close from the server side."""
        await self._send_json({"event": "task_finish"})

    async def events(self) -> AsyncIterator[TTSStreamEvent]:
        """Yield events until `finished`, `error`, or the connection ends."""
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event
            if event.kind in ("finished", "error"):
                return

    async def aclose(self) -> None:
        """Stop the reader and close the socket."""
        self.closed = True
        if self._reader is not None and not self._reader.done():
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                pass
        await self._ws.close()


class TTSMiniMaxWSBackend:
    """Opens bidirectional sessions; also serves blocking `infer` through a one-shot session."""

    def __init__(self, configuration: TTSMiniMaxWSConfiguration) -> None:
        self.configuration = configuration

    async def open_stream(self) -> TTSMiniMaxWSStream:
        """Connect and start a session."""
        return await TTSMiniMaxWSStream.start(self.configuration)

    async def infer(self, text: str) -> TTSResult:
        """Synthesize `text` through a one-shot session; never raises for provider failures."""
        cfg = self.configuration
        key_hint = mask_secret(cfg.api_key)
        started = time.monotonic()
        try:
            stream = await self.open_stream()
        except Exception as exc:
            Log.error(f"session start failed: {exc!r}")
            return TTSResult(
                False,
                None,
                cfg.provider,
                API_NAME,
                cfg.model,
                cfg.voice_id,
                key_hint,
                cfg.format,
                cfg.sample_rate,
                1,
                error_message=f"start: {exc!r}",
                latency_ms=_elapsed(started),
            )
        chunks: list[bytes] = []
        error: TTSStreamEvent | None = None
        first_audio_ms: float | None = None
        try:
            await stream.send(text)
            await stream.finish()
            async for event in stream.events():
                if event.kind == "audio":
                    if first_audio_ms is None:
                        first_audio_ms = _elapsed(started)
                    chunks.append(event.audio)
                elif event.kind == "error":
                    error = event
        finally:
            await stream.aclose()
        latency = _elapsed(started)
        if error is not None:
            return TTSResult(
                False,
                None,
                cfg.provider,
                API_NAME,
                cfg.model,
                cfg.voice_id,
                key_hint,
                cfg.format,
                cfg.sample_rate,
                1,
                api_code=error.api_code,
                error_message=error.message,
                latency_ms=latency,
            )
        audio = b"".join(chunks)
        if not audio:
            return TTSResult(
                False,
                None,
                cfg.provider,
                API_NAME,
                cfg.model,
                cfg.voice_id,
                key_hint,
                cfg.format,
                cfg.sample_rate,
                1,
                error_message="no audio received",
                latency_ms=latency,
            )
        Log.info(
            f"ok: bytes={len(audio)} first_audio={first_audio_ms and round(first_audio_ms)}ms total={latency:.0f}ms usage_chars={stream.usage_chars}"
        )
        return TTSResult(
            True,
            audio,
            cfg.provider,
            API_NAME,
            cfg.model,
            cfg.voice_id,
            key_hint,
            cfg.format,
            cfg.sample_rate,
            1,
            usage_chars=stream.usage_chars,
            status_code=200,
            latency_ms=latency,
        )


def _elapsed(started: float) -> float:
    return (time.monotonic() - started) * 1000.0
