"""sidekick.asr.minimax_speech_to_text — MiniMax `POST /v1/speech_to_text`

Overview
    Utterance transcription with MiniMax `asr-1.0`: multipart upload of a WAV file, optional
    `language` header (`yue` / `zh` / `en`, empty = mixed-language auto-detect), JSON
    `{text, duration}` back. There is no real-time input endpoint; `stream=true` only streams the
    result of an uploaded file, which brings nothing for sub-second utterances, so it is not used.
Design
    Configuration + backend (invariant 4), injectable `httpx.AsyncClient` for tests. Audio is
    re-encoded to 16 kHz mono 16-bit WAV, the vendor's recommended input; raw PCM is rejected by
    the API. Errors come in two shapes — OpenAI-style `{"error": {...}}` on non-200 and MiniMax
    `base_resp` on 200 — both are mapped to `status_code` / `api_code`.
Depends on
    sidekick.audio, sidekick.log, httpx.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx

from sidekick.audio import AudioClip
from sidekick.log import Log, mask_secret

from .schemas import ASRResult

API_NAME = "minimax_speech_to_text"
KEEPALIVE_S = 120.0  # pooled connections live this long idle (block #71)


@dataclass(frozen=True, slots=True)
class ASRMiniMaxConfiguration:
    """Endpoint, key and model."""

    url: str
    api_key: str
    model: str = "asr-1.0"
    provider: str = "minimax"
    timeout_s: float = 60.0


class ASRMiniMaxBackend:
    """MiniMax speech-to-text over HTTP multipart."""

    def __init__(
        self, configuration: ASRMiniMaxConfiguration, client: httpx.AsyncClient | None = None
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
        language: str | None = None,
    ) -> ASRResult:
        cfg = self.configuration
        return ASRResult(
            False,
            None,
            cfg.provider,
            API_NAME,
            cfg.model,
            mask_secret(cfg.api_key),
            language=language,
            status_code=status_code,
            api_code=api_code,
            error_message=message,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _error_from_body(payload: Any) -> tuple[int | None, str | None]:
        if not isinstance(payload, dict):
            return None, None
        base = payload.get("base_resp")
        if (
            isinstance(base, dict)
            and isinstance(base.get("status_code"), int)
            and base["status_code"] != 0
        ):
            return int(base["status_code"]), str(base.get("status_msg") or "unknown")
        error = payload.get("error")
        if isinstance(error, dict):
            code = error.get("http_code") if isinstance(error.get("http_code"), int) else None
            return code, str(error.get("message") or error.get("type") or "error")
        return None, None

    async def transcribe(self, clip: AudioClip, language: str | None = None) -> ASRResult:
        """Upload the clip as WAV and return the transcript."""
        cfg = self.configuration
        key_hint = mask_secret(cfg.api_key)
        headers = {"Authorization": f"Bearer {cfg.api_key}"}
        if language:
            headers["language"] = language
        wav = clip.to_wav_bytes()
        Log.info(
            f"request: provider={cfg.provider} model={cfg.model} key={key_hint} audio={clip.duration_s:.2f}s language={language or 'auto'} bytes={len(wav)}"
        )
        started = time.monotonic()
        client = self._http()
        try:
            response = await client.post(
                cfg.url,
                headers=headers,
                files={"file": ("audio.wav", wav, "audio/wav")},
                data={"model": cfg.model, "response_format": "json"},
            )
        except httpx.HTTPError as exc:
            Log.error(f"transport failure: {exc!r}")
            return self._failure(
                f"transport: {exc!r}", latency_ms=_elapsed(started), language=language
            )
        latency = _elapsed(started)
        try:
            payload: Any = response.json()
        except ValueError:
            payload = None
        if response.status_code != 200:
            api_code, message = self._error_from_body(payload)
            Log.error(f"http {response.status_code}: {response.text[:300]}")
            return self._failure(
                message or response.text[:1000] or f"http {response.status_code}",
                response.status_code,
                api_code,
                latency,
                language,
            )
        api_code, message = self._error_from_body(payload)
        if api_code is not None or message is not None:
            Log.error(f"api error {api_code}: {message}")
            return self._failure(
                f"api status {api_code}: {message}", 200, api_code, latency, language
            )
        if not isinstance(payload, dict) or "text" not in payload:
            return self._failure("no text in response", 200, latency_ms=latency, language=language)
        text = str(payload.get("text") or "")
        duration = payload.get("duration")
        Log.info(f"ok: chars={len(text)} audio={duration}s latency={latency:.0f}ms")
        return ASRResult(
            True,
            text,
            cfg.provider,
            API_NAME,
            cfg.model,
            key_hint,
            language=language,
            duration_s=float(duration) if isinstance(duration, (int, float)) else clip.duration_s,
            status_code=200,
            latency_ms=latency,
        )


def _elapsed(started: float) -> float:
    return (time.monotonic() - started) * 1000.0
