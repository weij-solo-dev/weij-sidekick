import asyncio
import json

import httpx
import pytest
from websockets.asyncio.server import serve

from sidekick.audio import AudioClip
from sidekick.tts import (
    TTSMiniMaxSyncBackend,
    TTSMiniMaxSyncConfiguration,
    TTSMiniMaxWSBackend,
    TTSMiniMaxWSConfiguration,
    TTSSession,
)

SYNC_CFG = TTSMiniMaxSyncConfiguration(
    url="https://example.test/v1/t2a_v2",
    api_key="sk-cp-TESTKEY0000000000001234",
    voice_id="Cantonese_crisp_news_anchor_vv2",
    language_boost="Chinese,Yue",
)


def sync_backend(handler):
    return TTSMiniMaxSyncBackend(
        SYNC_CFG, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


async def test_sync_builds_body_and_decodes_pcm():
    pcm = AudioClip.silence(0.25).to_pcm16_bytes()
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": {"audio": pcm.hex(), "status": 2},
                "extra_info": {"usage_characters": 4, "audio_sample_rate": 16000},
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
        )

    result = await sync_backend(handler).infer("早晨呀")
    assert result.success and result.audio == pcm and result.usage_chars == 4
    clip = result.to_clip()
    assert clip is not None and abs(clip.duration_s - 0.25) < 1e-6
    body = seen["body"]
    assert body["audio_setting"] == {"format": "pcm", "sample_rate": 16000, "channel": 1}
    assert body["language_boost"] == "Chinese,Yue" and body["voice_setting"]["voice_id"].startswith(
        "Cantonese"
    )
    assert body["output_format"] == "hex" and body["model"] == "speech-2.8-turbo"


async def test_sync_reports_base_resp_and_http_errors():
    result = await sync_backend(
        lambda r: httpx.Response(
            200, json={"base_resp": {"status_code": 2504, "status_msg": "voice not exist"}}
        )
    ).infer("x")
    assert not result.success and result.api_code == 2504
    result = await sync_backend(lambda r: httpx.Response(500, text="boom")).infer("x")
    assert not result.success and result.status_code == 500
    result = await sync_backend(
        lambda r: httpx.Response(
            200, json={"data": {"audio": "zz"}, "base_resp": {"status_code": 0}}
        )
    ).infer("x")
    assert not result.success and "hex" in result.error_message


def fake_minimax_server(behaviour="ok"):
    pcm = AudioClip.silence(0.05).to_pcm16_bytes().hex()
    log = []

    async def handler(ws):
        await ws.send(
            json.dumps(
                {
                    "event": "connected_success",
                    "session_id": "s",
                    "base_resp": {"status_code": 0, "status_msg": "success"},
                }
            )
        )
        buffer = ""
        async for raw in ws:
            msg = json.loads(raw)
            event = msg["event"]
            log.append(msg)
            if event == "task_start":
                if behaviour == "auth_fail":
                    await ws.send(
                        json.dumps(
                            {
                                "event": "task_failed",
                                "base_resp": {"status_code": 1004, "status_msg": "invalid api key"},
                            }
                        )
                    )
                    await ws.close()
                    return
                await ws.send(
                    json.dumps(
                        {
                            "event": "task_started",
                            "base_resp": {"status_code": 0, "status_msg": "success"},
                        }
                    )
                )
            elif event == "task_continue":
                buffer += msg["text"]
            elif event in ("task_flush", "task_finish"):
                if buffer:
                    await ws.send(json.dumps({"event": "sentence_start"}))
                    await ws.send(
                        json.dumps(
                            {
                                "event": "task_continued",
                                "data": {"audio": pcm},
                                "is_final": False,
                                "extra_info": {"usage_characters": len(buffer)},
                                "base_resp": {"status_code": 0},
                            }
                        )
                    )
                    await ws.send(
                        json.dumps(
                            {
                                "event": "task_continued",
                                "data": {"audio": ""},
                                "is_final": True,
                                "base_resp": {"status_code": 0},
                            }
                        )
                    )
                    await ws.send(json.dumps({"event": "sentence_end"}))
                    buffer = ""
                if event == "task_flush":
                    await ws.send(
                        json.dumps({"event": "task_flushed", "base_resp": {"status_code": 0}})
                    )
                else:
                    await ws.send(
                        json.dumps({"event": "task_finished", "base_resp": {"status_code": 0}})
                    )
                    await ws.close()
                    return
            elif event == "task_cancel":
                buffer = ""
                await ws.send(
                    json.dumps({"event": "task_canceled", "base_resp": {"status_code": 0}})
                )

    return handler, log


async def test_ws_infer_round_trip():
    handler, log = fake_minimax_server()
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        cfg = TTSMiniMaxWSConfiguration(
            url=f"ws://127.0.0.1:{port}/ws/v1/t2a_v2_bidi",
            api_key="sk-cp-TESTKEY0000000000001234",
            voice_id="v",
            language_boost="Chinese,Yue",
        )
        result = await TTSMiniMaxWSBackend(cfg).infer("早晨呀。")
    assert result.success and result.api == "minimax_ws" and result.format == "pcm"
    assert (
        len(result.audio) == len(AudioClip.silence(0.05).to_pcm16_bytes())
        and result.usage_chars == 4
    )
    assert log[0]["event"] == "task_start" and log[0]["language_boost"] == "Chinese,Yue"
    assert log[0]["audio_setting"]["sample_rate"] == 16000
    assert [m["event"] for m in log[1:]] == ["task_continue", "task_finish"]


async def test_ws_stream_flush_cancel_finish_events():
    handler, _log = fake_minimax_server()
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        cfg = TTSMiniMaxWSConfiguration(
            url=f"ws://127.0.0.1:{port}/", api_key="k" * 20, voice_id="v"
        )
        stream = await TTSMiniMaxWSBackend(cfg).open_stream()
        kinds = []

        async def collect():
            async for event in stream.events():
                kinds.append(event.kind)

        collector = asyncio.create_task(collect())
        await stream.send("第一句。")
        await stream.flush()
        await asyncio.sleep(0.2)
        await stream.send("要取消嘅")
        await stream.cancel()
        await asyncio.sleep(0.1)
        await stream.send("最後一句。")
        await stream.finish()
        await asyncio.wait_for(collector, timeout=5)
        await stream.aclose()
    assert kinds[:4] == ["sentence_start", "audio", "sentence_end", "flushed"]
    assert "canceled" in kinds and kinds[-1] == "finished"
    assert kinds.count("audio") == 2 and stream.audio_bytes > 0


async def test_ws_start_failure_becomes_result():
    handler, _ = fake_minimax_server("auth_fail")
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        cfg = TTSMiniMaxWSConfiguration(
            url=f"ws://127.0.0.1:{port}/", api_key="k" * 20, voice_id="v"
        )
        result = await TTSMiniMaxWSBackend(cfg).infer("x")
    assert not result.success and "1004" in result.error_message


async def test_ws_connection_refused_becomes_result():
    cfg = TTSMiniMaxWSConfiguration(
        url="ws://127.0.0.1:1/", api_key="k" * 20, voice_id="v", connect_timeout_s=2
    )
    result = await TTSMiniMaxWSBackend(cfg).infer("x")
    assert not result.success and "start" in result.error_message


async def test_session_slots_trace_and_streaming_flag(tmp_path):
    session = TTSSession()
    session.configure_trace(tmp_path / "tts_trace_v1.db")
    pcm = AudioClip.silence(0.5).to_pcm16_bytes()
    session.setup(
        "fallback",
        sync_backend(
            lambda r: httpx.Response(
                200, json={"data": {"audio": pcm.hex()}, "base_resp": {"status_code": 0}}
            )
        ),
    )
    assert not session.supports_streaming("fallback") and not session.is_ready("primary")
    assert TTSSession().voice() is None  # nothing bound: no voice to name
    assert session.voice() == f"minimax/{session.backend('fallback').configuration.voice_id}"
    result = await session.infer("fallback", "你好", task="probe")
    assert result.success
    row = session._trace.recent()[0]
    assert (
        row["input_chars"] == 2 and abs(row["audio_ms"] - 500.0) < 1e-6 and row["task"] == "probe"
    )
    with pytest.raises(RuntimeError):
        await session.open_stream("fallback")
