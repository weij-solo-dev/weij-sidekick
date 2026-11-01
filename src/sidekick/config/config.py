"""sidekick.config.config — ConfigSession: load / save / default / resolve / apply / probe

Overview
    The merge point of the provider framework (AGENTS.md "Provider framework"): a preset plus
    the user's spec plus a resolved region becomes a `ProviderSpec` per slot, which one
    `match api` per service turns into a backend handed to `LLMSession` / `ASRSession` /
    `TTSSession` / `VADSession`. `probe()` exercises the real backends so a bad key, model or
    voice fails at save time, and it resolves a provider's region by trying each candidate.
Design
    Mirrors Scoop's `ConfigSession.apply()` / `resolveRegion()`. Backend construction is the only
    place that branches on `api` (invariant 4); adding a vendor is a preset plus, when its wire
    format is new, one backend class and one `case`. Local models are an ordinary provider
    (`local`) whose model files live under `.derived_data/models/`. Probe outcomes are classified
    into the few things a user can act on: network, credentials, voice, incomplete, or an
    opaque vendor error with its code.
    `release()` unbinds every slot when Bobby's service stops (each session closes the backend
    it drops); the service's start loads and applies the spec again (block #87).
Depends on
    sidekick.log, sidekick.storage, sidekick.audio, sidekick.llm, sidekick.asr, sidekick.tts,
    sidekick.vad.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from sidekick.asr import (
    ASRBackend,
    ASRKeywordBackend,
    ASRKeywordConfiguration,
    ASRMiniMaxBackend,
    ASRMiniMaxConfiguration,
    ASRSenseVoiceBackend,
    ASRSenseVoiceConfiguration,
    ASRSession,
)
from sidekick.audio import AudioClip
from sidekick.llm import (
    LLMBackend,
    LLMInferOptions,
    LLMMessage,
    LLMSession,
    LLMV1ChatCompletionBackend,
    LLMV1ChatCompletionConfiguration,
)
from sidekick.log import Log, mask_secret
from sidekick.storage import StorageSession
from sidekick.tts import (
    TTSBackend,
    TTSMiniMaxSyncBackend,
    TTSMiniMaxSyncConfiguration,
    TTSMiniMaxWSBackend,
    TTSMiniMaxWSConfiguration,
    TTSSession,
)
from sidekick.vad import VADFactory, VADSession, VADSileroConfiguration, VADSileroFactory

from .catalog import load_catalog
from .catalog import provider as load_provider
from .schemas import SERVICES, SLOT_NAMES, ConfigSlot, ConfigSpec, ProviderSpec

ProbeKind = Literal["ok", "network", "credentials", "voice", "incomplete", "http", "api", "unknown"]

CREDENTIAL_API_CODES = frozenset({1004, 401, 2049})
VOICE_API_CODES = frozenset({2504, 3050})
# Which failure to report when no region works: the most actionable one wins.
_PROBE_RANK = {
    "network": 1,
    "unknown": 2,
    "http": 3,
    "api": 4,
    "incomplete": 5,
    "voice": 6,
    "credentials": 7,
}


@dataclass(frozen=True, slots=True)
class ConfigProbeOutcome:
    """What one probe found, in terms a user can act on."""

    slot: str
    kind: ProbeKind
    message: str
    provider: str = ""
    api: str = ""
    model: str = ""
    region: str = ""
    status_code: int | None = None
    api_code: int | None = None
    latency_ms: float | None = None

    @property
    def ok(self) -> bool:
        """Whether the slot works."""
        return self.kind == "ok"


class ConfigSession:
    """Owns the spec file and turns it into live backends."""

    shared: ClassVar[ConfigSession]

    def __init__(self, storage: StorageSession | None = None) -> None:
        self.storage = storage or StorageSession.shared
        self.spec: ConfigSpec | None = None

    # -- spec file -------------------------------------------------------------------------

    @property
    def path(self) -> Any:
        """Where the spec lives."""
        return self.storage.layout.config_path

    def load(self) -> ConfigSpec | None:
        """Read and validate the spec; None when it does not exist yet."""
        data = self.storage.read_json(self.path)
        if isinstance(data, dict) and data.pop("onboarding", None) is not None:
            Log.info("dropped the retired `onboarding` section (block #44: readiness replaces it)")
        body = data.get("body") if isinstance(data, dict) else None
        if isinstance(body, dict):
            retired = [
                key
                for key in ("emotions_dataset", "emotion_sound", "stop_daemon_on_exit")
                if body.pop(key, None) is not None
            ]
            if retired:
                Log.info(
                    f"dropped retired body keys {retired} (blocks #50, #85: Bobby's own"
                    " expressions; a stop of the service turns the robot off)"
                )
        self.spec = ConfigSpec.model_validate(data) if data is not None else None
        Log.info(f"{'loaded' if self.spec else 'no'} spec at {self.path}")
        return self.spec

    def save(self, spec: ConfigSpec) -> None:
        """Validate and persist with mode 0600."""
        self.storage.ensure_layout()
        self.storage.write_json(self.path, spec.model_dump(mode="json"), mode=0o600)
        self.spec = spec
        Log.info(f"saved spec at {self.path}")

    async def telegram_paired(self, chat_id: str, first: bool) -> None:
        """Keep a chat that paired with the one-time code (the Telegram adapter's callback)."""
        current = self.load() or self.spec
        if current is None:
            return
        telegram = current.channels.telegram
        if chat_id not in telegram.allow_chat_ids:
            telegram.allow_chat_ids.append(chat_id)
        telegram.pairing_code = None
        if first and not telegram.owner_chat_id:
            telegram.owner_chat_id = chat_id
        self.save(current)

    def slot_supports(self, service: str, slot: str, capability: str) -> bool:
        """Whether the provider bound to a slot declares a capability (`vision` on `llm.smart`)."""
        bound = self.spec.slot(service, slot) if self.spec is not None else None
        preset = load_catalog().get(bound.provider) if bound is not None else None
        return bool(preset is not None and preset.capabilities.get(capability, False))

    @staticmethod
    def default_spec(provider_id: str = "minimax", language: str = "yue") -> ConfigSpec:
        """A spec binding every cloud slot to `provider_id` and the local slots to `local`."""
        preset = load_provider(provider_id)
        slots: dict[str, dict[str, ConfigSlot]] = {}
        for kind in SERVICES:
            for name in SLOT_NAMES[kind]:
                target = (
                    "local"
                    if (kind == "vad" or (kind == "asr" and name in ("local", "kws")))
                    else provider_id
                )
                if load_provider(target).service(kind) is None:
                    continue
                slots.setdefault(kind, {})[name] = ConfigSlot(provider=target)
        spec = ConfigSpec(slots=slots)
        spec.languages.default = language
        spec.credentials[provider_id] = dict.fromkeys(preset.credential_fields(), "")
        return spec

    PRESETS: ClassVar[tuple[str, ...]] = ("default", "dev", "lite-mac", "wireless", "pi")

    @classmethod
    def preset_spec(
        cls, preset: str, provider_id: str = "minimax", language: str = "yue"
    ) -> ConfigSpec:
        """A spec for a deployment profile (see PLAN.md block #22)."""
        spec = cls.default_spec(provider_id, language)
        if preset in ("default", "dev", "lite-mac"):
            return spec
        if preset == "wireless":
            spec.body.host = "reachy-mini.local"
            spec.body.media_backend = "webrtc"
            spec.body.manage_daemon = False
            return spec
        if preset == "pi":
            spec.interaction.pre_roll_s = 0.7
            spec.perception.poll_hz = 1.0
            spec.automation.heartbeat_minutes = 60
            spec.recording.audio_codec = "flac"
            spec.recording.width, spec.recording.height = 960, 540
            spec.recording.fps, spec.recording.bitrate_kbps = 8.0, 600
            spec.recording.min_free_gb = 5.0
            vad = spec.slot("vad", "primary")
            if vad is not None:
                vad.params["threshold"] = 0.4
            spec.body.preload_datasets = False
            return spec
        raise ValueError(f"unknown preset {preset!r}; one of {cls.PRESETS}")

    @staticmethod
    def profile_of(spec: ConfigSpec) -> str:
        """Which profile a spec looks like."""
        if spec.body.media_backend == "webrtc" or spec.body.host not in ("localhost", "127.0.0.1"):
            return "wireless"
        if spec.perception.poll_hz <= 1.0 and spec.interaction.pre_roll_s <= 0.7:
            return "pi"
        return "lite-mac"

    # -- resolution ------------------------------------------------------------------------

    def resolve(self, spec: ConfigSpec, kind: str, name: str) -> ProviderSpec:
        """Merge preset + slot + credentials + region for one slot."""
        slot = spec.slot(kind, name)
        if slot is None:
            raise KeyError(f"slot {kind}.{name} is not bound")
        preset = load_provider(slot.provider)
        service = preset.service(kind)
        if service is None:
            raise KeyError(f"provider {slot.provider!r} has no {kind} service")
        region = spec.region.get(preset.id) or (preset.regions[0] if preset.regions else "global")
        use_fallback = kind == "tts" and name == "fallback" and service.fallback_api is not None
        api = service.fallback_api if use_fallback and service.fallback_api else service.api
        api = service.slot_api.get(name, api)
        url = service.url_for(region, fallback=use_fallback)
        language = slot.language or spec.languages.default
        params: dict[str, Any] = {
            **service.params,
            **service.language_params(language),
            **service.slot_params.get(name, {}),
            **slot.params,
        }
        if kind == "asr" and name == "kws" and "keywords" not in params:
            params["keywords"] = list(spec.robot.keywords)
        if slot.speed is not None:
            params["speed"] = slot.speed
        model = slot.model or service.models.get(name) or service.model
        extra_body = {
            **service.extra_body,
            **service.slot_extra_body.get(name, {}),
            **service.model_extra_body.get(model, {}),
        }
        entered = spec.credentials.get(preset.id, {})
        credentials = {
            slot_key: entered.get(field, "") for slot_key, field in service.credential_map.items()
        }
        voice = slot.voice or preset.default_voice_for(language)
        return ProviderSpec(
            kind,
            name,
            preset.id,
            api,
            url,
            model,
            params,
            extra_body,
            credentials,
            language,
            voice,
            region,
        )

    # -- backend construction (the only place that branches on api) -----------------------

    def make_llm_backend(self, ps: ProviderSpec) -> LLMBackend:
        """Build the LLM backend for a resolved slot."""
        match ps.api:
            case "v1_chat_completion":
                return LLMV1ChatCompletionBackend(
                    LLMV1ChatCompletionConfiguration(
                        url=ps.url or "",
                        api_key=ps.api_key,
                        model=ps.model,
                        provider=ps.provider,
                        temperature=ps.params.get("temperature"),
                        max_tokens=int(ps.params.get("max_tokens", 2048)),
                        max_tokens_field=str(ps.params.get("max_tokens_field", "max_tokens")),
                        extra_body=ps.extra_body,
                    )
                )
        raise ValueError(f"unknown llm api {ps.api!r}")

    def make_asr_backend(self, ps: ProviderSpec) -> ASRBackend:
        """Build the ASR backend for a resolved slot."""
        match ps.api:
            case "minimax_speech_to_text":
                return ASRMiniMaxBackend(
                    ASRMiniMaxConfiguration(
                        url=ps.url or "", api_key=ps.api_key, model=ps.model, provider=ps.provider
                    )
                )
            case "sherpa_sensevoice":
                return ASRSenseVoiceBackend(
                    ASRSenseVoiceConfiguration(
                        model_dir=self.storage.layout.models_dir / ps.model,
                        language=str(ps.params.get("language", "auto")),
                        use_itn=bool(ps.params.get("use_itn", True)),
                        num_threads=int(ps.params.get("num_threads", 2)),
                        provider=ps.provider,
                    )
                )
            case "sherpa_kws":
                return ASRKeywordBackend(
                    ASRKeywordConfiguration(
                        model_dir=self.storage.layout.models_dir / ps.model,
                        keywords=tuple(str(k) for k in ps.params.get("keywords", [])),
                        keywords_score=float(ps.params.get("keywords_score", 1.5)),
                        keywords_threshold=float(ps.params.get("keywords_threshold", 0.25)),
                        num_threads=int(ps.params.get("num_threads", 1)),
                        provider=ps.provider,
                    )
                )
        raise ValueError(f"unknown asr api {ps.api!r}")

    def make_tts_backend(self, ps: ProviderSpec) -> TTSBackend:
        """Build the TTS backend for a resolved slot."""
        voice_id = ps.voice or ""
        speed = float(ps.params.get("speed", 1.0))
        language_boost = ps.params.get("language_boost")
        emotion = ps.params.get("emotion")
        sample_rate = int(ps.params.get("sample_rate", 16000))
        audio_format = str(ps.params.get("format", "pcm"))
        match ps.api:
            case "minimax_ws":
                return TTSMiniMaxWSBackend(
                    TTSMiniMaxWSConfiguration(
                        url=ps.url or "",
                        api_key=ps.api_key,
                        voice_id=voice_id,
                        model=ps.model,
                        speed=speed,
                        language_boost=str(language_boost) if language_boost else None,
                        emotion=str(emotion) if emotion else None,
                        sample_rate=sample_rate,
                        format=audio_format,
                        provider=ps.provider,
                    )
                )
            case "minimax_sync":
                return TTSMiniMaxSyncBackend(
                    TTSMiniMaxSyncConfiguration(
                        url=ps.url or "",
                        api_key=ps.api_key,
                        voice_id=voice_id,
                        model=ps.model,
                        speed=speed,
                        language_boost=str(language_boost) if language_boost else None,
                        emotion=str(emotion) if emotion else None,
                        sample_rate=sample_rate,
                        format=audio_format,
                        provider=ps.provider,
                    )
                )
        raise ValueError(f"unknown tts api {ps.api!r}")

    def make_vad_backend(self, ps: ProviderSpec) -> VADFactory:
        """Build the VAD detector factory for a resolved slot."""
        match ps.api:
            case "silero_sherpa":
                return VADSileroFactory(
                    VADSileroConfiguration(
                        model_path=self.storage.layout.models_dir / ps.model,
                        threshold=float(ps.params.get("threshold", 0.5)),
                        min_silence_s=float(ps.params.get("min_silence_s", 0.5)),
                        min_speech_s=float(ps.params.get("min_speech_s", 0.25)),
                        max_speech_s=float(ps.params.get("max_speech_s", 20.0)),
                        provider=ps.provider,
                    )
                )
        raise ValueError(f"unknown vad api {ps.api!r}")

    def make_backend(self, ps: ProviderSpec) -> Any:
        """Dispatch on service kind."""
        match ps.kind:
            case "llm":
                return self.make_llm_backend(ps)
            case "asr":
                return self.make_asr_backend(ps)
            case "tts":
                return self.make_tts_backend(ps)
            case "vad":
                return self.make_vad_backend(ps)
        raise ValueError(f"unknown service {ps.kind!r}")

    # -- apply -----------------------------------------------------------------------------

    def apply(self, spec: ConfigSpec | None = None) -> dict[str, str]:
        """Bind every slot in the spec to a backend and point traces at the data directory."""
        spec = spec or self.spec
        if spec is None:
            raise RuntimeError("no spec loaded")
        layout = self.storage.ensure_layout()
        LLMSession.shared.configure_trace(layout.db_path("llm_trace"))
        ASRSession.shared.configure_trace(layout.db_path("asr_trace"))
        TTSSession.shared.configure_trace(layout.db_path("tts_trace"))
        sessions: dict[str, Any] = {
            "llm": LLMSession.shared,
            "asr": ASRSession.shared,
            "tts": TTSSession.shared,
            "vad": VADSession.shared,
        }
        summary: dict[str, str] = {}
        for kind in SERVICES:
            for name in SLOT_NAMES[kind]:
                if spec.slot(kind, name) is None:
                    sessions[kind].setup(name, None)
                    continue
                ps = self.resolve(spec, kind, name)
                sessions[kind].setup(name, self.make_backend(ps))
                summary[f"{kind}.{name}"] = f"{ps.provider}/{ps.api}/{ps.model}" + (
                    f"/{ps.voice}" if ps.voice else ""
                )
        Log.info(f"applied {len(summary)} slot(s): {summary}")
        return summary

    def release(self) -> None:
        """Unbind every slot (the service stopped): pooled connections close, models unload."""
        sessions: dict[str, Any] = {
            "llm": LLMSession.shared,
            "asr": ASRSession.shared,
            "tts": TTSSession.shared,
            "vad": VADSession.shared,
        }
        for kind in SERVICES:
            for name in SLOT_NAMES[kind]:
                sessions[kind].setup(name, None)
        Log.info("released every service slot")

    # -- probe -----------------------------------------------------------------------------

    async def probe(
        self, spec: ConfigSpec, slots: list[str] | None = None, persist_region: bool = True
    ) -> dict[str, ConfigProbeOutcome]:
        """Call every bound slot through its real backend; resolve regions on first success."""
        outcomes: dict[str, ConfigProbeOutcome] = {}
        for kind, name, slot in spec.bound_slots():
            key = f"{kind}.{name}"
            if slots and key not in slots:
                continue
            preset = load_provider(slot.provider)
            if spec.region.get(preset.id):
                candidates = [spec.region[preset.id]]
            else:
                candidates = list(preset.regions) or ["global"]
            # Keys, voices and models are region-bound (MiniMax: api.minimaxi.com vs
            # api.minimax.io), so every candidate region is tried on any failure and the first
            # success wins; a key that is valid nowhere reports the most actionable failure.
            outcome: ConfigProbeOutcome | None = None
            best: ConfigProbeOutcome | None = None
            for region in candidates:
                trial = spec.model_copy(deep=True)
                trial.region[preset.id] = region
                try:
                    ps = self.resolve(trial, kind, name)
                except KeyError as exc:
                    outcome = ConfigProbeOutcome(key, "incomplete", str(exc), slot.provider)
                    break
                missing = [k for k, v in ps.credentials.items() if not v]
                if missing:
                    outcome = ConfigProbeOutcome(
                        key,
                        "incomplete",
                        f"missing credential(s): {missing}",
                        ps.provider,
                        ps.api,
                        ps.model,
                        region,
                    )
                    break
                outcome = await self._probe_one(key, ps)
                Log.info(f"probe {key} region={region}: {outcome.kind} {outcome.message[:80]}")
                if outcome.ok:
                    if persist_region and len(candidates) > 1:
                        spec.region[preset.id] = region
                    break
                if best is None or _PROBE_RANK.get(outcome.kind, 0) > _PROBE_RANK.get(best.kind, 0):
                    best = outcome
            if outcome is not None and not outcome.ok and best is not None:
                outcome = best
            assert outcome is not None
            outcomes[key] = outcome
        return outcomes

    async def _probe_one(self, key: str, ps: ProviderSpec) -> ConfigProbeOutcome:
        started = time.monotonic()
        try:
            match ps.kind:
                case "llm":
                    result = await self.make_llm_backend(ps).infer(
                        [LLMMessage("user", "Reply with the single word: pong")],
                        LLMInferOptions(max_tokens=16),
                    )
                    return self._classify(
                        key,
                        ps,
                        result.success,
                        result.status_code,
                        result.api_code,
                        result.error_message,
                        started,
                        (result.output or "")[:40],
                    )
                case "asr":
                    if ps.api == "sherpa_sensevoice" and not ASRSenseVoiceBackend.model_present(
                        self.storage.layout.models_dir
                    ):
                        return ConfigProbeOutcome(
                            key,
                            "incomplete",
                            "SenseVoice model not downloaded yet (Bobby's start downloads it)",
                            ps.provider,
                            ps.api,
                            ps.model,
                            ps.region,
                        )
                    asr = await self.make_asr_backend(ps).transcribe(
                        AudioClip.silence(1.0), ps.language
                    )
                    return self._classify(
                        key,
                        ps,
                        asr.success,
                        asr.status_code,
                        asr.api_code,
                        asr.error_message,
                        started,
                        (asr.text or "")[:40],
                    )
                case "tts":
                    tts = await self.make_tts_backend(ps).infer("你好")
                    return self._classify(
                        key,
                        ps,
                        tts.success,
                        tts.status_code,
                        tts.api_code,
                        tts.error_message,
                        started,
                        f"{len(tts.audio or b'')} bytes",
                    )
                case "vad":
                    model_path = self.storage.layout.models_dir / ps.model
                    if not model_path.exists():
                        return ConfigProbeOutcome(
                            key,
                            "incomplete",
                            "silero model not downloaded yet (Bobby's start downloads it)",
                            ps.provider,
                            ps.api,
                            ps.model,
                            ps.region,
                        )
                    detector = self.make_vad_backend(ps)()
                    detector.feed(AudioClip.silence(0.5).samples)
                    detector.flush()
                    detector.pop_segments()
                    return ConfigProbeOutcome(
                        key,
                        "ok",
                        "detector ready",
                        ps.provider,
                        ps.api,
                        ps.model,
                        ps.region,
                        latency_ms=_elapsed(started),
                    )
        except Exception as exc:  # a probe must never crash the wizard
            Log.error(f"probe {key} crashed: {exc!r}")
            return ConfigProbeOutcome(
                key,
                "unknown",
                repr(exc),
                ps.provider,
                ps.api,
                ps.model,
                ps.region,
                latency_ms=_elapsed(started),
            )
        return ConfigProbeOutcome(
            key,
            "unknown",
            f"unsupported service {ps.kind}",
            ps.provider,
            ps.api,
            ps.model,
            ps.region,
        )

    @staticmethod
    def _classify(
        key: str,
        ps: ProviderSpec,
        success: bool,
        status_code: int | None,
        api_code: int | None,
        error: str | None,
        started: float,
        detail: str,
    ) -> ConfigProbeOutcome:
        latency = _elapsed(started)

        def outcome(kind: ProbeKind, message: str) -> ConfigProbeOutcome:
            return ConfigProbeOutcome(
                key,
                kind,
                message,
                provider=ps.provider,
                api=ps.api,
                model=ps.model,
                region=ps.region,
                status_code=status_code,
                api_code=api_code,
                latency_ms=latency,
            )

        if success:
            return outcome("ok", detail or "ok")
        message = error or "unknown failure"
        if status_code is None and api_code is None:
            return outcome("network", message)
        if (api_code in CREDENTIAL_API_CODES) or status_code in (401, 403):
            return outcome("credentials", message)
        if api_code in VOICE_API_CODES:
            return outcome("voice", message)
        if api_code is not None:
            return outcome("api", message)
        return outcome("http", message)

    def describe(self, spec: ConfigSpec) -> list[str]:
        """Human-readable slot bindings with masked credentials."""
        lines = []
        for kind, name, _slot in spec.bound_slots():
            try:
                ps = self.resolve(spec, kind, name)
                key = mask_secret(ps.api_key) if ps.credentials else "-"
                lines.append(
                    f"{kind}.{name:<9} {ps.provider}/{ps.api} model={ps.model} region={ps.region} key={key}"
                    + (f" voice={ps.voice}" if ps.voice else "")
                )
            except KeyError as exc:
                lines.append(f"{kind}.{name:<9} ERROR {exc}")
        return lines


def _elapsed(started: float) -> float:
    return (time.monotonic() - started) * 1000.0


ConfigSession.shared = ConfigSession()
