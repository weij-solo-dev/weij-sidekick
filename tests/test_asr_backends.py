import json

import httpx
import pytest

from sidekick.asr import (
    ASRMiniMaxBackend,
    ASRMiniMaxConfiguration,
    ASRSenseVoiceBackend,
    ASRSession,
)
from sidekick.audio import AudioClip, decode_wav
from sidekick.storage import StorageSession

CFG = ASRMiniMaxConfiguration(
    url="https://example.test/v1/speech_to_text", api_key="sk-cp-TESTKEY0000000000001234"
)


def backend_with(handler):
    return ASRMiniMaxBackend(CFG, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_minimax_transcribe_sends_multipart_wav_and_language_header():
    seen = {}

    def handler(request: httpx.Request):
        seen["language"] = request.headers.get("language")
        seen["auth"] = request.headers["authorization"]
        content_type = request.headers["content-type"]
        assert content_type.startswith("multipart/form-data")
        boundary = content_type.split("boundary=")[1].encode()
        parts = request.content.split(b"--" + boundary)
        file_part = next(p for p in parts if b'name="file"' in p)
        assert b"audio/wav" in file_part and b"RIFF" in file_part
        wav = file_part.split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n")
        seen["clip"] = decode_wav(wav)
        model_part = next(p for p in parts if b'name="model"' in p)
        assert b"asr-1.0" in model_part
        return httpx.Response(
            200, json={"text": "Bobby，今日天氣點呀", "duration": 1.5, "trace_id": "t"}
        )

    result = await backend_with(handler).transcribe(AudioClip.silence(1.5), language="yue")
    assert result.success and result.text.startswith("Bobby")
    assert result.language == "yue" and result.duration_s == 1.5
    assert seen["language"] == "yue" and seen["auth"].startswith("Bearer ")
    assert abs(seen["clip"].duration_s - 1.5) < 1e-6 and seen["clip"].sample_rate == 16000


async def test_minimax_omits_language_header_for_auto():
    def handler(request):
        assert "language" not in request.headers
        return httpx.Response(200, json={"text": "", "duration": 0.5})

    result = await backend_with(handler).transcribe(AudioClip.silence(0.5))
    assert result.success and result.text == "" and result.language is None


async def test_minimax_error_shapes():
    def openai_style(request):
        return httpx.Response(
            401,
            json={
                "type": "error",
                "error": {
                    "type": "authentication_error",
                    "message": "invalid api key",
                    "http_code": 401,
                },
            },
        )

    result = await backend_with(openai_style).transcribe(AudioClip.silence(0.2))
    assert (
        not result.success
        and result.status_code == 401
        and result.api_code == 401
        and "invalid api key" in result.error_message
    )

    def base_resp(request):
        return httpx.Response(
            200, json={"base_resp": {"status_code": 1004, "status_msg": "auth failed"}}
        )

    result = await backend_with(base_resp).transcribe(AudioClip.silence(0.2))
    assert not result.success and result.api_code == 1004

    def boom(request):
        raise httpx.ReadTimeout("slow")

    result = await backend_with(boom).transcribe(AudioClip.silence(0.2))
    assert not result.success and "transport" in result.error_message


async def test_session_slots_and_trace(tmp_path):
    session = ASRSession()
    session.configure_trace(tmp_path / "asr_trace_v1.db")
    missing = await session.transcribe("primary", AudioClip.silence(0.1))
    assert not missing.success
    session.setup(
        "primary",
        backend_with(lambda r: httpx.Response(200, json={"text": "hello", "duration": 0.1})),
    )
    ok = await session.transcribe("primary", AudioClip.silence(0.1), language="en", task="probe")
    assert ok.success and ok.text == "hello"
    rows = session._trace.recent()
    assert rows[0]["text"] == "hello" and rows[0]["language"] == "en" and rows[0]["task"] == "probe"
    assert "TESTKEY" not in json.dumps(rows)


@pytest.mark.slow
async def test_sensevoice_local_model_decodes(tmp_path):
    from sidekick.asr import ASRSenseVoiceConfiguration
    from sidekick.asr.sherpa_sensevoice import MODEL_NAME

    models = StorageSession().layout.models_dir
    if not ASRSenseVoiceBackend.model_present(models):
        pytest.skip("SenseVoice model not downloaded")
    backend = ASRSenseVoiceBackend(ASRSenseVoiceConfiguration(models / MODEL_NAME))
    silence = await backend.transcribe(AudioClip.silence(1.0))
    # SenseVoice hallucinates a filler ("嗯") on pure silence; VAD gating upstream is what keeps
    # silence out of the recognizer, so only the plumbing is asserted here.
    assert silence.success and len(silence.text) <= 2 and silence.api == "sherpa_sensevoice"
    sample = StorageSession().layout.cache_dir / "test_speech_yue.wav"
    if sample.exists():
        spoken = await backend.transcribe(decode_wav(sample.read_bytes()))
        assert spoken.success and spoken.text
        assert spoken.language in ("yue", "zh", "en")
