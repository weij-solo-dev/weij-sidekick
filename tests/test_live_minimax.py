"""Live checks against MiniMax and the local models.

Run with `SIDEKICK_LIVE=1 poetry run pytest -m network -s tests/test_live_minimax.py`. They need
`.derived_data/config.json` with a working key (`sidekick init --preset dev`). They also leave a
Cantonese speech sample in `.derived_data/cache/test_speech_yue.wav` that the slow offline tests
reuse.
"""

import asyncio
import json
import os
import time

import pytest

from sidekick.asr import ASRSession
from sidekick.audio import AudioClip, decode_wav
from sidekick.config import ConfigSession
from sidekick.llm import LLMInferOptions, LLMMessage, LLMSession, LLMToolSpec
from sidekick.storage import StorageSession
from sidekick.tts import TTSSession
from sidekick.vad import VADSession

pytestmark = pytest.mark.network

SAMPLE_TEXT = "Bobby，今日天氣好好，我哋一齊去公園玩吖。"


@pytest.fixture(scope="module")
def live():
    if os.environ.get("SIDEKICK_LIVE") != "1":
        pytest.skip("set SIDEKICK_LIVE=1 to run live tests")
    storage = StorageSession()
    StorageSession.shared = storage
    session = ConfigSession(storage)
    spec = session.load()
    if spec is None or not spec.credentials.get("minimax", {}).get("api_key"):
        pytest.skip("no MiniMax key in .derived_data/config.json")
    session.apply(spec)
    return session, spec, storage


def test_probe_all_slots(live):
    session, spec, _ = live
    outcomes = asyncio.run(session.probe(spec))
    for key, outcome in outcomes.items():
        print(
            f"probe {key}: {outcome.kind} {outcome.latency_ms and round(outcome.latency_ms)}ms region={outcome.region} {outcome.message[:60]}"
        )
    assert all(o.ok for o in outcomes.values()), {
        k: o.message for k, o in outcomes.items() if not o.ok
    }
    assert spec.region.get("minimax") in ("domestic", "overseas")
    session.save(spec)


def test_llm_fast_and_smart_and_tools(live):
    system = LLMMessage(
        "system", "你係 Bobby，一個住喺屋企嘅機械人管家。用口語化嘅書面粵語簡短回答。"
    )

    async def run():
        t0 = time.monotonic()
        fast = await LLMSession.shared.infer(
            "fast",
            [system, LLMMessage("user", "早晨，今日係星期幾？")],
            LLMInferOptions(max_tokens=200),
            task="live",
        )
        fast_ms = (time.monotonic() - t0) * 1000
        print(f"fast: {fast_ms:.0f}ms finish={fast.finish_reason} -> {fast.output!r}")
        assert fast.success and fast.output

        first_token = None
        chunks = []
        t0 = time.monotonic()
        async for event in LLMSession.shared.stream(
            "fast",
            [system, LLMMessage("user", "用一句話介紹你自己。")],
            LLMInferOptions(max_tokens=200),
        ):
            if event.kind == "text":
                if first_token is None:
                    first_token = (time.monotonic() - t0) * 1000
                chunks.append(event.text)
            elif event.kind == "done":
                assert event.result is not None and event.result.success, event.result
        print(
            f"fast stream: first_token={first_token and round(first_token)}ms total={(time.monotonic() - t0) * 1000:.0f}ms -> {''.join(chunks)!r}"
        )
        assert chunks and first_token is not None

        t0 = time.monotonic()
        smart = await LLMSession.shared.infer(
            "smart",
            [system, LLMMessage("user", "用兩句話解釋為什麼天空係藍色。")],
            LLMInferOptions(max_tokens=400),
            task="live",
        )
        print(
            f"smart: {(time.monotonic() - t0) * 1000:.0f}ms finish={smart.finish_reason} reasoning={len(smart.reasoning or '')}chars -> {(smart.output or '')[:80]!r}"
        )
        assert smart.success and smart.output

        tool = LLMToolSpec(
            "schedule",
            "Create a reminder for the user",
            {
                "type": "object",
                "properties": {
                    "when": {"type": "string", "description": "ISO time or natural language"},
                    "text": {"type": "string"},
                },
                "required": ["when", "text"],
            },
        )
        result = await LLMSession.shared.infer(
            "fast",
            [system, LLMMessage("user", "八點提我食藥。")],
            LLMInferOptions(tools=(tool,), max_tokens=200),
            task="live-tools",
        )
        print(
            f"tools: finish={result.finish_reason} calls={[(c.name, c.arguments) for c in result.tool_calls]} output={result.output!r}"
        )
        assert result.success and result.tool_calls and result.tool_calls[0].name == "schedule"
        json.loads(result.tool_calls[0].arguments)

    asyncio.run(run())


def test_tts_http_saves_cantonese_sample(live):
    _, _, storage = live

    async def run():
        t0 = time.monotonic()
        result = await TTSSession.shared.infer("fallback", SAMPLE_TEXT, task="live")
        print(
            f"tts http: {(time.monotonic() - t0) * 1000:.0f}ms bytes={len(result.audio or b'')} usage={result.usage_chars} err={result.error_message}"
        )
        assert result.success and result.audio
        clip = result.to_clip()
        assert clip is not None and clip.duration_s > 1.5, clip.duration_s
        path = storage.layout.cache_dir / "test_speech_yue.wav"
        path.write_bytes(clip.to_wav_bytes())
        print(f"saved {path} ({clip.duration_s:.2f}s)")

    asyncio.run(run())


def test_tts_ws_streaming_turn(live):
    async def run():
        t0 = time.monotonic()
        stream = await TTSSession.shared.open_stream("primary")
        connect_ms = (time.monotonic() - t0) * 1000
        kinds = []
        total = 0
        first_audio = None

        async def collect():
            nonlocal total, first_audio
            async for event in stream.events():
                kinds.append(event.kind)
                if event.kind == "audio":
                    total += len(event.audio)
                    if first_audio is None:
                        first_audio = (time.monotonic() - t1) * 1000
                if event.kind == "flushed":
                    break

        t1 = time.monotonic()
        collector = asyncio.create_task(collect())
        for fragment in [
            "Bobby",
            "，",
            "今日",
            "天氣",
            "好好",
            "。",
            "我哋",
            "一齊",
            "去公園",
            "玩吖。",
        ]:
            await stream.send(fragment)
            await asyncio.sleep(0.05)
        await stream.flush()
        await asyncio.wait_for(collector, timeout=30)
        await stream.finish()
        await stream.aclose()
        print(
            f"tts ws: connect={connect_ms:.0f}ms first_audio={first_audio and round(first_audio)}ms turn={(time.monotonic() - t1) * 1000:.0f}ms bytes={total} events={kinds}"
        )
        assert total > 16000 and "sentence_start" in kinds and kinds[-1] == "flushed"

    asyncio.run(run())


def test_asr_cloud_and_local_on_sample(live):
    _, _, storage = live
    path = storage.layout.cache_dir / "test_speech_yue.wav"
    assert path.exists(), "run the TTS test first"
    clip = decode_wav(path.read_bytes())

    async def run():
        for language in ("yue", None):
            t0 = time.monotonic()
            cloud = await ASRSession.shared.transcribe("primary", clip, language, task="live")
            print(
                f"asr minimax lang={language}: {(time.monotonic() - t0) * 1000:.0f}ms -> {cloud.text!r} err={cloud.error_message}"
            )
            assert cloud.success and cloud.text
            assert any(word in cloud.text for word in ("天氣", "天气", "公園", "公园"))
        t0 = time.monotonic()
        local = await ASRSession.shared.transcribe("local", clip, None, task="live")
        print(
            f"asr sensevoice: {(time.monotonic() - t0) * 1000:.0f}ms lang={local.language} -> {local.text!r}"
        )
        assert local.success and local.text
        assert any(word in local.text for word in ("天氣", "天气", "公園", "公园"))

    asyncio.run(run())


def test_vad_on_sample(live):
    _, _, storage = live
    path = storage.layout.cache_dir / "test_speech_yue.wav"
    clip = decode_wav(path.read_bytes())
    detector = VADSession.shared.create("primary")
    padded = AudioClip.silence(0.6).concat(clip).concat(AudioClip.silence(1.0))
    detector.feed(padded.samples)
    detector.flush()
    segments = detector.pop_segments()
    print(
        f"vad: {len(segments)} segment(s): {[(round(s.start_s, 2), round(s.end_s, 2)) for s in segments]} sample={clip.duration_s:.2f}s"
    )
    assert segments and 0.3 < segments[0].start_s < 0.9
    assert sum(s.clip.duration_s for s in segments) > 0.6 * clip.duration_s
