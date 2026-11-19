"""sidekick.config.schemas — provider presets, the user spec, and the resolved provider spec

Overview
    Three shapes: `ConfigProvider` (a bundled `provider_*.json` preset, everything fixed about a
    vendor), `ConfigSpec` (what the user chose: credentials, region, languages, slot bindings,
    robot, body, channels, interaction, …), and `ProviderSpec` (the merge of the two
    for one slot, consumed by `make_*_backend`).
Design
    Pydantic models because presets and the spec are user-editable JSON that must be validated
    with clear errors. Language keys are `yue` / `zh` / `en` project-wide. Slot names are fixed:
    `llm.fast`, `llm.smart`, `asr.primary`, `asr.local`, `tts.primary`, `tts.fallback`,
    `vad.primary`. The preset's `models` map gives a per-slot default model; `slot_extra_body`
    gives per-slot request extras (MiniMax: minimal reasoning for `fast`) and `model_extra_body`
    the extras a model needs whatever the slot (MiniMax-M3: thinking off), applied last. Every user-facing field
    carries a `description`: the dashboard renders its parameter cards from the JSON schema
    (`GET /api/config/schema`), so the text here is what the operator reads next to the control.
Depends on
    pydantic.

See Also
--------
    AGENTS.md "Provider framework".

"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# The robot's name is its wake name and is fixed here, not per home (block #9). It was "Bobby"
# until block #94; a home that still carries another name gets these on load.
ROBOT_NAME = "Banana"
# How SenseVoice spelled "banana" from Mandarin and English voices (block #94): Latin capitals
# with a doubled or dropped letter, now and then the Chinese syllables. Aliases are matched as
# they are written; only the name itself is matched loosely.
ROBOT_ALIASES = (
    "banana",
    "bananna",
    "ananna",
    "banaa",
    "baana",
    "bnaa",
    "把娜娜",
    "巴娜娜",
    "芭娜娜",
    "爸娜娜",
    "吧娜娜",
)
# Keyword-spotter lines: the lexicon's phones and the long-a variant (block #94). Pinyin lines
# found fewer and fired on 「把那边的那个拿过来」.
ROBOT_KEYWORDS = (
    "B AH0 N AE1 N AH0 @banana",
    "B AH0 N AA1 N AH0 @banana",
)

SERVICES = ("llm", "asr", "tts", "vad")
SLOT_NAMES: dict[str, tuple[str, ...]] = {
    "llm": ("fast", "smart"),
    "asr": ("primary", "local", "kws"),
    "tts": ("primary", "fallback"),
    "vad": ("primary",),
}
LANGUAGES = ("yue", "zh", "en")


class ConfigCredentialField(BaseModel):
    """One credential a provider asks for."""

    model_config = ConfigDict(extra="forbid")

    key: str
    secret: bool = True
    default: str = ""


class ConfigVoice(BaseModel):
    """A selectable voice."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str


class ConfigService(BaseModel):
    """One service block of a preset."""

    model_config = ConfigDict(extra="forbid")

    api: str
    url: dict[str, str] = Field(default_factory=dict)
    model: str = ""
    models: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    extra_body: dict[str, Any] = Field(default_factory=dict)
    slot_extra_body: dict[str, dict[str, Any]] = Field(default_factory=dict)
    model_extra_body: dict[str, dict[str, Any]] = Field(default_factory=dict)
    slot_api: dict[str, str] = Field(default_factory=dict)
    slot_params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    per_language: dict[str, dict[str, str]] = Field(default_factory=dict)
    credential_map: dict[str, str] = Field(default_factory=dict)
    fallback_api: str | None = None
    fallback_url: dict[str, str] = Field(default_factory=dict)

    def url_for(self, region: str, fallback: bool = False) -> str | None:
        """Endpoint for a region (or the fallback endpoint)."""
        table = self.fallback_url if fallback else self.url
        return table.get(region) or table.get("global")

    def language_params(self, language: str | None) -> dict[str, str]:
        """Per-language parameter values for `language`, with `*` as the default."""
        resolved: dict[str, str] = {}
        for name, by_language in self.per_language.items():
            value = by_language.get(language or "") or by_language.get("*")
            if value is not None:
                resolved[name] = value
        return resolved


class ConfigProvider(BaseModel):
    """A bundled provider preset."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    order: int = 0
    console_url: str | None = None
    enabled: bool = True
    credentials: list[ConfigCredentialField] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=lambda: ["global"])
    languages: list[str] = Field(default_factory=list)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    llm: ConfigService | None = None
    asr: ConfigService | None = None
    tts: ConfigService | None = None
    vad: ConfigService | None = None
    default_voice: dict[str, str] = Field(default_factory=dict)
    voices: dict[str, list[ConfigVoice]] = Field(default_factory=dict)

    def service(self, kind: str) -> ConfigService | None:
        """The service block for `kind`, if the provider offers it."""
        if kind not in SERVICES:
            raise ValueError(f"unknown service {kind!r}")
        value: ConfigService | None = getattr(self, kind)
        return value

    def voices_for(self, language: str) -> list[ConfigVoice]:
        """Voice catalog for a language."""
        return self.voices.get(language) or self.voices.get("*") or []

    def default_voice_for(self, language: str) -> str | None:
        """Default voice for a language."""
        return self.default_voice.get(language) or self.default_voice.get("*")

    def credential_fields(self) -> list[str]:
        """Credential keys the user must supply."""
        return [item.key for item in self.credentials]


class ConfigSlot(BaseModel):
    """One slot binding: which provider, and optional overrides."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str | None = None
    voice: str | None = None
    speed: float | None = None
    language: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class ConfigLanguages(BaseModel):
    """Household language preferences."""

    model_config = ConfigDict(extra="forbid")

    default: str = Field(default="yue", description="household language: yue / zh / en")
    order: list[str] = Field(
        default_factory=lambda: list(LANGUAGES), description="preference order for mixed speech"
    )


class ConfigRobot(BaseModel):
    """The robot's fixed name, how it is heard, and the keyword-spotter token lines."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default=ROBOT_NAME, description="the wake name (fixed)")
    aliases: list[str] = Field(
        description="how SenseVoice spells the name (matched as written; the name itself"
        " also loosely, word by word)",
        default_factory=lambda: list(ROBOT_ALIASES),
    )
    keywords: list[str] = Field(
        description="keyword-spotter lines: CMU phones (English) or pinyin (Chinese) @label",
        default_factory=lambda: list(ROBOT_KEYWORDS),
    )


class ConfigSway(BaseModel):
    """Audio-reactive head sway while speaking (`body/sway.py`); our port of the SDK wobble."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, description="the head sways with Banana's own voice")
    master: float = Field(
        default=0.5,
        ge=0.0,
        le=1.5,
        description="liveliness: 0 = still · 0.5 = default · 1.5 ≈ the SDK's wobble",
    )
    pitch_deg: float = Field(default=4.5, ge=0.0, le=15.0, description="pitch amplitude (°)")
    yaw_deg: float = Field(default=3.75, ge=0.0, le=15.0, description="yaw amplitude (°)")
    roll_deg: float = Field(default=2.25, ge=0.0, le=10.0, description="roll amplitude (°)")
    x_mm: float = Field(default=4.5, ge=0.0, le=10.0, description="forward amplitude (mm)")
    y_mm: float = Field(default=3.75, ge=0.0, le=10.0, description="sideways amplitude (mm)")
    z_mm: float = Field(default=2.25, ge=0.0, le=10.0, description="height amplitude (mm)")
    pitch_hz: float = Field(default=2.2, gt=0.0, le=5.0, description="pitch oscillator (Hz)")
    yaw_hz: float = Field(default=0.6, gt=0.0, le=5.0, description="yaw oscillator (Hz)")
    roll_hz: float = Field(default=1.3, gt=0.0, le=5.0, description="roll oscillator (Hz)")
    x_hz: float = Field(default=0.35, gt=0.0, le=5.0, description="forward oscillator (Hz)")
    y_hz: float = Field(default=0.45, gt=0.0, le=5.0, description="sideways oscillator (Hz)")
    z_hz: float = Field(default=0.25, gt=0.0, le=5.0, description="height oscillator (Hz)")
    loud_low_db: float = Field(default=-46.0, description="loudness window floor (dBFS → 0)")
    loud_high_db: float = Field(default=-18.0, description="loudness window ceiling (dBFS → 1)")
    loud_offset_db: float = Field(default=4.0, description="added to the measured loudness (dB)")
    loud_gamma: float = Field(
        default=0.9, gt=0.0, le=3.0, description="loudness curve (< 1 lifts quiet speech)"
    )
    vad_on_db: float = Field(default=-35.0, description="voice detected above (dBFS)")
    vad_off_db: float = Field(default=-45.0, description="voice lost below (dBFS)")
    vad_attack_ms: float = Field(default=40.0, ge=0.0, description="voice detector attack (ms)")
    vad_release_ms: float = Field(default=250.0, ge=0.0, description="voice detector release (ms)")
    attack_ms: float = Field(default=50.0, ge=0.0, description="envelope attack (ms)")
    release_ms: float = Field(
        default=250.0, ge=0.0, description="envelope release (ms); also the fade-out after speech"
    )
    follow: float = Field(
        default=0.65, gt=0.0, le=1.0, description="how fast the amplitude follows the envelope"
    )
    latency_ms: float = Field(
        default=80.0, ge=0.0, le=1000.0, description="speaker latency compensation (ms)"
    )


class ConfigBody(BaseModel):
    """How to reach the body and how its daemon is run.

    `mode` is `reachy` (Lite over USB, daemon on this host; Wireless with `host` set to the
    robot) or `null` (no robot; audio and motion are no-ops). `sim` selects the daemon backend
    for development without hardware: `mockup` needs nothing extra, `mujoco` needs the
    `reachy-mini[mujoco]` extra. With `manage_daemon` sidekick spawns the daemon itself when
    the service starts (the owner's rule: never run `reachy-mini-daemon` by hand); a stop of the
    service always turns the robot off (block #85).
    """

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(default="reachy", description="reachy (a robot) or null (no robot)")
    host: str = Field(default="localhost", description="where the daemon answers")
    port: int = Field(default=8000, description="daemon port")
    media_backend: str = Field(default="default", description="default (USB) or webrtc (Wireless)")
    manage_daemon: bool = Field(
        default=True, description="sidekick starts and stops the daemon itself"
    )
    sim: str = Field(default="none", description="daemon simulation: none / mockup / mujoco")
    wake_on_start: bool = Field(default=True, description="wake the robot when the service starts")
    sleep_on_stop: bool = Field(
        default=True, description="the sleep move when the service stops (the robot turns off)"
    )
    preload_datasets: bool = Field(
        default=False,
        description="daemon: download Pollen's motion datasets at start (sidekick has its own)",
    )
    daemon_log_level: str = Field(default="INFO", description="daemon log level")
    daemon_start_timeout_s: float = Field(default=90.0, description="wait for the daemon (s)")
    volume: int | None = Field(
        default=None, description="speaker volume 0 … 100 (empty = unchanged)"
    )
    expressiveness: float = Field(
        default=1.0,
        ge=0.0,
        le=1.6,
        description="how big Banana's expressions and speech movements are overall (the "
        "household's taste); a story can be livelier and comfort calmer on top of it",
    )
    sway: ConfigSway = Field(default_factory=ConfigSway)  # our speech sway (block #42)
    sdk_wobble: bool = Field(
        default=False, description="use the SDK's own wobble instead of ours (no parameters)"
    )


class ConfigDashboard(BaseModel):
    """Where the loopback dashboard listens (invariant 15)."""

    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = 8787


class ConfigRecording(BaseModel):
    """The 24 h ring of video / audio / telemetry chunks (`record` module)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, description="record the 24 h ring")
    root: str | None = Field(
        default=None, description="recordings directory (empty = <home>/recordings)"
    )
    chunk_minutes: float = Field(default=5.0, gt=0.0, le=60.0, description="chunk length (min)")
    retention_hours: float = Field(default=24.0, gt=0.0, description="keep this long (h)")
    min_free_gb: float = Field(
        default=20.0, ge=0.0, description="prune, then pause below this free space (GB)"
    )
    width: int = Field(default=1280, ge=160, le=1920, description="video width (px)")
    height: int = Field(default=720, ge=90, le=1080, description="video height (px)")
    fps: float = Field(default=10.0, gt=0.0, le=30.0, description="video rate (fps)")
    bitrate_kbps: int = Field(default=1000, ge=100, le=20000, description="H.264 bitrate (kbps)")
    audio_codec: Literal["wav", "flac"] = Field(
        default="wav", description="wav (fast) or flac (smaller; the Pi)"
    )
    telemetry_hz: float = Field(default=10.0, ge=1.0, le=30.0, description="telemetry rows (Hz)")


class ConfigInteraction(BaseModel):
    """Engagement, speaker gating, barge-in and tracing knobs (AGENTS.md "Interaction")."""

    model_config = ConfigDict(extra="forbid")

    triggers: dict[str, bool] = Field(
        description="which triggers open a session",
        default_factory=lambda: {
            "wake_name": True,
            "gaze": False,
            "touch": True,
            "robot_initiated": True,
        },
    )
    speaker_gate: Literal["off", "soft", "strict"] = Field(
        default="soft",
        description="off: anyone · soft: unknown voices only by name or touch · strict: enrolled only",
    )
    session_timeout_s: float = Field(default=8.0, description="silence that ends a session (s)")
    answer_timeout_s: float = Field(
        default=15.0,
        ge=0.0,
        le=60.0,
        description="silence that ends a session after Banana asked a question (s)",
    )
    no_reply_limit: int = Field(default=2, description="NO_REPLY answers in a row that end it")
    closing_phrases: list[str] = Field(
        description="words that end a session",
        default_factory=lambda: ["再見", "再见", "就這樣", "就这样", "多謝", "多谢", "bye", "拜拜"],
    )
    stop_words: list[str] = Field(
        description="words that stop Banana mid-sentence",
        default_factory=lambda: ["停", "等一下", "等陣", "等阵", "stop", "收聲", "收声"],
    )
    backchannels: list[str] = Field(
        description="short acknowledgements that never interrupt",
        default_factory=lambda: ["嗯", "好", "哦", "係", "是", "ok"],
    )
    fillers: list[str] = Field(
        description="content-less syllables ignored by the name check",
        default_factory=lambda: ["嗯", "啊", "喂", "哦", "呃", "唔", "哼", "嘅"],
    )
    min_segment_dbfs: float = Field(default=-50.0, description="quieter speech is ignored (dBFS)")
    echo_similarity: float = Field(
        default=0.5, description="own-voice similarity above which speech counts as echo"
    )
    self_sector_tolerance_rad: float = Field(
        default=0.45, description="sound within this of the speaker direction is Banana's (rad)"
    )
    pre_roll_s: float = Field(default=1.0, description="audio kept before speech onset (s)")
    duck_db: float = Field(default=-12.0, description="playback drop when someone speaks (dB)")
    hard_stop_speech_s: float = Field(
        default=0.9, description="speech this long stops Banana outright (s)"
    )
    name_match_threshold: float = Field(default=0.8, description="fuzzy wake-name score needed")
    tv_sector: list[float] | None = Field(
        default=None, description="the TV's sound: yaw and tolerance (rad); empty = no TV"
    )
    tv_sector_tolerance_rad: float = Field(default=0.35, description="TV sector width (rad)")
    doa_sector_tolerance_rad: float = Field(
        default=0.6, description="how far an unknown speaker may move within a session (rad)"
    )
    language: str | None = Field(
        default=None, description="reply language override (empty = household default)"
    )
    trace_retention_days: float = Field(default=7.0, description="keep decisions and clips (days)")
    clip_max_s: float = Field(default=6.0, description="decision clip length (s)")
    # Who keeps a face centred: our own detector + servo through the motion owner (`own`,
    # default: works in the dark, composes with gestures / glances) or the
    # daemon's tracker (`daemon`: blends its aim with our pose by the weights below; below 1.0
    # the face is never centred, at 1.0 every other head motion is ignored).
    face_tracker: Literal["own", "daemon"] = Field(
        default="own", description="own: our detector + servo · daemon: the SDK tracker"
    )
    face_servo_gain: float = Field(
        default=0.7, gt=0.0, le=1.5, description="step toward the face per detection (own)"
    )
    idle_face_tracking_weight: float = Field(
        default=0.3, description="daemon tracker blend while idle (daemon only)"
    )
    engaged_face_tracking_weight: float = Field(
        default=1.0, description="daemon tracker blend while engaged (daemon only)"
    )
    asr_slot: str = Field(default="local", description="ASR slot for turns: local or primary")
    shadow_asr: bool = Field(default=True, description="also run the other ASR slot for comparison")
    # The TTS server leaves ~0.2 s between its sentences, the same as a comma (block #76).
    sentence_pause_ms: int = Field(
        default=300,
        ge=0,
        le=1000,
        description="extra pause after 。！？ (ms); the voice adds about 200 ms of its own",
    )
    # Attention layer (never speaks): idle scanning glances and glances toward clear sounds.
    idle_scan: bool = Field(default=True, description="glance around while idle")
    idle_scan_min_s: float = Field(
        default=8.0, ge=2.0, description="shortest gap between glances (s)"
    )
    idle_scan_max_s: float = Field(
        default=15.0, ge=2.0, description="longest gap between glances (s)"
    )
    idle_scan_yaw_rad: float = Field(
        default=0.7, ge=0.1, le=1.0, description="how far to the side a glance may go (rad)"
    )
    idle_scan_hold_s: float = Field(default=2.5, ge=0.5, description="hold a glance (s)")
    sound_glance: bool = Field(default=True, description="turn toward clear sounds while idle")
    sound_glance_min_dbfs: float = Field(default=-35.0, description="sound level needed (dBFS)")
    sound_glance_min_s: float = Field(default=0.6, description="sound duration needed (s)")
    sound_glance_hold_s: float = Field(default=3.0, ge=0.5, description="hold the look (s)")
    # Initiative layer (speaks first, through the agent): how talkative Banana may be.
    # quiet = never speak first; normal = greet a known person after 2 h away (6 / day);
    # chatty = after 30 min (12 / day). Safety events are not subject to this setting.
    sociability: Literal["quiet", "normal", "chatty"] = Field(
        default="normal",
        description="quiet: never speaks first · normal: greets after 2 h away (6 / day) · chatty: 30 min (12 / day)",
    )

    def trigger(self, name: str) -> bool:
        """Whether a trigger is switched on."""
        return bool(self.triggers.get(name, False))


class ConfigSubagent(BaseModel):
    """A subagent profile defined in config (extensions may add more)."""

    model_config = ConfigDict(extra="forbid")

    role: str
    description: str = ""
    llm_slot: str = "smart"
    tools: list[str] = Field(default_factory=lambda: ["*"])
    mcp_servers: list[str] = Field(default_factory=lambda: ["*"])
    skills: list[str] = Field(default_factory=lambda: ["*"])
    max_steps: int = 8
    timeout_s: float = 120.0


class ConfigAgents(BaseModel):
    """Main-agent knobs and subagent profiles."""

    model_config = ConfigDict(extra="forbid")

    main_llm_slot: str = Field(default="fast", description="LLM slot of the main agent")
    main_max_steps: int = Field(default=6, description="tool-call rounds per turn")
    main_max_tokens: int = Field(default=500, description="reply length cap (tokens)")
    context_chars: int = Field(
        default=6000, description="this conversation's rows in a turn's prompt (chars)"
    )
    # MiniMax answered one call in twenty only after 9-13 s (median 1.4 s, block #78).
    main_hedge_s: float = Field(
        default=2.5,
        ge=0.0,
        le=10.0,
        description="no first word after this long: ask the model again, take the first answer (s); 0 = off",
    )
    # Memory (blocks #66 / #70): conversations are written into episodes and facts after they
    # end, off the turn; each conversation's prompt carries a memory block built once.
    memory_writer: bool = Field(
        default=True, description="write episodes and facts from conversations after they end"
    )
    memory_slot: str = Field(default="smart", description="LLM slot of the memory writer")
    memory_voice_gap_min: float = Field(
        default=5.0,
        ge=1.0,
        le=60.0,
        description="the room's conversation ends after this silence (min)",
    )
    memory_text_gap_min: float = Field(
        default=15.0,
        ge=1.0,
        le=240.0,
        description="a chat's conversation ends after this pause (min)",
    )
    memory_block_chars: int = Field(
        default=1000, ge=200, le=4000, description="memory block in a conversation's prompt (chars)"
    )
    memory_nightly_hour: int = Field(
        default=3,
        ge=0,
        le=23,
        description="hour of the nightly memory pass (expire, digest, merge)",
    )
    subagents: dict[str, ConfigSubagent] = Field(default_factory=dict)


class ConfigAutomation(BaseModel):
    """Scheduler and heartbeat."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description=(
            "master switch: off stops every reminder, recurring and event job and the heartbeat,"
            " and the agent stops offering to schedule"
        ),
    )
    tick_s: float = Field(default=15.0, description="scheduler tick (s)")
    heartbeat_minutes: int = Field(
        default=30,
        ge=0,
        description=(
            "how often Banana checks on its own whether there is news the household has not"
            " heard (one agent turn, usually silent), in minutes; 0 turns the heartbeat off"
        ),
    )
    quiet_hours: list[str] | None = Field(
        default_factory=lambda: ["23:00", "07:30"],
        description="no spontaneous speech between these times (HH:MM HH:MM; empty = never)",
    )


class ConfigTelegram(BaseModel):
    """Telegram bot channel (token in `credentials.telegram.bot_token`)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    allow_chat_ids: list[str] = Field(default_factory=list)
    pairing_code: str | None = None
    owner_chat_id: str | None = None
    poll_timeout_s: int = 30


class ConfigWeChat(BaseModel):
    """Personal WeChat through Tencent's iLink bot protocol (token in `credentials.wechat`)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    bot_id: str | None = None
    base_url: str = "https://ilinkai.weixin.qq.com"
    user_id: str | None = None
    allow_user_ids: list[str] = Field(default_factory=list)
    bot_agent: str = "sidekick/0.1.0"


class ConfigChannels(BaseModel):
    """Remote channels."""

    model_config = ConfigDict(extra="forbid")

    telegram: ConfigTelegram = Field(default_factory=ConfigTelegram)
    wechat: ConfigWeChat = Field(default_factory=ConfigWeChat)


class ConfigPerception(BaseModel):
    """Presence and event sources."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, description="camera and sound watchers")
    poll_hz: float = Field(
        default=10.0, description="face detection rate (Hz); also the servo rate"
    )
    presence_enter_s: float = Field(
        default=1.0, description="a face this long = someone present (s)"
    )
    presence_leave_s: float = Field(default=60.0, description="no face this long = nobody (s)")
    persist_min_severity: str = Field(
        default="notice", description="store events from this severity"
    )
    history: int = Field(default=200, description="events kept in memory")
    mutual_gaze_s: float = Field(
        default=2.5,
        ge=0.5,
        description="a face turned toward the camera this long = mutual gaze (s)",
    )
    mutual_gaze_min_height: float = Field(
        default=0.12, ge=0.0, le=1.0, description="smallest face that counts (fraction of frame)"
    )


class ConfigContacts(BaseModel):
    """Identification thresholds and the TV zone (normalised camera rectangle)."""

    model_config = ConfigDict(extra="forbid")

    voice_threshold: float = Field(default=0.5, description="voice match needed (cosine)")
    face_threshold: float = Field(default=0.363, description="face match needed (cosine)")
    tv_zone: list[float] | None = Field(
        default=None, description="camera rectangle x y w h (0 … 1) whose faces are ignored"
    )
    enroll_self: bool = Field(default=True, description="enroll Banana's own voice at start")


class ConfigSpec(BaseModel):
    """What the user chose; persisted as `.derived_data/config.json`."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    credentials: dict[str, dict[str, str]] = Field(default_factory=dict)
    region: dict[str, str] = Field(default_factory=dict)
    languages: ConfigLanguages = Field(default_factory=ConfigLanguages)
    slots: dict[str, dict[str, ConfigSlot]] = Field(default_factory=dict)
    robot: ConfigRobot = Field(default_factory=ConfigRobot)
    body: ConfigBody = Field(default_factory=ConfigBody)
    channels: ConfigChannels = Field(default_factory=ConfigChannels)
    perception: ConfigPerception = Field(default_factory=ConfigPerception)
    contacts: ConfigContacts = Field(default_factory=ConfigContacts)
    agents: ConfigAgents = Field(default_factory=ConfigAgents)
    automation: ConfigAutomation = Field(default_factory=ConfigAutomation)
    interaction: ConfigInteraction = Field(default_factory=ConfigInteraction)
    dashboard: ConfigDashboard = Field(default_factory=ConfigDashboard)
    recording: ConfigRecording = Field(default_factory=ConfigRecording)

    def slot(self, kind: str, name: str) -> ConfigSlot | None:
        """The binding for `kind.name`, if any."""
        return self.slots.get(kind, {}).get(name)

    def bound_slots(self) -> list[tuple[str, str, ConfigSlot]]:
        """Every binding as `(kind, name, slot)` in canonical order."""
        out: list[tuple[str, str, ConfigSlot]] = []
        for kind in SERVICES:
            for name in SLOT_NAMES[kind]:
                slot = self.slot(kind, name)
                if slot is not None:
                    out.append((kind, name, slot))
        return out

    def masked(self) -> dict[str, Any]:
        """A copy for display with credential values masked."""
        data = self.model_dump(mode="json")
        from sidekick.log import mask_secret

        data["credentials"] = {
            provider: {key: mask_secret(value) for key, value in fields.items()}
            for provider, fields in self.credentials.items()
        }
        return data


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """The merge of a preset service, a slot and credentials, ready for `make_*_backend`."""

    kind: str
    slot: str
    provider: str
    api: str
    url: str | None
    model: str
    params: dict[str, Any] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)
    credentials: dict[str, str] = field(default_factory=dict)
    language: str | None = None
    voice: str | None = None
    region: str = "global"

    @property
    def api_key(self) -> str:
        """The one credential slot every cloud backend has."""
        return self.credentials.get("api_key", "")
