import json

import httpx

from sidekick.llm import (
    LLMInferOptions,
    LLMMessage,
    LLMSession,
    LLMToolSpec,
    LLMV1ChatCompletionBackend,
    LLMV1ChatCompletionConfiguration,
)

CFG = LLMV1ChatCompletionConfiguration(
    url="https://example.test/v1/chat/completions",
    api_key="sk-cp-TESTKEY0000000000001234",
    model="MiniMax-M3",
    provider="minimax",
    max_tokens_field="max_completion_tokens",
    extra_body={"thinking": {"type": "disabled"}},
)


def backend_with(handler):
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return LLMV1ChatCompletionBackend(CFG, client=client)


def sse(chunks):
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})


async def test_infer_builds_body_and_parses_content():
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "你好",
                            "reasoning_content": "...",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
        )

    result = await backend_with(handler).infer(
        [LLMMessage("user", "hi")], LLMInferOptions(max_tokens=64)
    )
    assert result.success and result.output == "你好" and result.finish_reason == "stop"
    assert result.usage.total_tokens == 7 and result.reasoning == "..."
    assert (
        result.api_key_hint.endswith(f"1234({len(CFG.api_key)})")
        and "TESTKEY" not in result.api_key_hint
    )
    body = seen["body"]
    assert body["max_completion_tokens"] == 64 and "max_tokens" not in body
    assert body["thinking"] == {"type": "disabled"} and body["stream"] is False
    assert seen["auth"] == f"Bearer {CFG.api_key}"


async def test_infer_reports_base_resp_error_with_api_code():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "base_resp": {"status_code": 1004, "status_msg": "invalid api key"},
                "choices": [],
            },
        )

    result = await backend_with(handler).infer([LLMMessage("user", "hi")], LLMInferOptions())
    assert not result.success and result.api_code == 1004 and result.status_code == 200
    assert "1004" in result.error_message


async def test_infer_reports_http_and_transport_failures():
    def handler(request):
        return httpx.Response(429, text="rate limited")

    result = await backend_with(handler).infer([LLMMessage("user", "hi")], LLMInferOptions())
    assert (
        not result.success and result.status_code == 429 and "rate limited" in result.error_message
    )

    def boom(request):
        raise httpx.ConnectError("no route")

    result = await backend_with(boom).infer([LLMMessage("user", "hi")], LLMInferOptions())
    assert not result.success and result.status_code is None and "transport" in result.error_message


async def test_infer_parses_tool_calls_and_round_trips_messages():
    def handler(request):
        body = json.loads(request.content)
        assert body["tools"][0]["function"]["name"] == "get_weather"
        assert body["messages"][-1]["role"] == "tool"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_weather",
                                        "arguments": '{"city":"HK"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )

    tool = LLMToolSpec(
        "get_weather", "weather", {"type": "object", "properties": {"city": {"type": "string"}}}
    )
    messages = [LLMMessage("user", "weather?"), LLMMessage("tool", "sunny", tool_call_id="call_0")]
    result = await backend_with(handler).infer(messages, LLMInferOptions(tools=(tool,)))
    assert result.success and result.finish_reason == "tool_calls"
    assert result.tool_calls[0].name == "get_weather" and json.loads(
        result.tool_calls[0].arguments
    ) == {"city": "HK"}


async def test_stream_yields_text_and_assembled_tool_calls():
    chunks = [
        {"choices": [{"delta": {"role": "assistant", "content": "早"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "晨"}, "finish_reason": None}]},
        {"choices": [{"delta": {"reasoning_content": "thinking"}, "finish_reason": None}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "c1",
                                "function": {"name": "sched", "arguments": '{"at":'},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"8:00"}'}}]},
                    "finish_reason": "tool_calls",
                }
            ]
        },
        {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}},
    ]

    events = []
    async for event in backend_with(lambda r: sse(chunks)).stream(
        [LLMMessage("user", "hi")], LLMInferOptions()
    ):
        events.append(event)
    kinds = [e.kind for e in events]
    assert kinds[:4] == ["start", "text", "text", "reasoning"] and kinds[-2:] == [
        "tool_call",
        "done",
    ]
    assert kinds.count("start") == 1  # once, with the first delta (what a hedge races on)
    assert events[-2].tool_call.id == "c1" and json.loads(events[-2].tool_call.arguments) == {
        "at": "8:00"
    }
    done = events[-1].result
    assert done.success and done.output == "早晨" and done.reasoning == "thinking"
    assert done.finish_reason == "tool_calls" and done.usage.total_tokens == 7


async def test_stream_tolerates_legacy_full_message_chunk_without_duplicating():
    chunks = [
        {"choices": [{"delta": {"content": "AB"}, "finish_reason": None}]},
        {"choices": [{"message": {"role": "assistant", "content": "AB"}, "finish_reason": "stop"}]},
    ]
    events = [
        e
        async for e in backend_with(lambda r: sse(chunks)).stream(
            [LLMMessage("user", "x")], LLMInferOptions()
        )
    ]
    assert events[-1].result.output == "AB"


async def test_stream_surfaces_base_resp_error_and_http_error():
    err_chunks = [{"base_resp": {"status_code": 1008, "status_msg": "insufficient balance"}}]
    events = [
        e
        async for e in backend_with(lambda r: sse(err_chunks)).stream(
            [LLMMessage("user", "x")], LLMInferOptions()
        )
    ]
    assert events[-1].kind == "done" and events[-1].result.api_code == 1008

    events = [
        e
        async for e in backend_with(lambda r: httpx.Response(401, text="nope")).stream(
            [LLMMessage("user", "x")], LLMInferOptions()
        )
    ]
    assert events == [events[0]] and events[0].result.status_code == 401


async def test_session_slots_and_trace(tmp_path):
    session = LLMSession()
    session.configure_trace(tmp_path / "llm_trace_v1.db")
    missing = await session.infer("fast", [LLMMessage("user", "hi")])
    assert not missing.success and "no backend" in missing.error_message

    session.setup(
        "fast",
        backend_with(
            lambda r: httpx.Response(
                200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
            )
        ),
    )
    assert session.is_ready("fast") and session.slots() == ["fast"]
    result = await session.infer("fast", [LLMMessage("user", "hi")], task="probe")
    assert result.success and result.output == "ok"

    streamed = [e async for e in session.stream("fast", [LLMMessage("user", "hi")])]
    # MockTransport returns the same JSON body; stream parser sees no data: lines -> empty stream failure
    assert streamed[-1].kind == "done"

    rows = session._trace.recent()
    assert len(rows) == 3 and rows[-1]["error"].startswith("no backend")
    assert (
        rows[1]["task"] == "probe"
        and rows[1]["answer"] == "ok"
        and "TESTKEY" not in json.dumps(rows)
    )


def test_content_rejection_detection():
    from sidekick.llm import LLMResult

    assert LLMResult(False, None, "minimax", "x", "m", "k", api_code=1027).is_content_rejected
    assert LLMResult(
        False, None, "openai", "x", "m", "k", error_message="content_policy_violation"
    ).is_content_rejected
    assert not LLMResult(True, "ok", "minimax", "x", "m", "k").is_content_rejected


async def test_pooled_client_is_reused_and_warm_heads_the_origin(monkeypatch):
    """One client per backend and loop (block #71): no TLS handshake per call."""
    seen: list[tuple[str, str]] = []
    made: list[httpx.AsyncClient] = []
    real = httpx.AsyncClient

    def handler(request: httpx.Request):
        seen.append((request.method, str(request.url)))
        if request.method == "HEAD":
            return httpx.Response(404)
        return sse([{"choices": [{"delta": {"content": "好"}, "finish_reason": "stop"}]}])

    def factory(**kwargs):
        client = real(transport=httpx.MockTransport(handler), **kwargs)
        made.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    backend = LLMV1ChatCompletionBackend(CFG)
    await backend.warm()
    await backend.warm(2)  # a hedged slot keeps two connections (block #78)
    assert [m for m, _ in seen] == ["HEAD", "HEAD", "HEAD"]
    seen.clear()
    seen.append(("HEAD", "https://example.test/"))
    for _ in range(2):
        events = [e async for e in backend.stream([LLMMessage("user", "hi")], LLMInferOptions())]
        assert events[-1].result.success and events[-1].result.first_token_ms is not None
    assert len(made) == 1
    assert seen[0] == ("HEAD", "https://example.test/")
    assert [m for m, _ in seen[1:]] == ["POST", "POST"]
    await backend.aclose()
    assert made[0].is_closed


async def test_stream_separates_calls_that_reuse_an_index():
    """Two calls under index 0 with different ids are two calls, not `scheduleschedule`."""

    def handler(request: httpx.Request):
        call = lambda cid, args: {  # noqa: E731
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": cid,
                                "function": {"name": "schedule", "arguments": args},
                            }
                        ]
                    }
                }
            ]
        }
        return sse(
            [
                call("c1", '{"when": "22:00"}'),
                call("c2", '{"when": "23:00"}'),
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            ]
        )

    events = [
        e async for e in backend_with(handler).stream([LLMMessage("user", "hi")], LLMInferOptions())
    ]
    calls = events[-1].result.tool_calls
    assert [(c.id, c.name, c.arguments) for c in calls] == [
        ("c1", "schedule", '{"when": "22:00"}'),
        ("c2", "schedule", '{"when": "23:00"}'),
    ]


async def test_a_tool_only_stream_starts_with_its_first_call_delta():
    """`start` comes with the first delta of any kind, so a hedge does not wait for the end."""
    chunks = [
        {"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "c1",
                                "function": {"name": "look", "arguments": "{}"},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]
    events = [
        e
        async for e in backend_with(lambda r: sse(chunks)).stream(
            [LLMMessage("user", "hi")], LLMInferOptions()
        )
    ]
    assert [e.kind for e in events] == ["start", "tool_call", "done"]
