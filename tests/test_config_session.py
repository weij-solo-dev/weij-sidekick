import json

import pytest

from sidekick.asr import ASRSession
from sidekick.config import (
    ROBOT_ALIASES,
    ROBOT_KEYWORDS,
    ROBOT_NAME,
    ConfigSession,
    ConfigSpec,
    load_catalog,
    provider,
)
from sidekick.llm import LLMSession, LLMV1ChatCompletionBackend
from sidekick.storage import StorageSession
from sidekick.tts import TTSMiniMaxSyncBackend, TTSMiniMaxWSBackend, TTSSession
from sidekick.vad import VADSession, VADSileroFactory


def test_catalog_loads_and_validates_presets():
    catalog = load_catalog()
    assert list(catalog)[:2] == ["minimax", "local"]
    minimax = provider("minimax")
    assert minimax.credential_fields() == ["api_key"]
    assert minimax.llm.url_for("overseas").startswith("https://api.minimax.io")
    assert minimax.llm.url_for("domestic").startswith("https://api.minimaxi.com")
    assert minimax.tts.language_params("yue") == {"language_boost": "Chinese,Yue"}
    assert minimax.tts.language_params("ja") == {"language_boost": "auto"}
    assert minimax.default_voice_for("yue").startswith("Cantonese")
    assert next(v.id for v in minimax.voices_for("yue")) == "Cantonese_crisp_news_anchor_vv2"
    local = provider("local")
    assert local.llm is None and local.vad.api == "silero_sherpa"
    with pytest.raises(KeyError):
        provider("nope")


def test_default_spec_binds_every_slot():
    spec = ConfigSession.default_spec()
    bound = {f"{k}.{n}": s.provider for k, n, s in spec.bound_slots()}
    assert bound == {
        "llm.fast": "minimax",
        "llm.smart": "minimax",
        "asr.primary": "minimax",
        "asr.local": "local",
        "asr.kws": "local",
        "tts.primary": "minimax",
        "tts.fallback": "minimax",
        "vad.primary": "local",
    }
    assert spec.languages.default == "zh" and spec.robot.name == "Banana"  # block #94
    assert spec.credentials == {"minimax": {"api_key": ""}}


def test_resolve_merges_preset_slot_and_credentials(tmp_path):
    session = ConfigSession(StorageSession(tmp_path))
    spec = ConfigSession.default_spec()
    spec.credentials["minimax"]["api_key"] = "sk-cp-TESTKEY0000000000001234"

    fast = session.resolve(spec, "llm", "fast")
    assert (
        fast.api == "v1_chat_completion"
        and fast.model == "MiniMax-M3.1-Flash"
        and fast.region == "overseas"
    )
    assert (
        fast.extra_body == {"reasoning_effort": "minimal"}  # block #71: Flash, least reasoning
        and fast.params["max_tokens_field"] == "max_completion_tokens"
    )
    spec.slots["llm"]["fast"] = spec.slots["llm"]["fast"].model_copy(update={"model": "MiniMax-M3"})
    m3 = session.resolve(spec, "llm", "fast")  # a model's own extras win, whatever the slot
    assert m3.extra_body == {"reasoning_effort": "minimal", "thinking": {"type": "disabled"}}
    spec.slots["llm"]["fast"] = spec.slots["llm"]["fast"].model_copy(update={"model": None})
    assert fast.api_key.startswith("sk-cp-") and fast.url.endswith("/v1/chat/completions")
    smart = session.resolve(spec, "llm", "smart")
    assert smart.model == "MiniMax-M3.1-Flash" and smart.extra_body == {
        "reasoning_effort": "medium"
    }

    tts = session.resolve(spec, "tts", "primary")
    assert (
        tts.api == "minimax_ws"
        and tts.url.startswith("wss://")
        and tts.voice == "Chinese (Mandarin)_Warm_Girl"  # Mandarin by default (block #94)
    )
    assert tts.params["language_boost"] == "Chinese" and tts.params["sample_rate"] == 16000
    fallback = session.resolve(spec, "tts", "fallback")
    assert (
        fallback.api == "minimax_sync"
        and fallback.url.startswith("https://")
        and fallback.url.endswith("/v1/t2a_v2")
    )

    spec.region["minimax"] = "domestic"
    spec.slots["tts"]["primary"].voice = "Cantonese_CuteGirl"
    spec.slots["tts"]["primary"].speed = 1.2
    spec.slots["llm"]["fast"].model = "MiniMax-M3.1-Flash"
    tts = session.resolve(spec, "tts", "primary")
    assert (
        tts.url.startswith("wss://api.minimaxi.com")
        and tts.voice == "Cantonese_CuteGirl"
        and tts.params["speed"] == 1.2
    )
    assert session.resolve(spec, "llm", "fast").model == "MiniMax-M3.1-Flash"

    local = session.resolve(spec, "asr", "local")
    assert local.api == "sherpa_sensevoice" and local.credentials == {} and local.region == "global"
    assert local.params["language"] == "zh"  # a Mandarin household tells SenseVoice so
    with pytest.raises(KeyError):
        session.resolve(ConfigSpec(), "llm", "fast")


def test_apply_binds_sessions_and_traces(tmp_path):
    storage = StorageSession(tmp_path)
    session = ConfigSession(storage)
    spec = ConfigSession.default_spec()
    spec.credentials["minimax"]["api_key"] = "k" * 24
    summary = session.apply(spec)
    assert summary["llm.fast"].startswith("minimax/v1_chat_completion/MiniMax-M3.1-Flash")
    assert isinstance(LLMSession.shared.backend("fast"), LLMV1ChatCompletionBackend)
    assert isinstance(TTSSession.shared.backend("primary"), TTSMiniMaxWSBackend)
    assert isinstance(TTSSession.shared.backend("fallback"), TTSMiniMaxSyncBackend)
    assert TTSSession.shared.supports_streaming(
        "primary"
    ) and not TTSSession.shared.supports_streaming("fallback")
    assert ASRSession.shared.slots() == ["kws", "local", "primary"] and VADSession.shared.is_ready(
        "primary"
    )
    assert isinstance(VADSession.shared._slots["primary"], VADSileroFactory)
    assert (tmp_path / "llm_trace_v1.db").exists() and (tmp_path / "tts_trace_v1.db").exists()


def test_save_load_round_trip_and_masking(tmp_path):
    storage = StorageSession(tmp_path)
    session = ConfigSession(storage)
    assert session.load() is None
    spec = ConfigSession.default_spec()
    spec.credentials["minimax"]["api_key"] = "sk-cp-SECRET000000000000ABCD"
    session.save(spec)
    assert oct((tmp_path / "config.json").stat().st_mode & 0o777) == "0o600"
    loaded = ConfigSession(storage).load()
    assert loaded == spec
    masked = json.dumps(loaded.masked())
    assert "SECRET" not in masked and "ABCD(" in masked
    assert any("key=sk-c" in line for line in session.describe(loaded))


class _StubResult:
    def __init__(
        self, success, status_code=None, api_code=None, error=None, output="pong", audio=b"\x00\x00"
    ):
        self.success = success
        self.status_code = status_code
        self.api_code = api_code
        self.error_message = error
        self.output = output
        self.text = output
        self.audio = audio


async def test_probe_classifies_and_resolves_region(tmp_path, monkeypatch):
    storage = StorageSession(tmp_path)
    session = ConfigSession(storage)
    spec = ConfigSession.default_spec()
    spec.credentials["minimax"]["api_key"] = "k" * 24
    calls = []

    class StubLLM:
        def __init__(self, url):
            self.url = url

        async def infer(self, messages, options):
            calls.append(self.url)
            if "api.minimax.io" in self.url:
                return _StubResult(False, None, None, "transport: ConnectError")
            return _StubResult(True, 200)

    monkeypatch.setattr(session, "make_llm_backend", lambda ps: StubLLM(ps.url))
    outcomes = await session.probe(spec, ["llm.fast"])
    assert outcomes["llm.fast"].ok and outcomes["llm.fast"].region == "domestic"
    assert spec.region["minimax"] == "domestic" and len(calls) == 2

    class BadKey:
        async def infer(self, messages, options):
            return _StubResult(False, 200, 1004, "api status 1004: invalid api key")

    spec.region.clear()
    monkeypatch.setattr(session, "make_llm_backend", lambda ps: BadKey())
    outcomes = await session.probe(spec, ["llm.smart"])
    assert outcomes["llm.smart"].kind == "credentials" and "minimax" not in spec.region

    class RegionBoundKey:
        def __init__(self, url):
            self.url = url

        async def infer(self, messages, options):
            if "api.minimax.io" in self.url:
                return _StubResult(False, 401, None, "invalid api key (2049)")
            return _StubResult(True, 200)

    monkeypatch.setattr(session, "make_llm_backend", lambda ps: RegionBoundKey(ps.url))
    outcomes = await session.probe(spec, ["llm.fast"])
    assert outcomes["llm.fast"].ok and spec.region["minimax"] == "domestic"
    spec.region.clear()

    class BadVoice:
        async def infer(self, text):
            return _StubResult(False, 200, 2504, "voice not exist")

    monkeypatch.setattr(session, "make_tts_backend", lambda ps: BadVoice())
    outcomes = await session.probe(spec, ["tts.fallback"])
    assert outcomes["tts.fallback"].kind == "voice"

    spec.credentials["minimax"]["api_key"] = ""
    outcomes = await session.probe(spec, ["asr.primary"])
    assert (
        outcomes["asr.primary"].kind == "incomplete"
        and "api_key" in outcomes["asr.primary"].message
    )


def test_a_home_written_under_the_retired_name_takes_the_new_one(tmp_path):
    """Block #94: the name is fixed by the code. A home whose config still says "Bobby" gets
    the new name with its aliases and keyword lines; everything else in it is kept."""
    session = ConfigSession(StorageSession(tmp_path))
    old = ConfigSession.default_spec().model_dump(mode="json")
    old["robot"] = {
        "name": "Bobby",
        "aliases": ["bobby", "bob", "波比", "芭比"],
        "keywords": ["B AA1 B IY0 @bobby", "b ō b ǐ @波比"],
    }
    old["interaction"]["session_timeout_s"] = 11.0
    session.path.parent.mkdir(parents=True, exist_ok=True)
    session.path.write_text(json.dumps(old, ensure_ascii=False))
    spec = session.load()
    assert spec is not None and spec.robot.name == ROBOT_NAME == "Banana"
    assert spec.robot.aliases == list(ROBOT_ALIASES) and "bobby" not in spec.robot.aliases
    assert spec.robot.keywords == list(ROBOT_KEYWORDS)
    assert spec.interaction.session_timeout_s == 11.0  # the rest of the home is untouched
    kws = session.resolve(spec, "asr", "kws")
    assert kws.params["keywords"] == list(ROBOT_KEYWORDS)
    # the spotter is tuned for the three-syllable name (block #94)
    assert kws.params["keywords_score"] == 2.0 and kws.params["keywords_threshold"] == 0.2
    # a home already on the name keeps the aliases its owner tuned on the Voice tab
    session.save(spec)
    tuned = json.loads(session.path.read_text())
    tuned["robot"]["aliases"] = ["banana", "把娜娜", "班娜娜"]
    session.path.write_text(json.dumps(tuned, ensure_ascii=False))
    assert session.load().robot.aliases == ["banana", "把娜娜", "班娜娜"]


def test_voices_and_the_recogniser_follow_the_household_language(tmp_path):
    """Block #94: the owner chose 普通话 on the dashboard and the robot went on in the Cantonese
    voice both TTS slots carried; SenseVoice in `auto` took some Mandarin for Cantonese."""
    session = ConfigSession(StorageSession(tmp_path))
    spec = ConfigSession.default_spec(language="yue")
    for name in ("primary", "fallback"):
        spec.slots["tts"][name].voice = "Cantonese_crisp_news_anchor_vv2"
    assert ConfigSession.drop_foreign_voices(spec) == []  # Cantonese voices in a Cantonese home
    assert session.resolve(spec, "asr", "local").params["language"] == "auto"
    mandarin = ConfigSession.with_language(spec, "zh")
    assert spec.languages.default == "yue" and spec.slots["tts"]["primary"].voice  # a copy
    assert mandarin.languages.default == "zh"
    assert mandarin.slots["tts"]["primary"].voice is None
    assert mandarin.slots["tts"]["fallback"].voice is None
    tts = session.resolve(mandarin, "tts", "primary")
    assert tts.voice == "Chinese (Mandarin)_Warm_Girl" and tts.params["language_boost"] == "Chinese"
    assert session.resolve(mandarin, "asr", "local").params["language"] == "zh"
    assert session.resolve(mandarin, "asr", "kws").params["keywords"] == list(ROBOT_KEYWORDS)
    # a voice of the new language stays; so does one the catalog does not list (the owner's own)
    mandarin.slots["tts"]["primary"].voice = "Chinese (Mandarin)_Gentleman"
    mandarin.slots["tts"]["fallback"].voice = "my_cloned_voice"
    again = ConfigSession.with_language(mandarin, "zh", ["zh", "en", "yue"])
    assert again.slots["tts"]["primary"].voice == "Chinese (Mandarin)_Gentleman"
    assert again.slots["tts"]["fallback"].voice == "my_cloned_voice"
    assert again.languages.order == ["zh", "en", "yue"]
    # a home left half-switched (a Mandarin household, a Cantonese voice) heals when loaded
    half = ConfigSession.default_spec()
    half.slots["tts"]["primary"].voice = "Cantonese_crisp_news_anchor_vv2"
    session.save(half)
    assert session.load().slots["tts"]["primary"].voice is None
