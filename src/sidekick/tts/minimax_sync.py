"""sidekick.tts.minimax_sync — MiniMax `POST /v1/t2a_v2` (whole utterance)

Overview
    The fallback voice path and the probe target: one HTTP call, hex-encoded audio back. Ported
    from Scoop's `TTSMiniMaxSync`, with PCM 16 kHz mono output instead of MP3 so the bytes can be
    pushed to the robot speaker without a decoder.
Design
    Configuration + backend (invariant 4); injectable client. `language_boost` carries the
    language hint (`Chinese,Yue` for Cantonese); `emotion` is optional. MiniMax reports failures
    as HTTP 200 with `base_resp.status_code != 0`, mapped to `api_code`.
Depends on
    sidekick.log, httpx.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx

from sidekick.log import Log, mask_secret

from .schemas import TTSResult

API_NAME = "minimax_sync"
KEEPALIVE_S = 120.0  # pooled connections live this long idle (block #71)


@dataclass(frozen=True, slots=True)
class TTSMiniMaxSyncConfiguration:
    """Endpoint, key, model, voice and audio format."""

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
    timeout_s: float = 60.0


class TTSMiniMaxSyncBackend:
    """MiniMax synchronous TTS over HTTP."""

    def __init__(
        self, configuration: TTSMiniMaxSyncConfiguration, client: httpx.AsyncClient | None = None
    ) -> None:
        self.configuration = configuration
        self._client = client  # injected (tests): used as is, never closed here
        self._pool: httpx.AsyncClient | None = None
        self._pool_loop: asyncio.AbstractEventLoop | None = None

    def _http(self) -> httpx.AsyncClient:
        """The client for this event loop; its connections outlive a call (no TLS per call)."""
        if self._client is not None:
            return self._client
        loop = asyncio.get_running_loop()
        if self._pool is None or self._pool_loop is not loop or self._pool.is_closed:
            self._pool = httpx.AsyncClient(
                timeout=self.configuration.timeout_s,
                limits=httpx.Limits(max_keepalive_connections=2, keepalive_expiry=KEEPALIVE_S),
            )
            self._pool_loop = loop
        return self._pool

    async def aclose(self) -> None:
        """Close the pooled connections (the slot was replaced or the service stopped)."""
        pool, self._pool = self._pool, None
        if pool is not None and not pool.is_closed:
            await pool.aclose()

    def _failure(
        self,
        message: str,
        status_code: int | None = None,
        api_code: int | None = None,
        latency_ms: float | None = None,
    ) -> TTSResult:
        cfg = self.configuration
        return TTSResult(
            False,
            None,
            cfg.provider,
            API_NAME,
            cfg.model,
            cfg.voice_id,
            mask_secret(cfg.api_key),
            cfg.format,
            cfg.sample_rate,
            1,
            status_code=status_code,
            api_code=api_code,
            error_message=message,
            latency_ms=latency_ms,
        )

    def body(self, text: str) -> dict[str, Any]:
        """Request body for `text`."""
        cfg = self.configuration
        voice: dict[str, Any] = {"voice_id": cfg.voice_id, "speed": cfg.speed}
        if cfg.emotion:
            voice["emotion"] = cfg.emotion
        body: dict[str, Any] = {
            "model": cfg.model,
            "text": text,
            "voice_setting": voice,
            "audio_setting": {"format": cfg.format, "sample_rate": cfg.sample_rate, "channel": 1},
            "output_format": "hex",
        }
        if cfg.language_boost:
            body["language_boost"] = cfg.language_boost
        return body

    async def infer(self, text: str) -> TTSResult:
        """Synthesize `text`; never raises for provider failures."""
        cfg = self.configuration
        key_hint = mask_secret(cfg.api_key)
        Log.info(
            f"request: provider={cfg.provider} model={cfg.model} voice={cfg.voice_id} key={key_hint} chars={len(text)} boost={cfg.language_boost}"
        )
        started = time.monotonic()
        client = self._http()
        try:
            response = await client.post(
                cfg.url,
                headers={
                    "Authorization": f"Bearer {cfg.api_key}",
                    "Content-Type": "application/json",
                },
                json=self.body(text),
            )
        except httpx.HTTPError as exc:
            Log.error(f"transport failure: {exc!r}")
            return self._failure(f"transport: {exc!r}", latency_ms=_elapsed(started))
        latency = _elapsed(started)
        if response.status_code != 200:
            Log.error(f"http {response.status_code}: {response.text[:300]}")
            return self._failure(
                response.text[:1000] or f"http {response.status_code}",
                response.status_code,
                latency_ms=latency,
            )
        try:
            payload = response.json()
        except ValueError:
            return self._failure("invalid json response", 200, latency_ms=latency)
        base = payload.get("base_resp") if isinstance(payload, dict) else None
        if isinstance(base, dict) and base.get("status_code") not in (0, None):
            Log.error(f"api error {base.get('status_code')}: {base.get('status_msg')}")
            return self._failure(
                f"minimax status {base.get('status_code')}: {base.get('status_msg')}",
                200,
                int(base["status_code"]),
                latency,
            )
        data = payload.get("data") if isinstance(payload, dict) else None
        audio_hex = data.get("audio") if isinstance(data, dict) else None
        if not isinstance(audio_hex, str) or not audio_hex:
            Log.error(f"no audio in response: {str(payload)[:200]}")
            return self._failure("no audio in response", 200, latency_ms=latency)
        try:
            audio = bytes.fromhex(audio_hex)
        except ValueError:
            return self._failure("audio is not hex", 200, latency_ms=latency)
        extra = payload.get("extra_info") if isinstance(payload, dict) else None
        usage = extra.get("usage_characters") if isinstance(extra, dict) else None
        Log.info(f"ok: bytes={len(audio)} usage_chars={usage} latency={latency:.0f}ms")
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
            usage_chars=usage if isinstance(usage, int) else None,
            status_code=200,
            latency_ms=latency,
        )


def _elapsed(started: float) -> float:
    return (time.monotonic() - started) * 1000.0
