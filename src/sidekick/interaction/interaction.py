"""sidekick.interaction.interaction — InteractionSession: the voice front end, assembled

Overview
    Owns the audio thread, the engagement machine, the barge-in controller, the turn pipeline,
    attention and expressions, and exposes `VoiceChannel`. `setup` registers that adapter with
    the channel registry it is given and takes the recorder's microphone reader for decision
    clips; `start()` begins listening when the body is connected and the VAD bound (otherwise
    the front end stays idle and says so); `say()` speaks robot-initiated text, `can_speak()` /
    `speak()` are the agent's voice hooks for unprompted messages (awake, the front end running
    and someone in the room, or presence off); `snapshot()` / `recent_decisions()` feed the dashboard;
    `hold()` / `release_hold()` let a controller (the Robot tab) park the front end while it
    drives the body directly.
Design
    One asyncio task consumes the ordered event stream from `AudioFrontEnd` (speech, touch,
    body state) and applies the rules of AGENTS.md "Interaction":

    - IDLE: every segment is transcribed **locally** and name-spotted; nothing goes to the cloud
      unless the machine accepts (invariant 17). An accepted segment opens a session and its
      remainder is the first turn (cloud ASR on the clip, name stripped from the transcript;
      the local remainder is the fallback).
    - ENGAGED: segments matching the session (speaker or DoA sector) run a turn; the session
      ends on timeout, closing phrase or repeated `NO_REPLY`. Speech that began before the
      silence ran out holds the session until it ends: the timer used to close it under people
      who were mid-sentence (13 times on 10-30/31, block #92). Only the name, with no speech
      after it: Banana answers out loud at once (`call.py`), and the session waits as after a
      question.
    - SPEAKING: qualifying speech ducks playback; ≥ 0.7 s, a stop word, the wake name or a touch
      cancels the running turn and the buffered utterance becomes the next turn; a short
      backchannel resumes.

    Turns run as a cancellable task so events keep flowing during playback. Every decision is
    traced with scores and a clip (invariant 18). The façade never calls the SDK: all motion
    and audio go through `BodySession` (invariant 10). While held, speech / keyword / touch
    events are dropped (level and body-state events still update the mirrors), the running
    turn is cancelled, and `say()` does not touch attention; release restores the idle posture.

    Two more layers ride on the same event stream (block #38). **Attention** never speaks: the
    0.5 s tick drives idle scanning glances, a sound that lasts while idle earns a glance toward
    it, faces own the head, and speech flagged `self_motion` by the front end (it began and
    ended inside the body's moving window) never ducks playback and is traced as `self motion`.
    **Initiative** speaks only through the agent: a `gaze.mutual` event from `perception` goes
    through `Initiative` (known contact, away ≥ 2 h at `normal` sociability, not quiet hours,
    daily cap) and, when due, becomes a `greet.due` event the robot extension's automation
    answers — or not (`NO_REPLY`). Captions report `listening` only inside a session so the Live
    page does not label ambient sound; the raw flag is `speech_open`.

    Conversational voice enrollment (`start_enrollment`, the robot extension's `enroll_voice`)
    learns the next utterances of the session it started in, for at most `ENROLL_WINDOW_S`: a
    voice not yet recognised in that session is the person being learned (no new `person:n`),
    a different known voice is skipped, and when the session ends first the enrollment is
    dropped — it once stayed armed for nine hours and learned the next morning's speakers
    (block #63).

    **Who is speaking (block #80).** An utterance with less than `MIN_ID_SPEECH_S` of speech is
    not identified (a 0.7 s call of the name in a clip that is mostly pre-roll embeds the room),
    and less than `MIN_PERSON_SPEECH_S` never starts a new person. A voice in the uncertain band of
    a contact (`Identification.near`) is not a stranger either: no new person, and inside a
    session it counts as the session's speaker, and once `SESSION_MEAN_MIN` uncertain
    utterances of a session average out at the threshold the session is that contact (the
    owner's first morning: single sentences 0.41–0.54, their mean 0.53 by the fourth; another
    voice's mean stayed at 0.26). Utterances identified as a contact — and uncertain ones inside
    that contact's session — are folded into the contact's voice (`learn_voice`), and an
    unnamed person whose centroid has become a contact's is merged into it (`merge_person`, the
    session renamed). A turn's speaker is the utterance's identity, else
    the session's. A segment's direction is the median of the readings during its speech
    (`BodySession.doa_between`); one whose readings disagree has none (`_yaw_of`).
    Restartable in place (block #87): `start()` registers its touch / state callbacks once (stable
    methods forwarding to the run's front end), takes the body's state as it is now, preloads
    SenseVoice and waits up to `TTS_READY_S` for the TTS link; `stop()` joins the front end,
    cancels the warm-up and puts the machine to sleep; `check()` gives the start dialog listening,
    SenseVoice, the wake-name spotter and the TTS link.
Depends on
    sidekick.log, sidekick.storage, sidekick.audio, sidekick.body, sidekick.asr, sidekick.tts,
    sidekick.vad, sidekick.channel.

See Also
--------
    AGENTS.md "Interaction: engagement, interruption, languages", PLAN.md block "[2026-10-26 #12]".

"""

from __future__ import annotations

import asyncio
import collections
import difflib
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from sidekick.asr import ASRSession
from sidekick.audio import AudioClip, decode_wav
from sidekick.body import BodyDoA, BodySession, doa_to_yaw, yaw_distance
from sidekick.channel import ChannelMessage, ChannelSession
from sidekick.contact import is_person
from sidekick.log import Log
from sidekick.perception import PerceptionEvent, Severity
from sidekick.tts import TTSSession
from sidekick.vad import VADSession

from .attention import DOA_MIN_AGREEMENT, Attention
from .barge_in import BargeInController
from .call import CallAnswers
from .engagement import EngagementMachine
from .expression import ExpressionMapper
from .frontend import AudioFrontEnd
from .initiative import Initiative
from .namespot import NameSpotter, is_filler, normalize
from .pipeline import TurnPipeline
from .schemas import (
    EngagementDecision,
    FrontEndEvent,
    InteractionState,
    NameMatch,
    Responder,
    TurnResult,
    TurnTiming,
)
from .trace import InteractionTrace
from .voice_channel import VoiceChannel

TTS_READY_S = 8.0  # the start waits this long for the TTS link (it takes 2–3 s)
CAMERA_HALF_FOV_RAD = math.radians(45.0)  # the Lite camera's half horizontal field of view
FACE_DOA_TOLERANCE_RAD = math.radians(25.0)
ENROLL_WINDOW_S = 90.0  # conversational voice enrollment: its own session only, this long (#63)
MIN_ID_SPEECH_S = 1.0  # less speech than this is not identified (block #80)
MIN_PERSON_SPEECH_S = 1.2  # ...and less than this never starts a new person
SESSION_MEAN_MIN = 3  # uncertain utterances of one session averaged before they may identify it


@dataclass(frozen=True, slots=True)
class _Voice:
    """Who an utterance sounds like (`InteractionSession._identify`)."""

    speaker: str | None = None  # a contact, `self` or an unnamed person, at the threshold
    score: float = 0.0
    is_self: bool = False
    near: str | None = None  # a contact in the uncertain band below the threshold
    vector: Any = None  # the utterance's voice embedding, when one was taken


class InteractionSession:
    """The voice front end."""

    shared: ClassVar[InteractionSession]

    def __init__(self) -> None:
        self.body: BodySession | None = None
        self.asr: ASRSession | None = None
        self.tts: TTSSession | None = None
        self.vad: VADSession | None = None
        self.config: Any = None
        self.robot: Any = None
        self.responder: Responder | None = None
        self.contacts: Any = None
        self.perception: Any = None
        self.default_language: str | None = "zh"
        self.names: NameSpotter | None = None
        self.machine: EngagementMachine | None = None
        self.barge: BargeInController | None = None
        self.pipeline: TurnPipeline | None = None
        self.attention: Attention | None = None
        self.initiative: Initiative | None = None
        self.expressions: ExpressionMapper | None = None
        self.trace: InteractionTrace | None = None
        self._onset_self_motion = False
        self.voice = VoiceChannel(self)
        self._events: asyncio.Queue[FrontEndEvent] | None = None
        self._frontend: AudioFrontEnd | None = None
        self._loop_task: asyncio.Task[None] | None = None
        self._tick_task: asyncio.Task[None] | None = None
        self._turn: asyncio.Task[TurnResult] | None = None
        self._warmup_task: asyncio.Task[None] | None = None
        self._turn_meta: dict[asyncio.Task[TurnResult], dict[str, Any]] = {}
        self._pending_interrupt: FrontEndEvent | None = None
        self.level_dbfs = -100.0
        self._short_segment: tuple[AudioClip, float] | None = None
        self._name_heard_at = float("-inf")
        self._self_yaws: collections.deque[float] = collections.deque(maxlen=20)
        # (contact, utterances to go, the session it belongs to, deadline)
        self._enrollment: tuple[str, int, Any, float] | None = None
        self.last_turn: TurnResult | None = None
        self.last_turn_at = 0.0
        self.recent: collections.deque[dict[str, Any]] = collections.deque(maxlen=50)
        self.started = False
        self._speech_since: float | None = None
        self._speech_onset: float | None = None  # monotonic start of the speech open now
        self.calls = CallAnswers()  # the spoken answers to a bare call (block #92)
        self._calls_task: asyncio.Task[int] | None = None
        self._call_task: asyncio.Task[None] | None = None
        self._heard: tuple[str, float, str | None] | None = None
        self._held: str | None = None
        self._guest_voices: dict[str, Any] = {}
        self._unsure: tuple[Any, str | None, list[Any]] = (None, None, [])  # session, near, votes
        self.clip_source: Callable[[float, float], AudioClip | None] | None = None

    # ------------------------------------------------------------------- setup

    def setup(
        self,
        body: BodySession,
        asr: ASRSession,
        tts: TTSSession,
        vad: VADSession,
        config: Any,
        robot: Any,
        responder: Responder,
        trace_path: Path | None = None,
        audio_dir: Path | None = None,
        default_language: str | None = "zh",
        shadow_asr: bool | None = None,
        asr_slot: str | None = None,
        contacts: Any = None,
        perception: Any = None,
        quiet_hours: tuple[str, str] | list[str] | None = None,
        channels: ChannelSession | None = None,
        clip_source: Callable[[float, float], AudioClip | None] | None = None,
    ) -> None:
        """Bind peers, register the voice adapter and take the recorder's clip reader."""
        self.body, self.asr, self.tts, self.vad = body, asr, tts, vad
        self.config, self.robot, self.responder = config, robot, responder
        self.contacts, self.perception = contacts, perception
        self.default_language = default_language
        self.names = NameSpotter(
            getattr(robot, "name", "Banana"),
            getattr(robot, "aliases", []),
            float(getattr(config, "name_match_threshold", 0.75)),
        )
        self.machine = EngagementMachine(config, awake=body.awake)
        self.barge = BargeInController(
            self.names,
            getattr(config, "stop_words", []),
            getattr(config, "backchannels", []),
            float(getattr(config, "duck_db", -12.0)),
            float(getattr(config, "hard_stop_speech_s", 0.7)),
        )
        self.expressions = ExpressionMapper(body)
        self.pipeline = TurnPipeline(
            asr,
            tts,
            body,
            responder,
            self.expressions,
            asr_slot=asr_slot or str(getattr(config, "asr_slot", "local")),
            shadow_asr=bool(getattr(config, "shadow_asr", True))
            if shadow_asr is None
            else shadow_asr,
            sentence_pause_s=float(getattr(config, "sentence_pause_ms", 300)) / 1000.0,
        )
        self.attention = Attention(
            body,
            float(getattr(config, "idle_face_tracking_weight", 0.3)),
            float(getattr(config, "engaged_face_tracking_weight", 1.0)),
        )
        self.attention.configure(config)
        self.initiative = Initiative(
            contacts, str(getattr(config, "sociability", "normal")), quiet_hours
        )
        if trace_path is not None and audio_dir is not None:
            self.trace = InteractionTrace(
                trace_path,
                audio_dir,
                float(getattr(config, "trace_retention_days", 7.0)),
                float(getattr(config, "clip_max_s", 6.0)),
            )
        if channels is not None:
            channels.register(self.voice)
        if clip_source is not None:  # decision clips come from the recording ring, not audio/
            self.clip_source = clip_source
            if self.trace is not None:
                self.trace.clip_files = False

    def set_config(self, config: Any) -> None:
        """Apply a changed `ConfigInteraction` live (Settings page, TV sector wizard step)."""
        self.config = config
        if self.machine is not None:
            self.machine.config = config
        if self.pipeline is not None:
            self.pipeline.keeper.sentence_pause_s = (
                float(getattr(config, "sentence_pause_ms", 300)) / 1000.0
            )
        if self.attention is not None:
            self.attention.configure(config)
        if self.initiative is not None:
            self.initiative.configure(config)

    def set_quiet_hours(self, quiet_hours: Any) -> None:
        """Apply changed quiet hours live (they come from `automation.quiet_hours`)."""
        if self.initiative is not None:
            self.initiative.quiet_hours = tuple(quiet_hours) if quiet_hours else None

    # --------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Start listening (only with a connected body and a bound VAD)."""
        assert self.body is not None and self.vad is not None and self.machine is not None
        if not self.body.connected or not self.vad.is_ready("primary"):
            Log.warning("voice front end not started (no body or no VAD)")
            return
        Log.info0(f"state={self.machine.state.value}")
        loop = asyncio.get_running_loop()
        self._events = asyncio.Queue()
        detector = self.vad.create("primary")
        keyword_stream = None
        kws_backend = self.asr.backend("kws") if self.asr is not None else None
        if kws_backend is not None and hasattr(kws_backend, "spot_stream"):
            try:
                keyword_stream = await asyncio.to_thread(kws_backend.spot_stream)
                Log.info("streaming keyword spotter on")
            except Exception as exc:
                Log.warning(f"streaming keyword spotter unavailable: {exc!r}")
        self._frontend = AudioFrontEnd(
            self.body,
            detector,
            loop,
            self._events,
            pre_roll_s=float(getattr(self.config, "pre_roll_s", 1.0)),
            keyword_stream=keyword_stream,
        )
        # Stable session methods, registered once however often the service restarts (block
        # #87); each forwards to the front end of the current run.
        self.body.on_touch(self._forward_touch)
        self.body.on_state_change(self._forward_body_state)
        # `setup` ran before the body connected (block #87): take its state as it is now
        self.machine.set_awake(self.body.awake, time.monotonic())
        self._frontend.start()
        if self.attention is not None:
            self.attention.start()
        subscribe = getattr(self.perception, "subscribe", None)
        if callable(subscribe):
            subscribe("gaze.mutual", self._on_gaze_event)
        on_face = getattr(self.perception, "on_face", None)
        if callable(on_face):
            on_face(self._on_local_face)  # every detection of our detector → the face servo
        self._loop_task = asyncio.create_task(self._run(), name="interaction-events")
        self._tick_task = asyncio.create_task(self._ticks(), name="interaction-ticks")
        self.started = True
        await self._prepare_voice()

    async def _prepare_voice(self) -> None:
        """Load the recogniser and open the TTS link before anyone speaks (block #86).

        SenseVoice used to load on the first utterance (0.35 s) and the TTS link opened
        2–3 s after start; `check()` reports both.
        """
        local = self.asr.backend("local") if self.asr is not None else None
        preload = getattr(local, "preload", None)
        if callable(preload):
            try:
                await asyncio.to_thread(preload)
            except Exception as exc:
                Log.error(f"SenseVoice preload: {exc!r}")
        if self.pipeline is not None:
            self._warmup_task = asyncio.create_task(self.pipeline.warm_up(), name="tts-warmup")
            try:
                await asyncio.wait_for(asyncio.shield(self._warmup_task), TTS_READY_S)
            except (TimeoutError, Exception) as exc:
                Log.warning(f"tts link not ready after {TTS_READY_S:.0f} s: {exc!r}")
        if self.tts is not None and self.tts.slots():
            # the answers to a bare call, in the household's voice, before anyone calls
            languages = (self.default_language, "zh", "en", "yue")
            self._calls_task = asyncio.create_task(
                self.calls.prepare(self.tts.synthesize, languages), name="call-answers"
            )

    def _forward_touch(self, touch: Any) -> None:
        frontend = self._frontend
        if frontend is not None and self.started:
            frontend.on_touch(touch)

    def _forward_body_state(self, previous: Any, current: Any) -> None:
        frontend = self._frontend
        if frontend is not None and self.started:
            frontend.on_body_state(previous, current)

    def check(self) -> list[dict[str, Any]]:
        """Readiness items: listening, the recogniser, the wake-name spotter, the TTS link."""
        if self.body is not None and not self.body.connected:
            if getattr(self.body, "mode", "reachy") != "reachy":
                return [
                    {"id": "frontend", "title": "listening", "level": "off", "detail": "no robot"}
                ]
            return [
                {
                    "id": "frontend",
                    "title": "listening",
                    "level": "bad",
                    "detail": "no body connection",
                }
            ]
        frontend = self._frontend
        listening = self.started and frontend is not None and frontend.is_alive()
        items = [
            {
                "id": "frontend",
                "title": "listening",
                "level": "ok" if listening else "bad",
                "detail": "VAD running" if listening else "not started (no VAD?)",
            }
        ]
        local = self.asr.backend("local") if self.asr is not None else None
        if local is not None and hasattr(local, "loaded"):
            items.append(
                {
                    "id": "asr",
                    "title": "SenseVoice",
                    "level": "ok" if local.loaded else "bad",
                    "detail": "loaded" if local.loaded else "not loaded (model missing?)",
                }
            )
        if self.asr is not None and self.asr.backend("kws") is not None:
            spotting = frontend is not None and frontend.keyword_stream is not None
            items.append(
                {
                    "id": "kws",
                    "title": "wake-name spotter",
                    "level": "ok" if spotting else "warn",
                    "detail": "on" if spotting else "off (SenseVoice alone)",
                }
            )
        if self.pipeline is not None:
            keeper = self.pipeline.keeper
            items.append(
                {
                    "id": "tts",
                    "title": "TTS link",
                    "level": "ok" if keeper.connected else "bad",
                    "detail": "connected"
                    if keeper.connected
                    else (keeper.error or "not connected")[:200],
                }
            )
        return items

    async def stop(self) -> None:
        """Stop listening and release the TTS session."""
        Log.info0()
        self.started = False
        frontend = self._frontend
        if frontend is not None:
            frontend.stop()
            if frontend.is_alive():
                await asyncio.to_thread(frontend.join, 2.0)
        for task in (
            self._warmup_task,
            self._calls_task,
            self._tick_task,
            self._loop_task,
            self._call_task,
            self._turn,
        ):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        if self.pipeline is not None:
            await self.pipeline.close()
        self._loop_task = self._tick_task = self._turn = self._warmup_task = None
        self._calls_task = self._call_task = None
        self._speech_onset = None
        self._frontend = None
        if self.machine is not None:  # the robot is off: no session survives a stop
            self.machine.set_awake(False, time.monotonic())

    # ------------------------------------------------------------------ events

    async def _ticks(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            if self.machine is None:
                continue
            self._attention_tick()
            if self._turn is not None and not self._turn.done():
                continue
            decision = self.machine.on_tick(time.monotonic(), self._speech_onset)
            if decision is not None and decision.end_session:
                self._session_ended(decision.reason)

    def _attention_tick(self) -> None:
        """Idle glances: only while awake, idle and not parked by a controller."""
        attention, machine, body = self.attention, self.machine, self.body
        if attention is None or machine is None or body is None or self._held is not None:
            return
        if machine.state != InteractionState.IDLE or not body.awake:
            return
        visible = attention.face_tracked()
        if not visible and self.perception is not None and hasattr(self.perception, "local_face"):
            visible = bool(self.perception.local_face().detected)
        attention.tick(visible)

    def _on_local_face(self, face: Any) -> None:
        """Our detector saw (or lost) a face: servo the head unless parked or asleep."""
        attention, machine, body = self.attention, self.machine, self.body
        if attention is None or machine is None or body is None or self._held is not None:
            return
        if machine.state == InteractionState.SLEEPING or not body.awake:
            return
        attention.on_face(face)

    async def _on_gaze_event(self, event: Any) -> None:
        """`gaze.mutual` from perception → the initiative rules → maybe `greet.due`."""
        machine, initiative, body = self.machine, self.initiative, self.body
        if machine is None or initiative is None or body is None or self.perception is None:
            return
        if self._held is not None or machine.state != InteractionState.IDLE or not body.awake:
            return
        data = dict(getattr(event, "data", {}) or {})
        due = initiative.on_mutual_gaze(data.get("contact"))
        if due is None:
            Log.debug(f"mutual gaze of {data.get('contact')}: {initiative.last_reason}")
            return
        self._record(
            "initiative",
            True,
            f"greet {due['name']} (away {due['absent_h']} h, {due['sociability']})",
            machine.state,
            speaker=due["contact"],
        )
        await self.perception.publish(PerceptionEvent("greet.due", Severity.NOTICE, due))

    async def _run(self) -> None:
        assert self._events is not None
        while True:
            event = await self._events.get()
            try:
                await self._handle(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                Log.error(f"event {event.kind}: {exc!r}")

    async def _handle(self, event: FrontEndEvent) -> None:
        assert self.machine is not None and self.barge is not None and self.attention is not None
        machine = self.machine
        if event.kind == "level":
            self.level_dbfs = event.level_dbfs or -100.0
            return
        if event.kind == "body_state":
            decision = machine.set_awake(bool(event.awake), event.ts)
            if decision is not None:
                Log.info(f"engagement: {decision.reason} -> {decision.next_state.value}")
                if decision.end_session:
                    await self._cancel_turn("body asleep")
                    self.attention.set_engaged(False)
            return
        if self._held is not None:
            return
        if event.kind == "touch":
            await self._on_touch(event)
            return
        if event.kind == "keyword":
            await self._on_keyword(event)
            return
        if event.kind == "pause":
            # a pause inside their sentence: maybe a small "mm-hm" nod (never during a turn)
            if machine.state == InteractionState.ENGAGED and (
                self._turn is None or self._turn.done()
            ):
                self.attention.backchannel()
            return
        if event.kind == "speech_start":
            self._speech_since = time.time()
            self._speech_onset = None if event.self_motion else event.ts
            self._onset_self_motion = event.self_motion
            if machine.state == InteractionState.ENGAGED and not event.self_motion:
                self.attention.heard_again()  # they talk while Banana thinks: listen again
                self._warm_responder()
            if machine.state == InteractionState.SPEAKING:
                # our own motors (a gesture, a turn) never duck the voice
                qualifying = self._qualifies(event) and not event.self_motion
                stage1 = self.barge.on_speech_start(event.ts, qualifying)
                if stage1.action == "duck":
                    self._duck(True, stage1.reason)
            return
        if event.kind == "speech_ongoing":
            if machine.state == InteractionState.IDLE:
                if not event.self_motion and self._sound_ok(event):
                    self.attention.on_sound(event.doa, self.level_dbfs, event.duration_s)
                return
            if machine.state == InteractionState.SPEAKING:
                if (
                    not self.barge.ducked
                    and self._onset_self_motion
                    and not event.self_motion
                    and self._qualifies(event)
                ):
                    # speech that began during our motion but outlasts it is the room after all
                    self._onset_self_motion = False
                    stage1 = self.barge.on_speech_start(event.ts, True)
                    if stage1.action == "duck":
                        self._duck(True, "speech outlasted self motion")
                if self.barge.ducked and not self._qualifies(event):
                    # The sound moved out of the addressee's sector (or into the robot's own):
                    # not an interruption after all.
                    self.barge.ducked = False
                    self._duck(False, "not qualifying anymore")
                    return
                stage2 = self.barge.on_speech_ongoing(event.ts, event.duration_s)
                if stage2.action == "stop":
                    if await self._sounds_like_self(event):
                        return
                    await self._hard_stop(stage2.reason, event)
            return
        if event.kind == "speech_end":
            self._speech_since = None
            self._speech_onset = None
            if event.segment is not None:
                await self._on_segment(event)

    def _sound_ok(self, event: FrontEndEvent) -> bool:
        """A sound worth a glance: a direction that is neither the TV's nor our own speaker's."""
        assert self.machine is not None
        if event.doa is None:
            return False
        yaw = doa_to_yaw(event.doa.angle)
        if self.machine._in_tv_sector(yaw):
            return False
        self_yaw = self.self_sector_yaw()
        return self_yaw is None or yaw_distance(yaw, self_yaw) > float(
            getattr(self.config, "self_sector_tolerance_rad", 0.45)
        )

    def _qualifies(self, event: FrontEndEvent) -> bool:
        """Who may duck by onset: the addressee's direction (or anyone, for robot-initiated speech).

        Unknown direction never ducks; such speech can still stop the robot by content (a stop
        word or the wake name) once its segment is transcribed locally.
        """
        assert self.machine is not None
        if event.doa is None:
            return False
        yaw = doa_to_yaw(event.doa.angle)
        if self.machine._in_tv_sector(yaw):
            return False
        self_yaw = self.self_sector_yaw()
        if self_yaw is not None and yaw_distance(yaw, self_yaw) <= float(
            getattr(self.config, "self_sector_tolerance_rad", 0.45)
        ):
            return False
        session = self.machine.session
        if session is None or session.doa_yaw is None:
            return True
        tolerance = float(getattr(self.config, "doa_sector_tolerance_rad", 0.6))
        return yaw_distance(yaw, session.doa_yaw) <= tolerance

    async def _sounds_like_self(self, event: FrontEndEvent) -> bool:
        """Before a duration-based hard stop, look at the speech so far: echo or filler → not a stop."""
        assert self.barge is not None
        if self._frontend is None:
            return False
        recent = self._frontend.recent_audio(min(event.duration_s + 0.3, 3.0))
        if recent is None:
            return False
        local = await self._local_text(recent)
        echo = self._echo_score(local)
        fillers = getattr(self.config, "fillers", [])
        if is_filler(local, fillers) or echo >= float(getattr(self.config, "echo_similarity", 0.5)):
            yaw = doa_to_yaw(event.doa.angle) if event.doa is not None else None
            if yaw is not None:
                self._self_yaws.append(yaw)
            self.barge.ducked = False
            self.barge.stopped = False
            self._duck(False, "self")
            self._record(
                "barge_in",
                False,
                f"ignored: sounds like self ({echo:.2f}, {local!r})",
                InteractionState.SPEAKING,
                doa=yaw,
                duration=event.duration_s,
                text=local,
                clip=recent,
            )
            return True
        return False

    def self_sector_yaw(self) -> float | None:
        """Median direction of segments classified as the robot's own voice (learned at runtime)."""
        if len(self._self_yaws) < 2:
            return None
        values = sorted(self._self_yaws)
        return values[len(values) // 2]

    @staticmethod
    def _level_dbfs(clip: AudioClip) -> float:
        rms = (
            float(np.sqrt(np.mean(np.square(clip.samples, dtype=np.float64))))
            if len(clip.samples)
            else 0.0
        )
        return 20.0 * math.log10(rms) if rms > 1e-9 else -100.0

    def _warm_responder(self) -> None:
        """A turn may follow: let the responder open its LLM connection now (duck-typed)."""
        warm = getattr(self.responder, "warm", None)
        if callable(warm):
            try:
                warm()
            except Exception as exc:  # never in the way of listening
                Log.debug(f"warm responder: {exc!r}")

    async def _on_keyword(self, event: FrontEndEvent) -> None:
        """Streaming keyword spotter hit: engage now; the coming segment is the first turn."""
        assert self.machine is not None and self.barge is not None and self.attention is not None
        doa_yaw = self._yaw_of(event.doa)
        state_before = self.machine.state
        if state_before == InteractionState.SPEAKING:
            self._record(
                "keyword",
                True,
                f"stop: wake name {event.side}",
                state_before,
                doa=doa_yaw,
                trigger="wake_name",
            )
            self.barge.on_speech_start(event.ts, True)
            self.barge.stopped = True
            await self._cancel_turn("wake name (stream)")
            self.machine.on_robot_speaking(False, event.ts)
            self._duck(False, "stopped")
            self.barge.reset()
            self._name_heard_at = event.ts
            self.attention.set_engaged(True)
            self.attention.on_speech(event.doa, force=True)
            return
        decision = self.machine.on_keyword(event.ts, doa_yaw)
        if decision.accept:
            self._warm_responder()
        self._record(
            "keyword",
            decision.accept,
            f"{decision.reason} {event.side}",
            state_before,
            doa=doa_yaw,
            trigger="wake_name",
        )
        if not decision.accept:
            return
        self._name_heard_at = event.ts
        self._short_segment = None
        if state_before == InteractionState.IDLE:
            Log.info(f"engagement: keyword {event.side!r} -> ENGAGED")
            self.attention.set_engaged(True)
        self.attention.on_speech(event.doa, force=True)

    async def _on_touch(self, event: FrontEndEvent) -> None:
        assert self.machine is not None and self.barge is not None and self.attention is not None
        state_before = self.machine.state
        decision = self.machine.on_touch(event.ts)
        self._record("touch", decision.accept, decision.reason, state_before, trigger="touch")
        if not decision.accept:
            return
        if state_before == InteractionState.SPEAKING:
            self.barge.on_touch()
            await self._cancel_turn("touch")
            self.attention.set_engaged(True)
            return
        if state_before == InteractionState.IDLE:
            Log.info("engagement: touch -> ENGAGED")
            self.attention.set_engaged(True)
            self.attention.acknowledge()
        else:
            self.attention.acknowledge()

    async def _on_segment(self, event: FrontEndEvent) -> None:
        assert self.machine is not None and self.barge is not None and self.attention is not None
        assert event.segment is not None and self.names is not None
        machine = self.machine
        clip = event.segment.clip
        doa_yaw = self._yaw_of(event.doa)
        state_before = machine.state
        if state_before == InteractionState.SLEEPING:
            return
        level = self._level_dbfs(clip)
        if level < float(getattr(self.config, "min_segment_dbfs", -50.0)):
            self._record(
                "segment",
                False,
                f"too quiet ({level:.0f} dBFS)",
                state_before,
                doa=doa_yaw,
                duration=event.duration_s,
                clip=clip,
            )
            return
        fillers = getattr(self.config, "fillers", [])
        if state_before == InteractionState.SPEAKING:
            local = await self._local_text(clip)
            echo = self._echo_score(local)
            is_self = (await self._identify(clip)).is_self
            if is_self:
                echo = max(echo, 1.0)
            if echo >= float(getattr(self.config, "echo_similarity", 0.5)):
                # The microphone heard the robot itself (residual after hardware AEC).
                if doa_yaw is not None:
                    self._self_yaws.append(doa_yaw)
                if self.barge.ducked:
                    self.barge.ducked = False
                    self._duck(False, "echo")
                self._record(
                    "segment",
                    False,
                    f"echo ({echo:.2f})",
                    state_before,
                    doa=doa_yaw,
                    duration=event.duration_s,
                    text=local,
                    clip=clip,
                )
                return
            if is_filler(local, fillers) and doa_yaw is not None:
                # Content-less sound while the robot talks is almost always its own voice.
                self._self_yaws.append(doa_yaw)
            if not self.barge.ducked and not self.barge.stopped:
                # Not the addressee's direction: only a stop word or the wake name may stop.
                named = bool(local and self.names.match(local).hit) or bool(
                    await self._keyword(clip)
                )
                if (local and self.barge.is_stop_word(local)) or named:
                    self.barge.on_speech_start(event.ts, True)
                    await self._hard_stop("stop word or wake name", event, local_text=local)
                else:
                    self._record(
                        "segment",
                        False,
                        "not qualifying during speech",
                        state_before,
                        doa=doa_yaw,
                        duration=event.duration_s,
                        text=local,
                        clip=clip,
                    )
                return
            if is_filler(local, fillers) and event.duration_s < 1.5:
                local = None
            verdict = self.barge.on_speech_end(event.ts, event.duration_s, local)
            if verdict.action == "stop":
                await self._hard_stop(verdict.reason, event, local_text=local)
                return
            if verdict.action == "resume":
                self._duck(False, verdict.reason)
                self._record(
                    "segment",
                    False,
                    f"resume: {verdict.reason}",
                    state_before,
                    doa=doa_yaw,
                    duration=event.duration_s,
                    text=local,
                    clip=clip,
                )
            return
        local_text: str | None = None
        name: NameMatch | None = None
        if state_before == InteractionState.IDLE or self.barge.stopped:
            clip, merged = self._merge_short_segment(clip, event.ts)
            local_text, keyword = await asyncio.gather(self._local_text(clip), self._keyword(clip))
            name = self.names.match(local_text) if local_text else None
            if keyword and not (name is not None and name.hit):
                remainder = self.names.without_name(local_text) if local_text else ""
                name = NameMatch(True, 1.0, f"kws:{keyword}", remainder, local_text or "")
            if merged and name is not None and name.hit:
                Log.info("wake name found across two segments")
        elif state_before == InteractionState.ENGAGED:
            # Cheap check for the name / closing words without waiting for cloud ASR.
            local_text = await self._local_text(clip)
            name = self.names.match(local_text) if local_text else None
        recent_hit = event.ts - self._name_heard_at < 4.0
        if (
            recent_hit
            and not (name is not None and name.hit)
            and not is_filler(local_text, fillers)
        ):
            remainder = self.names.without_name(local_text) if local_text else ""
            name = NameMatch(True, 1.0, "kws-stream", remainder, local_text or "")
        if is_filler(local_text, fillers) and not (name is not None and name.hit):
            if event.duration_s < 1.5 and state_before == InteractionState.IDLE:
                self._short_segment = (event.segment.clip, event.ts)
            self._record(
                "segment",
                False,
                "self motion" if event.self_motion else "filler",
                state_before,
                doa=doa_yaw,
                duration=event.duration_s,
                text=local_text,
                clip=clip,
            )
            return
        voice = await self._identify(clip, event.duration_s)
        speaker, speaker_score = voice.speaker, voice.score
        if voice.is_self:
            self._record(
                "segment",
                False,
                f"self voice ({speaker_score:.2f})",
                state_before,
                doa=doa_yaw,
                duration=event.duration_s,
                text=local_text,
                clip=clip,
            )
            return
        person: str | None = None
        if speaker is not None and is_person(speaker):
            person, speaker = speaker, None  # seen before, no name yet: unknown for the gates
        elif speaker is not None and hasattr(self.contacts, "touch"):
            self.contacts.touch(speaker)  # last seen by voice (initiative rules)
        enrolling = self._enrolling(time.time())
        if enrolling is not None and speaker is None:
            person, speaker = None, enrolling  # the voice being learned: no new person:n
        gate = str(getattr(self.config, "speaker_gate", "soft"))
        if (
            gate == "strict"
            and speaker is None
            and not (name is not None and name.hit and state_before != InteractionState.IDLE)
        ):
            self._record(
                "segment",
                False,
                "strict gate: unknown voice",
                state_before,
                doa=doa_yaw,
                duration=event.duration_s,
                text=local_text,
                clip=clip,
                speaker=None,
            )
            return
        guest, voice_vector = (
            await self._person_for(clip, person, voice, event.duration_s)
            if speaker is None
            else (None, None)
        )
        gaze = (
            state_before == InteractionState.IDLE
            and speaker is not None
            and gate != "strict"
            and self._gaze_ok(event)
        )
        if gaze and not (name is not None and name.hit) and not is_filler(local_text, fillers):
            machine.begin_session(
                "gaze", event.ts, addressee=speaker, doa_yaw=doa_yaw, speaker=speaker
            )
            decision = EngagementDecision(
                True,
                "gaze + enrolled voice",
                machine.state,
                trigger="gaze",
                text=local_text,
                name_score=None,
            )
        else:
            decision = machine.on_segment(
                event.ts, event.duration_s, doa_yaw, name, speaker or guest, local_text
            )
        self._record(
            "segment",
            decision.accept,
            decision.reason,
            state_before,
            trigger=decision.trigger,
            name_score=decision.name_score,
            speaker=f"{speaker}:{speaker_score:.2f}"
            if speaker
            else (
                guest
                or (f"~{voice.near}:{speaker_score:.2f}" if voice.near else None)
                or (f"unknown:{speaker_score:.2f}" if speaker_score else None)
            ),
            doa=doa_yaw,
            duration=event.duration_s,
            text=local_text,
            clip=clip,
        )
        if not decision.accept:
            return
        if guest is not None and is_person(guest):
            merged_into = await self._attribute(guest, voice_vector, doa_yaw)
            if merged_into is not None:
                guest = merged_into
        await self._learn(voice, speaker)
        if state_before == InteractionState.IDLE:
            Log.info(f"engagement: {decision.reason} -> ENGAGED (local text {local_text!r})")
            self.attention.set_engaged(True)
            self.attention.on_speech(event.doa, force=True)
        else:
            self.attention.on_speech(event.doa)
        await self._maybe_enroll(clip, event, speaker)
        self.barge.reset()
        remainder = (decision.text or "").strip()
        session = machine.session
        if name is not None and name.hit and not remainder:
            # Only the name was said: the antennas flick and Banana answers the call out loud.
            self.attention.acknowledge()
            self._answer_call(
                speaker or guest or (session.speaker if session is not None else None)
            )
            return
        await self._start_turn(
            clip,
            event,
            fallback_text=remainder if name and name.hit else None,
            local_text=local_text,
            speaker=speaker or guest or (session.speaker if session is not None else None),
        )

    def _echo_score(self, local_text: str | None) -> float:
        """How much a transcript heard while speaking overlaps what the robot is saying."""
        if not local_text or self.pipeline is None or not self.pipeline.current_text:
            return 0.0
        heard = normalize(local_text)
        said = normalize(self.pipeline.current_text)
        if len(heard) < 2 or not said:
            return 0.0
        matcher = difflib.SequenceMatcher(None, heard, said)
        matched = sum(block.size for block in matcher.get_matching_blocks())
        return matched / len(heard)

    def _merge_short_segment(self, clip: AudioClip, now: float) -> tuple[AudioClip, bool]:
        """Prepend a recent short, content-less segment ("Banana," split off by a pause)."""
        pending, self._short_segment = self._short_segment, None
        if pending is None:
            return clip, False
        previous, ts = pending
        if now - ts > 2.5 or previous.sample_rate != clip.sample_rate:
            return clip, False
        gap = AudioClip.silence(0.15, clip.sample_rate)
        return previous.concat(gap).concat(clip), True

    def start_enrollment(self, contact_id: str, utterances: int = 3) -> bool:
        """Learn the next utterances of the open session as `contact_id`'s voice.

        Bound to that session and to `ENROLL_WINDOW_S` (block #63): when the session ends first,
        the enrollment is dropped, so no later voice is learned. False when no session is open.
        """
        session = self.machine.session if self.machine is not None else None
        if session is None:
            return False
        session.speaker = contact_id
        session.addressee = contact_id
        self._enrollment = (contact_id, max(1, utterances), session, time.time() + ENROLL_WINDOW_S)
        Log.info(f"voice enrollment started for {contact_id}: {utterances} utterance(s)")
        return True

    def _enrolling(self, now: float) -> str | None:
        """The contact being learned in the open session, or None (a stale enrollment is dropped)."""
        if self._enrollment is None:
            return None
        contact_id, _remaining, session, deadline = self._enrollment
        current = self.machine.session if self.machine is not None else None
        if current is session and now <= deadline:
            return contact_id
        self._enrollment = None
        why = "the session ended" if current is not session else "the window is over"
        Log.info(f"voice enrollment for {contact_id} dropped: {why}")
        return None

    async def _maybe_enroll(
        self, clip: AudioClip, event: FrontEndEvent, speaker: str | None
    ) -> None:
        contact_id = self._enrolling(time.time())
        if (
            contact_id is None
            or speaker != contact_id  # someone else, identified, spoke in the session
            or self.contacts is None
            or not getattr(self.contacts, "ready", False)
            or self._enrollment is None
        ):
            return
        _contact, remaining, session, deadline = self._enrollment
        try:
            used = await asyncio.to_thread(self.contacts.enroll_voice, contact_id, [clip])
        except Exception as exc:
            Log.warning(f"enroll: {exc!r}")
            used = 0
        if used:
            remaining -= 1
            self._record(
                "enroll",
                True,
                f"{contact_id}: {remaining} to go",
                InteractionState.ENGAGED,
                speaker=contact_id,
                duration=event.duration_s,
                clip=clip,
            )
        self._enrollment = (contact_id, remaining, session, deadline) if remaining > 0 else None
        if self._enrollment is None:
            Log.info(f"voice enrollment for {contact_id} complete")

    async def _person_for(
        self,
        clip: AudioClip,
        identified: str | None,
        voice: _Voice | None = None,
        speech_s: float | None = None,
    ) -> tuple[str | None, Any]:
        """(person id, voice vector) for an unknown voice.

        An identified `person:n` keeps its id; a new voice becomes a new person in the contact
        store (the first sample folded there), or a session guest when there is no store —
        unless it is close to a contact (`near`) or too short to say (block #80).
        """
        contacts = self.contacts
        if (
            contacts is None
            or not getattr(contacts, "ready", False)
            or not hasattr(contacts, "embed_voice")
        ):
            return identified, None
        if identified is None and (
            (voice is not None and voice.near is not None)
            or (speech_s is not None and speech_s < MIN_PERSON_SPEECH_S)
        ):
            return None, None
        vector = voice.vector if voice is not None and voice.vector is not None else None
        if vector is None:
            vector = await asyncio.to_thread(contacts.embed_voice, clip)
        if vector is None:
            return identified, None
        if identified is not None:
            return identified, vector
        if hasattr(contacts, "new_person") and getattr(contacts, "store", None) is not None:
            return await asyncio.to_thread(contacts.new_person, vector), None
        return self._guest_match(contacts, vector), None

    async def _guest_for(self, clip: AudioClip) -> str | None:
        """Tell unknown voices apart (session guests when no store, else persistent people)."""
        person_id, _ = await self._person_for(clip, None)
        return person_id

    def _guest_match(self, contacts: Any, vector: Any) -> str | None:
        """In-memory clustering for sessions without a contact store."""
        threshold = float(getattr(contacts, "voice_threshold", 0.5))
        best, best_score = None, 0.0
        for guest_id, known in self._guest_voices.items():
            score = float(contacts.voice_similarity(vector, known))
            if score > best_score:
                best, best_score = guest_id, score
        if best is not None and best_score >= threshold:
            mixed = self._guest_voices[best] * 0.8 + vector * 0.2
            self._guest_voices[best] = mixed / (float(np.linalg.norm(mixed)) or 1.0)
            return best
        guest_id = str(contacts.new_guest())
        if len(self._guest_voices) >= 8:
            self._guest_voices.pop(next(iter(self._guest_voices)))
        self._guest_voices[guest_id] = vector
        Log.info(f"new guest voice {guest_id} (best match {best_score:.2f})")
        return guest_id

    async def _attribute(
        self, person_id: str, voice_vector: Any, doa_yaw: float | None
    ) -> str | None:
        """Fold this utterance (and the face it came from, when the DoA agrees) into the person.

        Returns the contact the person was merged into when their voice turned out to be a
        contact's (block #80), else None.
        """
        contacts = self.contacts
        if contacts is None or not hasattr(contacts, "fold_person"):
            return None
        face_vector = None
        perception = self.perception
        if perception is not None and hasattr(perception, "faces") and doa_yaw is not None:
            faces = perception.faces()
            if faces:
                face = faces[0]
                azimuth = -((face["x"] + face["w"] / 2.0) * 2.0 - 1.0) * CAMERA_HALF_FOV_RAD
                large = face["w"] >= 0.12
                unnamed = not face.get("contact") or face.get("contact") == person_id
                if large and unnamed and yaw_distance(azimuth, doa_yaw) <= FACE_DOA_TOLERANCE_RAD:
                    face_vector = perception.local_face_vector()
        session = self.machine.session if self.machine is not None else None
        session_key = f"{session.started_at:.0f}" if session is not None else None
        person = await asyncio.to_thread(
            contacts.fold_person,
            person_id,
            voice=voice_vector,
            face=face_vector,
            session=session_key,
        )
        if person is None:
            return None
        if hasattr(contacts, "merge_person"):
            merged = await asyncio.to_thread(contacts.merge_person, person_id)
            if merged is not None:
                self.rename_speaker(person_id, merged)
                return str(merged)
        if not contacts.person_ready(person_id):
            return None
        contacts.mark_person(person_id, "ready")
        if self.perception is not None and hasattr(self.perception, "publish"):
            await self.perception.publish(
                PerceptionEvent(
                    "person.ready",
                    Severity.NOTICE,
                    {
                        "person_id": person_id,
                        "utterances": person.utterances,
                        "sessions": person.sessions,
                        "faces": person.face_samples,
                    },
                    time.time(),
                )
            )
            Log.info(f"{person_id} is ready to be befriended")
        return None

    async def _learn(self, voice: _Voice, speaker: str | None) -> None:
        """Fold an accepted utterance into the contact it is (block #80).

        Identified at the threshold, or uncertain (`near`) inside that contact's own session;
        uncertain ones of a session without a known speaker are kept until their mean decides.
        """
        contacts = self.contacts
        if voice.vector is None or contacts is None or not hasattr(contacts, "learn_voice"):
            return
        session = self.machine.session if self.machine is not None else None
        if speaker is not None and speaker == voice.speaker and not is_person(speaker):
            await asyncio.to_thread(contacts.learn_voice, speaker, voice.vector)
        elif speaker is None and voice.near is not None and session is not None:
            if session.speaker == voice.near:
                await asyncio.to_thread(contacts.learn_voice, voice.near, voice.vector)
            elif session.speaker is None or is_person(session.speaker):
                await self._session_mean(session, voice.near, voice.vector)

    async def _session_mean(self, session: Any, near: str, vector: Any) -> None:
        """Several uncertain utterances of one session: their mean may identify it."""
        contacts = self.contacts
        assert contacts is not None
        kept_session, kept_near, votes = self._unsure
        if kept_session is not session or kept_near != near:
            votes = []
        votes.append(vector)
        self._unsure = (session, near, votes)
        if len(votes) < SESSION_MEAN_MIN:
            return
        mean = np.mean(np.stack(votes), axis=0)
        mean = mean / (float(np.linalg.norm(mean)) or 1.0)
        result = await asyncio.to_thread(contacts.identify_vector, mean)
        if result.contact_id != near:
            return
        session.speaker = session.addressee = near
        for kept in votes:
            await asyncio.to_thread(contacts.learn_voice, near, kept)
        self._unsure = (None, None, [])
        Log.info(f"session identified as {near} from {len(votes)} utterances ({result.score:.2f})")

    def rename_speaker(self, old: str, new: str) -> None:
        """A person was befriended: the open session and the last caption follow the new id."""
        session = self.machine.session if self.machine is not None else None
        if session is not None:
            if session.addressee == old:
                session.addressee = new
            if session.speaker == old:
                session.speaker = new
        if self._heard is not None and self._heard[2] == old:
            self._heard = (self._heard[0], self._heard[1], new)

    def clip_for(self, row_id: str) -> AudioClip | None:
        """A decision's audio: the file under audio/ if any, else sliced from the recording ring."""
        trace = self.trace
        if trace is None:
            return None
        path = trace.clip_path(row_id)
        if path is not None:
            return decode_wav(path.read_bytes())
        window = trace.clip_window(row_id)
        if window is None or self.clip_source is None:
            return None
        return self.clip_source(window[0], window[1])

    def _speaker_label(self, speaker: str | None) -> str | None:
        """Display name for captions: contact name, or the raw guest id."""
        if speaker is None:
            return None
        contacts = self.contacts
        if contacts is not None and getattr(contacts, "ready", False):
            try:
                return str(contacts.display_name(speaker))
            except Exception:
                return speaker
        return speaker

    async def _identify(self, clip: AudioClip, speech_s: float | None = None) -> _Voice:
        """Who the utterance sounds like: speaker, score, self, `near` and the embedding.

        Less than `MIN_ID_SPEECH_S` of speech is not identified (block #80).
        """
        contacts = self.contacts
        if contacts is None or not getattr(contacts, "ready", False):
            return _Voice()
        if speech_s is not None and speech_s < MIN_ID_SPEECH_S:
            return _Voice()
        vector: Any = None
        try:
            if hasattr(contacts, "identify_vector") and hasattr(contacts, "embed_voice"):
                vector = await asyncio.to_thread(contacts.embed_voice, clip)
                if vector is None:
                    return _Voice()
                result = await asyncio.to_thread(contacts.identify_vector, vector)
            else:
                result = await asyncio.to_thread(contacts.identify_voice, clip)
        except Exception as exc:
            Log.debug(f"identify_voice: {exc!r}")
            return _Voice()
        return _Voice(
            result.contact_id,
            float(result.score),
            bool(result.is_self),
            getattr(result, "near", None),
            vector,
        )

    @staticmethod
    def _yaw_of(doa: BodyDoA | None) -> float | None:
        """A segment's direction as a head yaw; None when its readings disagree (block #80)."""
        if doa is None or doa.agreement < DOA_MIN_AGREEMENT:
            return None
        return doa_to_yaw(doa.angle)

    def _gaze_ok(self, event: FrontEndEvent) -> bool:
        """Gaze trigger: a frontal face right now whose direction is roughly the speech direction."""
        if (
            self.perception is None
            or self.machine is None
            or not self.machine.trigger_enabled("gaze")
        ):
            return False
        presence = self.perception.presence()
        if not (presence.face_visible and presence.frontal):
            return False
        if event.doa is None:
            return True
        yaw = doa_to_yaw(event.doa.angle)
        return abs(yaw) <= float(getattr(self.config, "doa_sector_tolerance_rad", 0.6))

    async def _keyword(self, clip: AudioClip) -> str | None:
        """Wake-name keyword spotting on the `asr.kws` slot (label or None)."""
        assert self.asr is not None
        if not self.asr.is_ready("kws"):
            return None
        result = await self.asr.transcribe("kws", clip, None, task="namespot.kws")
        text = (result.text or "").strip() if result.success else ""
        return text.split()[0] if text else None

    async def _local_text(self, clip: AudioClip) -> str | None:
        assert self.asr is not None
        if not self.asr.is_ready("local"):
            return None
        if clip.duration_s < 2.0:
            pad = AudioClip.silence(0.3, clip.sample_rate)
            clip = pad.concat(clip).concat(pad)
        result = await self.asr.transcribe("local", clip, None, task="namespot")
        return (result.text or "").strip() if result.success else None

    # ------------------------------------------------------------------- turns

    async def _start_turn(
        self,
        clip: AudioClip | None,
        event: FrontEndEvent | None,
        fallback_text: str | None = None,
        local_text: str | None = None,
        text: str | None = None,
        speaker: str | None = None,
    ) -> None:
        assert self.machine is not None and self.pipeline is not None and self.attention is not None
        self._cancel_call()
        await self._cancel_turn("new turn")
        session = self.machine.session
        speaker = speaker or (session.addressee if session is not None else "guest")
        language = self.default_language
        if self.contacts is not None and getattr(self.contacts, "ready", False):
            contact = self.contacts.get(speaker)
            if contact is not None and getattr(contact, "language", None):
                language = contact.language
        self.attention.thinking()
        meta = {
            "speaker": speaker,
            "clip": clip,
            "doa": doa_to_yaw(event.doa.angle)
            if event is not None and event.doa is not None
            else None,
            "local_text": local_text,
            "started": time.monotonic(),
        }
        names = self.names

        def strip_name(transcript: str) -> str:
            stripped = names.without_name(transcript) if names is not None else transcript
            if not stripped and fallback_text:
                return fallback_text
            return stripped

        def on_speaking(speaking: bool) -> None:
            assert self.machine is not None and self.attention is not None
            self.machine.on_robot_speaking(speaking, time.monotonic())
            self.attention.speaking(speaking)
            if speaking and self.barge is not None:
                self.barge.reset()

        def on_text_in(heard: str) -> None:
            self._heard = (heard, time.time(), speaker)

        self._turn = asyncio.create_task(
            self.pipeline.run_turn(
                speaker,
                language,
                clip=clip,
                text=text,
                speech_end=event.ts if event is not None else time.monotonic(),
                strip_name=strip_name,
                on_text_in=on_text_in,
                on_speaking=on_speaking,
            ),
            name="interaction-turn",
        )
        self._turn_meta[self._turn] = meta
        self._turn.add_done_callback(self._turn_finished)

    def _turn_finished(self, task: asyncio.Task[TurnResult]) -> None:
        assert self.machine is not None and self.attention is not None
        if task.cancelled():
            return
        try:
            result = task.result()
        except Exception as exc:
            Log.error(f"turn failed: {exc!r}")
            result = TurnResult(False, error=repr(exc))
        self.last_turn = result
        self.last_turn_at = time.time()
        meta = self._turn_meta.pop(task, {})
        if self._turn is task:
            self._turn = None
        now = time.monotonic()
        self.machine.on_robot_speaking(False, now)
        self._duck(False, "turn end")
        timing: dict[str, Any] = dict(result.timing.as_dict())
        if self.pipeline is not None and self.pipeline.last_shadow is not None:
            timing["asr_shadow"] = self.pipeline.last_shadow
            self.pipeline.last_shadow = None
        if self.pipeline is not None and self.pipeline.last_raw_transcript is not None:
            timing["asr_text_raw"] = self.pipeline.last_raw_transcript
            self.pipeline.last_raw_transcript = None
        Log.info(
            f"turn {'ok' if result.ok else 'failed'} in={result.text_in!r} out={result.text_out[:60]!r} "
            f"asr={timing['asr_ms'] and round(timing['asr_ms'])} first_token={timing['first_token_ms'] and round(timing['first_token_ms'])} "
            f"first_audio={timing['first_audio_ms'] and round(timing['first_audio_ms'])} total={timing['total_ms'] and round(timing['total_ms'])} ms"
            + (" interrupted" if result.interrupted else "")
            + (f" error={result.error}" if result.error else "")
        )
        self._record(
            "turn",
            result.ok,
            "interrupted"
            if result.interrupted
            else (result.error or ("no_reply" if result.no_reply else "ok")),
            InteractionState.SPEAKING,
            speaker=meta.get("speaker"),
            doa=meta.get("doa"),
            text=result.text_in or meta.get("local_text"),
            reply=result.text_out,
            timing=timing,
            clip=meta.get("clip"),
        )
        if result.interrupted:
            return
        decision = self.machine.on_turn_done(
            now, result.text_in, result.no_reply, reply=result.text_out
        )
        if decision is not None and decision.end_session:
            self._session_ended(decision.reason)
        elif self.machine.session is not None:
            self.attention.speaking(False)

    async def _cancel_turn(self, reason: str) -> None:
        task = self._turn
        if task is None or task.done():
            return
        Log.info(f"cancelling turn: {reason}")
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        if self.pipeline is not None:
            await self.pipeline.interrupt()
        if self._turn is task:
            self._turn = None

    async def _hard_stop(
        self, reason: str, event: FrontEndEvent, local_text: str | None = None
    ) -> None:
        assert self.machine is not None and self.attention is not None
        Log.info(f"barge-in stop: {reason}")
        self._cancel_call()
        self._record(
            "barge_in",
            True,
            f"stop: {reason}",
            InteractionState.SPEAKING,
            doa=doa_to_yaw(event.doa.angle) if event.doa else None,
            duration=event.duration_s,
            text=local_text,
            clip=event.segment.clip if event.segment else None,
        )
        await self._cancel_turn(f"barge-in {reason}")
        self.machine.on_robot_speaking(False, event.ts)
        self._duck(False, "stopped")
        self.attention.on_speech(event.doa)
        if event.segment is not None and self.barge is not None:
            # The interrupting utterance is the next turn unless it was only a stop word or
            # only the robot's name.
            text = local_text or ""
            only_name = bool(
                self.names and self.names.match(text).hit and not self.names.match(text).remainder
            )
            if text and not self.barge.only_stop_word(text) and not only_name:
                self.barge.reset()
                await self._start_turn(event.segment.clip, event, local_text=local_text)
            else:
                self.barge.reset()
                self.attention.set_engaged(True)
                if only_name:  # the name called over a story: stop, then answer the call
                    session = self.machine.session
                    self._answer_call(session.speaker if session else None)

    def _answer_call(self, speaker: str | None) -> None:
        """Only the name: answer out loud now (block #92), unless they are already going on.

        A nod and the antennas were all a first-time caller got, and they thought Banana was
        broken. The answer is a clip made at start, so it plays as soon as the name is
        recognised; when they already speak again ("Banana, … 今日天氣點呀"), their sentence is
        the answer and nothing is said.
        """
        if self._speech_since is not None:
            return
        language = self.default_language
        if speaker and self.contacts is not None and getattr(self.contacts, "ready", False):
            contact = self.contacts.get(speaker)
            language = getattr(contact, "language", None) or language
        text, clip = self.calls.pick(language)
        self._cancel_call()
        self._call_task = asyncio.create_task(self._say_call(text, clip), name="call-answer")

    async def _say_call(self, text: str, clip: AudioClip | None) -> None:
        assert self.machine is not None and self.attention is not None and self.body is not None
        machine = self.machine
        if clip is None:  # not synthesized yet (or TTS down): through the stream
            await self.say(text)
        else:
            if self.pipeline is not None:
                self.pipeline.current_text = text  # the echo guard compares with this
            machine.on_robot_speaking(True, time.monotonic())
            self.attention.speaking(True)
            try:
                self.body.speak(clip)
                await asyncio.to_thread(self.body.wait_quiet, clip.duration_s + 2.0)
            finally:
                machine.on_robot_speaking(False, time.monotonic())
                self.attention.speaking(False)
                self._duck(False, "call answered")
                if self.barge is not None:
                    self.barge.reset()
            self._record("say", True, "call answered", InteractionState.SPEAKING, reply=text)
        if machine.session is not None:
            machine.session.asked = True  # the answer invites them: wait as after a question

    def _cancel_call(self) -> None:
        """Their sentence comes in while Banana answers the call: the answer stops."""
        task = self._call_task
        if task is not None and not task.done():
            task.cancel()
            if self.body is not None:
                self.body.stop_speaking()

    def _duck(self, on: bool, reason: str) -> None:
        assert self.body is not None and self.attention is not None
        if on:
            self.body.duck(float(getattr(self.config, "duck_db", -12.0)))
            self.attention.ducked(True)
            self._record("barge_in", True, f"duck: {reason}", InteractionState.SPEAKING)
        else:
            self.body.unduck()

    def _session_ended(self, reason: str) -> None:
        assert self.attention is not None
        Log.info(f"session ended: {reason}")
        self._guest_voices.clear()
        self.attention.set_engaged(False)
        self._record("session", False, f"end: {reason}", InteractionState.ENGAGED)

    # ------------------------------------------------------------------ hold

    @property
    def held(self) -> str | None:
        """Who parked the front end, if anyone."""
        return self._held

    async def hold(self, reason: str = "controller") -> None:
        """Park the front end: cancel the turn, drop events until `release_hold()`."""
        Log.info0(reason)
        self._held = reason
        self._speech_since = None
        await self._cancel_turn(f"held: {reason}")
        if self.body is not None:
            self.body.stop_speaking()
        if self.machine is not None and self.machine.session is not None:
            self.machine.end_session(f"held: {reason}", time.monotonic())
            self._record("session", False, f"end: held {reason}", InteractionState.ENGAGED)

    def release_hold(self) -> None:
        """Resume: events flow again and the idle posture is restored."""
        Log.info0(self._held or "")
        self._held = None
        if self.attention is not None and self.started:
            self.attention.set_engaged(False)

    # -------------------------------------------------------- robot-initiated

    def can_speak(self) -> bool:
        """Whether an unprompted message may be spoken now (the agent's `auto` delivery)."""
        if not self.started or self.body is None or not self.body.awake:
            return False
        if self.perception is None or not getattr(self.perception, "enabled", True):
            return True
        return bool(self.perception.presence().someone_present)

    async def speak(self, text: str, expression: str | None = None) -> bool:
        """Say an unprompted message (the agent's delivery); False when nothing was spoken."""
        if not self.started:
            return False
        result = await self.say(text, expression)
        return bool(result.ok)

    async def say(
        self, text: str, expression: str | None = None, addressee: str | None = None
    ) -> TurnResult:
        """Speak text in the room (automation / dashboard); opens a session for follow-ups."""
        assert self.machine is not None and self.pipeline is not None and self.attention is not None
        if not self.machine.robot_initiated(time.monotonic(), addressee):
            return TurnResult(False, error="body asleep")
        await self._cancel_turn("robot initiated")
        if expression and self.expressions is not None:
            self.expressions.express(expression)
        if self._held is None:
            self.attention.set_engaged(True)
        timing = TurnTiming(speech_end=time.monotonic())

        class _Fixed:
            def __init__(self, reply: str) -> None:
                self.reply = reply

            async def respond(self, message: ChannelMessage) -> Any:
                yield self.reply

        pipeline = self.pipeline
        saved = pipeline.responder
        pipeline.responder = _Fixed(text)
        try:
            message = ChannelMessage(
                "voice", addressee or "household", text, language=self.default_language
            )

            def on_speaking(speaking: bool) -> None:
                assert self.machine is not None and self.attention is not None
                self.machine.on_robot_speaking(speaking, time.monotonic())
                self.attention.speaking(speaking)

            self._turn = asyncio.create_task(
                pipeline.speak_reply(message, timing, on_speaking), name="interaction-say"
            )
            try:
                result = await self._turn
            except asyncio.CancelledError:
                result = TurnResult(False, text_out=text, interrupted=True)
            finally:
                self._turn = None
        finally:
            pipeline.responder = saved
        self.machine.on_robot_speaking(False, time.monotonic())
        self.last_turn = result
        self.last_turn_at = time.time()
        self._record(
            "say",
            result.ok,
            "robot initiated",
            InteractionState.SPEAKING,
            reply=text,
            timing=result.timing.as_dict(),
        )
        return result

    # ------------------------------------------------------------- reporting

    def _record(
        self,
        event: str,
        accept: bool,
        reason: str,
        state: InteractionState,
        *,
        trigger: str | None = None,
        name_score: float | None = None,
        speaker: str | None = None,
        doa: float | None = None,
        duration: float | None = None,
        text: str | None = None,
        reply: str | None = None,
        clip: AudioClip | None = None,
        timing: dict[str, Any] | None = None,
    ) -> None:
        row: dict[str, Any] = {
            "ts": time.time(),
            "state": state.value,
            "event": event,
            "decision": "accept" if accept else "reject",
            "reason": reason,
            "trigger": trigger,
            "name_score": name_score,
            "speaker": speaker,
            "doa": doa,
            "duration_s": duration,
            "text": text,
            "reply": reply,
            "timing": timing,
        }
        if self.trace is not None:
            try:
                row["id"] = self.trace.record(
                    state.value,
                    event,
                    row["decision"],
                    reason,
                    trigger=trigger,
                    name_score=name_score,
                    speaker=speaker,
                    doa=doa,
                    duration_s=duration,
                    text=text,
                    reply=reply,
                    clip=clip,
                    timing=timing,
                )
            except Exception as exc:
                Log.warning(f"trace write failed: {exc!r}")
        self.recent.appendleft(row)

    def snapshot(self) -> dict[str, Any]:
        """Live state for the dashboard."""
        machine = self.machine.snapshot() if self.machine is not None else {"state": "unconfigured"}
        last = self.last_turn
        return {
            **machine,
            "started": self.started,
            "held": self._held,
            "level_dbfs": round(self.level_dbfs, 1),
            "ducked": bool(self.barge.ducked) if self.barge is not None else False,
            "speaking": self.body.is_speaking() if self.body is not None else False,
            "turn_running": self._turn is not None and not self._turn.done(),
            "tts_connected": self.pipeline.keeper.connected if self.pipeline is not None else False,
            "self_sector_yaw": self.self_sector_yaw(),
            "last_turn": None
            if last is None
            else {
                "ok": last.ok,
                "text_in": last.text_in,
                "text_out": last.text_out,
                "interrupted": last.interrupted,
                "no_reply": last.no_reply,
                "error": last.error,
                "timing": last.timing.as_dict(),
            },
            "frontend": None
            if self._frontend is None
            else {
                "chunks": self._frontend.chunks,
                "segments": self._frontend.segments,
                "self_motion_segments": self._frontend.self_motion_segments,
            },
            "attention": self.attention.snapshot() if self.attention is not None else None,
            "initiative": self.initiative.snapshot() if self.initiative is not None else None,
        }

    def captions(self) -> dict[str, Any]:
        """What the Live view shows as subtitles: an open segment, the last heard and said text."""
        pipeline = self.pipeline
        said = pipeline.current_text if pipeline is not None else ""
        in_session = self.machine is not None and self.machine.state in (
            InteractionState.ENGAGED,
            InteractionState.SPEAKING,
        )
        return {
            "listening": self._speech_since is not None and in_session,
            "speech_open": self._speech_since is not None,
            "listening_since": self._speech_since,
            "heard": self._heard[0] if self._heard is not None else None,
            "heard_at": self._heard[1] if self._heard is not None else None,
            "heard_by": self._speaker_label(self._heard[2]) if self._heard is not None else None,
            "said": said or None,
            "turn_running": self._turn is not None and not self._turn.done(),
        }

    def live(self) -> dict[str, Any]:
        """Vital signs for the Live page, from memory only (block #69).

        The engagement machine, the time left before a session times out, the turn in progress
        (its marks so far, the first audio from the body) or else the last one, the newest
        decisions, the attention mode and the initiative budget.
        """
        machine = self.machine
        session = machine.session if machine is not None else None
        state = machine.state if machine is not None else None
        now = time.monotonic()
        timeout = float(getattr(self.config, "session_timeout_s", 8.0))
        pipeline = self.pipeline
        keeper = pipeline.keeper if pipeline is not None else None
        running = self._turn is not None and not self._turn.done()
        timing = pipeline.timing if pipeline is not None else None
        turn: dict[str, Any] | None = None
        if running and timing is not None:
            heard = self._heard
            turn = {
                "running": True,
                "speaker": self._speaker_label(heard[2]) if heard is not None else None,
                "text_in": heard[0] if heard is not None else None,
                "said": pipeline.current_text if pipeline is not None else "",
                "marks": timing.marks(
                    self.body.speech_turn_first_push() if self.body is not None else None
                ),
            }
        elif self.last_turn is not None:
            last = self.last_turn
            turn = {
                "running": False,
                "at": self.last_turn_at,
                "text_in": last.text_in,
                "text_out": last.text_out,
                "ok": last.ok,
                "interrupted": last.interrupted,
                "no_reply": last.no_reply,
                "error": last.error,
                "marks": last.timing.marks(),
            }
        decisions = [
            {
                "ts": row["ts"],
                "event": row["event"],
                "decision": row["decision"],
                "reason": row["reason"],
                "trigger": row.get("trigger"),
                "speaker": self._speaker_label(row.get("speaker")),
                "text": (row.get("text") or "")[:60] or None,
            }
            for row in list(self.recent)[:3]
        ]
        initiative = self.initiative.snapshot() if self.initiative is not None else None
        return {
            "state": state.value if state is not None else "off",
            "reason": machine.last_transition_reason if machine is not None else None,
            "held": self._held,
            "ducked": bool(self.barge.ducked) if self.barge is not None else False,
            "speaking": self.body.is_speaking() if self.body is not None else False,
            "speech_open": self._speech_since is not None,
            "session": None
            if session is None
            else {
                "addressee": self._speaker_label(session.addressee),
                "trigger": session.trigger,
                "turns": session.turns,
                "age_s": round(now - session.started_at, 1),
                "left_s": round(max(0.0, timeout - (now - session.last_activity)), 1)
                if state == InteractionState.ENGAGED and not running
                else None,
            },
            "turn": turn,
            "decisions": decisions,
            "attention": self.attention.snapshot() if self.attention is not None else None,
            "initiative": initiative,
            "tts": None
            if keeper is None
            else {
                "connected": keeper.connected,
                "connects": keeper.connects,
                "error": keeper.error,
            },
            "segments": self._frontend.segments if self._frontend is not None else None,
        }

    def telemetry(self) -> dict[str, Any]:
        """Compact interaction state for the recorder's telemetry rows (`record` extra)."""
        machine = self.machine
        session = machine.session if machine is not None else None
        captions = self.captions()
        return {
            "state": machine.state.value if machine is not None else "off",
            "who": session.addressee if session is not None else None,
            "trigger": session.trigger if session is not None else None,
            "ducked": bool(self.barge.ducked) if self.barge is not None else False,
            "turn": captions["turn_running"],
            "listening": captions["listening"],
            "speech": captions["speech_open"],
            "heard_at": captions["heard_at"],
            "saying": bool(captions["said"]) and captions["turn_running"],
        }

    def activity(self, since: float = 0.0, limit: int = 30) -> list[dict[str, Any]]:
        """Decisions for the Live activity stream, newest first.

        Accepted ones, barge-ins, sessions, touches and Banana's own lines; a rejected ambient
        segment (the TV, people talking to each other) is left to the Voice page.
        """
        rows = []
        for row in self.recent:
            if row["ts"] <= since:
                break
            if row["event"] == "segment" and row["decision"] != "accept":
                continue
            who = self._speaker_label(row.get("speaker"))
            text = row.get("text") or row.get("reply") or ""
            rows.append(
                {
                    "ts": row["ts"],
                    "module": "interaction",
                    "text": f"{row['event']} {row['decision']}: {row['reason']}"
                    + (f" · {who}" if who else "")
                    + (f" · {text[:50]}" if text else ""),
                    "level": "info" if row["decision"] == "accept" else "dim",
                }
            )
        return rows[:limit]

    def recent_decisions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Newest decisions (from the trace when available)."""
        if self.trace is not None:
            return self.trace.recent(limit)
        return list(self.recent)[:limit]
