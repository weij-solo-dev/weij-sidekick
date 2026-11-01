"""sidekick.llm.v1_chat_completion — OpenAI-compatible chat completions backend

Overview
    The one LLM backend sidekick needs for MiniMax, OpenAI, DashScope, Volcengine, DeepSeek and
    friends: `POST <url>` with the chat-completions body, non-streaming or SSE streaming, with
    tool calling. MiniMax is the first target (`/v1/chat/completions`, models `MiniMax-M3` and
    `MiniMax-M3.1-Flash`).
Design
    A frozen configuration plus a backend class (invariant 4). The HTTP client is injectable so
    tests use `httpx.MockTransport`. Streaming parses `data:` lines, accumulates tool-call
    deltas by index, and tolerates a vendor's final chunk carrying a full `message` instead of a
    `delta` (the legacy MiniMax behaviour) without duplicating text. MiniMax's `base_resp` is
    read before the choices so an auth failure surfaces as `api_code=1004`, not as "no content".
    `max_tokens_field` lets a preset switch to `max_completion_tokens` (MiniMax deprecates
    `max_tokens`). Provider failures never raise: they come back as `LLMResult(success=False)`.
    One HTTP client per backend and event loop, its connections kept alive for
    `KEEPALIVE_S`: a fresh client per call paid a TLS handshake every time — 1.3 s from the
    owner's Mac to `api.minimaxi.com`, half of the first token (block #71). `warm()` opens a
    pooled connection ahead of a turn (`warm(2)` keeps a second one for a hedged request, block
    #78); the stream records when the first text arrived (`first_token_ms`) and yields `start`
    with the first delta of any kind, text or tool call, which is what a hedged call races on.
Depends on
    sidekick.log, httpx.

See Also
--------
    AGENTS.md "Provider framework", PLAN.md block "[2026-10-26 #10]".

"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from sidekick.log import Log, mask_secret

from .schemas import (
    LLMInferOptions,
    LLMMessage,
    LLMResult,
    LLMStreamEvent,
    LLMToolCall,
    LLMUsage,
)

API_NAME = "v1_chat_completion"
KEEPALIVE_S = 120.0  # pooled connections live this long idle (the server kept them > 4 min)


@dataclass(frozen=True, slots=True)
class LLMV1ChatCompletionConfiguration:
    """Fixed part of a deployment: endpoint, key, model and defaults."""

    url: str
    api_key: str
    model: str
    provider: str = ""
    temperature: float | None = None
    max_tokens: int = 2048
    max_tokens_field: str = "max_tokens"
    extra_body: Mapping[str, Any] = field(default_factory=dict)
    timeout_s: float = 60.0


class LLMV1ChatCompletionBackend:
    """Chat completions over HTTP, streaming or not."""

    def __init__(
        self,
        configuration: LLMV1ChatCompletionConfiguration,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.configuration = configuration
        self._client = client  # injected (tests): used as is, never closed here
        self._pool: httpx.AsyncClient | None = None
        self._pool_loop: asyncio.AbstractEventLoop | None = None

    def _http(self) -> httpx.AsyncClient:
        """The client for this event loop; its connections outlive a call."""
        if self._client is not None:
            return self._client
        loop = asyncio.get_running_loop()
        if self._pool is None or self._pool_loop is not loop or self._pool.is_closed:
            self._pool = httpx.AsyncClient(
                timeout=self.configuration.timeout_s,
                limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=KEEPALIVE_S),
            )
            self._pool_loop = loop
        return self._pool

    async def warm(self, connections: int = 1) -> None:
        """Open (or keep) pooled connections to the endpoint's host: no handshake on the turn.

        Requests sent together each take a connection of their own, so `connections` of them
        keep that many open (a hedged call's second request needs its own, block #78).
        """
        parts = urlsplit(self.configuration.url)

        async def head() -> None:
            try:
                await self._http().head(f"{parts.scheme}://{parts.netloc}/", timeout=10.0)
            except httpx.HTTPError as exc:
                Log.debug(f"warm {parts.netloc}: {exc!r}")

        await asyncio.gather(*(head() for _ in range(max(1, connections))))

    async def aclose(self) -> None:
        """Close the pooled connections."""
        if self._pool is not None and not self._pool.is_closed:
            await self._pool.aclose()
        self._pool = None

    # -- request building -------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.configuration.api_key}",
            "Content-Type": "application/json",
        }

    def _body(
        self, messages: list[LLMMessage], options: LLMInferOptions, stream: bool
    ) -> dict[str, Any]:
        cfg = self.configuration
        body: dict[str, Any] = {
            "model": cfg.model,
            "messages": [message.to_openai() for message in messages],
            "stream": stream,
            cfg.max_tokens_field: options.max_tokens or cfg.max_tokens,
        }
        temperature = options.temperature if options.temperature is not None else cfg.temperature
        if temperature is not None:
            body["temperature"] = temperature
        if options.tools:
            body["tools"] = [tool.to_openai() for tool in options.tools]
            if options.tool_choice:
                body["tool_choice"] = options.tool_choice
        if stream:
            body["stream_options"] = {"include_usage": True}
        body.update(cfg.extra_body)
        body.update(options.extra_body)
        return body

    def _failure(
        self,
        message: str,
        status_code: int | None = None,
        api_code: int | None = None,
        usage: LLMUsage | None = None,
        latency_ms: float | None = None,
    ) -> LLMResult:
        return LLMResult(
            success=False,
            output=None,
            provider=self.configuration.provider,
            api=API_NAME,
            model=self.configuration.model,
            api_key_hint=mask_secret(self.configuration.api_key),
            usage=usage,
            status_code=status_code,
            api_code=api_code,
            error_message=message,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _parse_usage(raw: Any) -> LLMUsage | None:
        if not isinstance(raw, dict):
            return None
        prompt = raw.get("prompt_tokens")
        completion = raw.get("completion_tokens")
        total = raw.get("total_tokens")
        if prompt is None and completion is None and total is None:
            return None
        details = raw.get("prompt_tokens_details")
        cached = details.get("cached_tokens") if isinstance(details, dict) else None
        return LLMUsage(prompt, completion, total, cached if isinstance(cached, int) else None)

    @staticmethod
    def _base_resp_error(payload: Mapping[str, Any]) -> tuple[int, str] | None:
        base = payload.get("base_resp")
        if isinstance(base, dict):
            code = base.get("status_code")
            if isinstance(code, int) and code != 0:
                return code, str(base.get("status_msg") or "unknown")
        return None

    @staticmethod
    def _parse_tool_calls(raw: Any) -> tuple[LLMToolCall, ...]:
        if not isinstance(raw, list):
            return ()
        calls: list[LLMToolCall] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            function = item.get("function") or {}
            arguments = function.get("arguments", "")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False)
            calls.append(
                LLMToolCall(
                    id=str(item.get("id") or f"call_{index}"),
                    name=str(function.get("name") or ""),
                    arguments=arguments,
                )
            )
        return tuple(calls)

    # -- non-streaming ----------------------------------------------------------------------

    async def infer(self, messages: list[LLMMessage], options: LLMInferOptions) -> LLMResult:
        """One completion; never raises for provider failures."""
        cfg = self.configuration
        key_hint = mask_secret(cfg.api_key)
        body = self._body(messages, options, stream=False)
        started = time.monotonic()
        Log.info(
            f"request: provider={cfg.provider} model={cfg.model} key={key_hint} messages={len(messages)} tools={len(options.tools)}"
        )
        client = self._http()
        try:
            response = await client.post(cfg.url, headers=self._headers(), json=body)
        except httpx.HTTPError as exc:
            Log.error(f"transport failure: {exc!r}")
            return self._failure(f"transport: {exc!r}", latency_ms=_elapsed(started))
        latency = _elapsed(started)
        if response.status_code != 200:
            Log.error(f"http {response.status_code}: {response.text[:300]}")
            api_code = None
            try:
                err = self._base_resp_error(response.json())
                api_code = err[0] if err else None
            except ValueError:
                pass
            return self._failure(
                response.text[:1000] or f"http {response.status_code}",
                response.status_code,
                api_code,
                latency_ms=latency,
            )
        try:
            payload = response.json()
        except ValueError:
            return self._failure("invalid json response", 200, latency_ms=latency)
        usage = self._parse_usage(payload.get("usage"))
        err = self._base_resp_error(payload)
        if err is not None:
            Log.error(f"api error {err[0]}: {err[1]}")
            return self._failure(f"api status {err[0]}: {err[1]}", 200, err[0], usage, latency)
        choices = payload.get("choices") or []
        message = (choices[0].get("message") if choices else None) or {}
        finish = choices[0].get("finish_reason") if choices else None
        tool_calls = self._parse_tool_calls(message.get("tool_calls"))
        content = message.get("content")
        if content is None and not tool_calls:
            Log.error(f"no content: {json.dumps(payload)[:300]}")
            return self._failure("no content in response", 200, usage=usage, latency_ms=latency)
        Log.info(
            f"ok: finish={finish} chars={len(content or '')} tool_calls={len(tool_calls)} latency={latency:.0f}ms"
        )
        return LLMResult(
            success=True,
            output=content,
            provider=cfg.provider,
            api=API_NAME,
            model=cfg.model,
            api_key_hint=key_hint,
            tool_calls=tool_calls,
            finish_reason=finish,
            reasoning=message.get("reasoning_content"),
            usage=usage,
            status_code=200,
            latency_ms=latency,
        )

    # -- streaming --------------------------------------------------------------------------

    async def stream(
        self, messages: list[LLMMessage], options: LLMInferOptions
    ) -> AsyncIterator[LLMStreamEvent]:
        """SSE completion; yields deltas and ends with a `done` event carrying the result."""
        cfg = self.configuration
        key_hint = mask_secret(cfg.api_key)
        body = self._body(messages, options, stream=True)
        started = time.monotonic()
        Log.info(
            f"stream request: provider={cfg.provider} model={cfg.model} key={key_hint} messages={len(messages)} tools={len(options.tools)}"
        )
        client = self._http()
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        pending_calls: dict[int, dict[str, str]] = {}
        emitted_calls: list[LLMToolCall] = []
        finish: str | None = None
        usage: LLMUsage | None = None
        first_token_ms: float | None = None
        started_answer = False  # `start` was yielded
        finished = False
        try:
            async with client.stream(
                "POST", cfg.url, headers=self._headers(), json=body
            ) as response:
                if response.status_code != 200:
                    raw = (await response.aread()).decode("utf-8", "replace")
                    Log.error(f"http {response.status_code}: {raw[:300]}")
                    api_code = None
                    try:
                        err = self._base_resp_error(json.loads(raw))
                        api_code = err[0] if err else None
                    except ValueError:
                        pass
                    yield LLMStreamEvent(
                        "done",
                        result=self._failure(
                            raw[:1000] or f"http {response.status_code}",
                            response.status_code,
                            api_code,
                            latency_ms=_elapsed(started),
                        ),
                    )
                    return
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        Log.warning(f"bad sse chunk: {data[:120]}")
                        continue
                    err = self._base_resp_error(chunk)
                    if err is not None:
                        Log.error(f"api error {err[0]}: {err[1]}")
                        yield LLMStreamEvent(
                            "done",
                            result=self._failure(
                                f"api status {err[0]}: {err[1]}",
                                200,
                                err[0],
                                usage,
                                _elapsed(started),
                            ),
                        )
                        return
                    if chunk.get("usage"):
                        usage = self._parse_usage(chunk["usage"]) or usage
                    for choice in chunk.get("choices") or []:
                        if choice.get("finish_reason"):
                            finish = choice["finish_reason"]
                        delta = choice.get("delta")
                        if not started_answer and _answers(delta, choice.get("message")):
                            started_answer = True
                            yield LLMStreamEvent("start")
                        if isinstance(delta, dict):
                            text = delta.get("content")
                            if text:
                                if first_token_ms is None:
                                    first_token_ms = _elapsed(started)
                                text_parts.append(text)
                                yield LLMStreamEvent("text", text=text)
                            reasoning = delta.get("reasoning_content")
                            if reasoning:
                                reasoning_parts.append(reasoning)
                                yield LLMStreamEvent("reasoning", text=reasoning)
                            for item in delta.get("tool_calls") or []:
                                if not isinstance(item, dict):
                                    continue
                                index = int(item.get("index", len(pending_calls)))
                                call_id = str(item.get("id") or "")
                                slot = pending_calls.get(index)
                                if slot is not None and call_id and slot["id"] not in ("", call_id):
                                    # A new call under an index already used (MiniMax-M3.1-Flash
                                    # did this): appending made `scheduleschedule`.
                                    index = max(pending_calls) + 1
                                    slot = None
                                if slot is None:
                                    slot = pending_calls.setdefault(
                                        index, {"id": "", "name": "", "arguments": ""}
                                    )
                                if call_id:
                                    slot["id"] = call_id
                                function = item.get("function") or {}
                                name = str(function.get("name") or "")
                                if name and name != slot["name"]:  # a repeated name is not news
                                    slot["name"] += name
                                if function.get("arguments"):
                                    slot["arguments"] += str(function["arguments"])
                        # Legacy MiniMax: the last chunk repeats the whole message.
                        full = choice.get("message")
                        if isinstance(full, dict):
                            if not text_parts and full.get("content"):
                                text_parts.append(str(full["content"]))
                                yield LLMStreamEvent("text", text=str(full["content"]))
                            if not pending_calls and full.get("tool_calls"):
                                for call in self._parse_tool_calls(full["tool_calls"]):
                                    emitted_calls.append(call)
                                    yield LLMStreamEvent("tool_call", tool_call=call)
            finished = True
        except httpx.HTTPError as exc:
            Log.error(f"transport failure: {exc!r}")
            yield LLMStreamEvent(
                "done",
                result=self._failure(f"transport: {exc!r}", latency_ms=_elapsed(started)),
            )
            return
        finally:
            if not finished and self._client is None:
                # Cancelled mid-body (a barge-in): httpx dropped that connection, so open the
                # next one now rather than on the next turn.
                try:
                    asyncio.get_running_loop().create_task(self.warm())
                except RuntimeError:  # the loop is shutting down
                    pass
        for index in sorted(pending_calls):
            slot = pending_calls[index]
            call = LLMToolCall(slot["id"] or f"call_{index}", slot["name"], slot["arguments"])
            emitted_calls.append(call)
            yield LLMStreamEvent("tool_call", tool_call=call)
        output = "".join(text_parts)
        latency = _elapsed(started)
        if not output and not emitted_calls:
            yield LLMStreamEvent(
                "done", result=self._failure("empty stream", 200, usage=usage, latency_ms=latency)
            )
            return
        Log.info(
            f"stream ok: finish={finish} chars={len(output)} tool_calls={len(emitted_calls)} first_token={first_token_ms and round(first_token_ms)}ms total={latency:.0f}ms"
        )
        yield LLMStreamEvent(
            "done",
            result=LLMResult(
                success=True,
                output=output or None,
                provider=cfg.provider,
                api=API_NAME,
                model=cfg.model,
                api_key_hint=key_hint,
                tool_calls=tuple(emitted_calls),
                finish_reason=finish,
                reasoning="".join(reasoning_parts) or None,
                usage=usage,
                status_code=200,
                latency_ms=latency,
                first_token_ms=first_token_ms,
            ),
        )


def _elapsed(started: float) -> float:
    return (time.monotonic() - started) * 1000.0


def _answers(delta: Any, message: Any) -> bool:
    """Whether a chunk carries the answer itself: text, reasoning or a tool call."""
    for part in (delta, message):
        if isinstance(part, dict) and any(
            part.get(k) for k in ("content", "reasoning_content", "tool_calls")
        ):
            return True
    return False
