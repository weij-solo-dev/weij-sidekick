"""End-to-end voice front end with fakes: wake name → turn → speech → barge-in → session end."""

from __future__ import annotations

import asyncio
import math
import time

import numpy as np
import pytest

from sidekick.asr import ASRResult, ASRSession
from sidekick.audio import AudioClip
from sidekick.body import BodyDoA, BodyNullBackend, BodySession
from sidekick.channel import ChannelMessage
from sidekick.config import ConfigInteraction, ConfigRobot
from sidekick.interaction import InteractionSession, InteractionState
from sidekick.tts import TTSResult, TTSSession, TTSStreamEvent
from sidekick.vad import VADSegment, VADSession

SR = 16000


class FakeVAD:
    """Energy detector: |x| > 0.1 is speech; 10 silent chunks close a segment."""

    sample_rate = SR
    window_size = 320

    def __init__(self):
        self._speech = False
        self._buf = []
        self._silence = 0
        self._segments = []
        self._pos = 0

    def feed(self, samples):
        self._pos += len(samples)
        loud = float(np.abs(samples).max()) > 0.1 if len(samples) else False
        if loud:
            self._speech = True
            self._silence = 0
            self._buf.append(np.asarray(samples, dtype=np.float32))
        elif self._speech:
            self._silence += 1
            self._buf.append(np.asarray(samples, dtype=np.float32))
            if self._silence >= 10:
                data = np.concatenate(self._buf)
                end = self._pos / SR
                self._segments.append(VADSegment(AudioClip(data, SR), end - len(data) / SR, end))
                self._speech = False
                self._buf = []
                self._silence = 0

    def is_speech(self):
        return self._speech

    def pop_segments(self):
        out, self._segments = self._segments, []
        return out

    def flush(self):
        pass

    def reset(self):
        self.__init__()


class FakeASR:
    def __init__(self, name):
        self.name = name
        self.script = []
        self.calls = []

    async def transcribe(self, clip, language=None):
        self.calls.append((round(clip.duration_s, 2), language))
        text = self.script.pop(0) if self.script else ""
        await asyncio.sleep(0.02)
        return ASRResult(
            True,
            text,
            "fake",
            self.name,
            "fake-1",
            "****",
            language=language or "yue",
            latency_ms=20,
        )


class FakeStream:
    def __init__(self, backend):
        self.backend = backend
        self.q = asyncio.Queue()
        self.sent = []
        self.canceled = 0
        self.closed = False

    async def send(self, text):
        self.sent.append(text)
        seconds = max(0.2, 0.08 * len(text))
        pcm = (0.3 * np.sin(np.arange(int(seconds * SR)) * 0.05)).astype(np.float32)
        await self.q.put(TTSStreamEvent("sentence_start"))
        await asyncio.sleep(0.05)
        await self.q.put(TTSStreamEvent("audio", audio=AudioClip(pcm, SR).to_pcm16_bytes()))
        await self.q.put(TTSStreamEvent("sentence_end"))

    async def flush(self):
        await self.q.put(TTSStreamEvent("flushed"))

    async def cancel(self):
        self.canceled += 1
        await self.q.put(TTSStreamEvent("canceled"))

    async def finish(self):
        await self.q.put(TTSStreamEvent("finished"))

    async def events(self):
        while True:
            ev = await self.q.get()
            yield ev
            if ev.kind in ("finished", "error"):
                return

    async def aclose(self):
        self.closed = True


class FakeTTS:
    def __init__(self):
        self.streams = []

    async def open_stream(self):
        s = FakeStream(self)
        self.streams.append(s)
        return s

    async def infer(self, text):
        return TTSResult(
            True, AudioClip.silence(0.3).to_pcm16_bytes(), "fake", "fake", "m", "v", "****"
        )


class FakeResponder:
    def __init__(self):
        self.reply = "今日好天呀。記得帶遮。"
        self.delay = 0.01
        self.messages = []

    async def respond(self, message: ChannelMessage):
        self.messages.append(message)
        for i in range(0, len(self.reply), 3):
            await asyncio.sleep(self.delay)
            yield self.reply[i : i + 3]


def speech(seconds):
    return (0.5 * np.sin(np.arange(int(seconds * SR)) * 0.1)).astype(np.float32)


async def wait_for(pred, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        await asyncio.sleep(0.02)
    return pred()


@pytest.fixture
def stack(tmp_path):
    backend = BodyNullBackend()
    body = BodySession(backend, poll_hz=20.0)
    body.connect()
    asr = ASRSession()
    local, primary = FakeASR("local"), FakeASR("primary")
    asr.setup("local", local)
    asr.setup("primary", primary)
    tts = TTSSession()
    fake_tts = FakeTTS()
    tts.setup("primary", fake_tts)
    vad = VADSession()
    vad.setup("primary", FakeVAD)
    responder = FakeResponder()
    session = InteractionSession()
    session.setup(
        body,
        asr,
        tts,
        vad,
        ConfigInteraction(session_timeout_s=2.0, asr_slot="primary", shadow_asr=False),
        ConfigRobot(),
        responder,
        trace_path=tmp_path / "interaction_trace_v1.db",
        audio_dir=tmp_path / "audio",
    )
    yield backend, body, session, local, primary, fake_tts, responder
    body.close()


async def test_wake_name_turn_and_timeout(stack):
    backend, _body, session, local, primary, fake_tts, responder = stack
    await session.start()
    try:
        # A sentence without the name stays local and is rejected.
        local.script = ["今日天氣好好"]
        backend.feed_audio(np.zeros(SR // 2, np.float32))
        backend.feed_audio(speech(1.0))
        backend.feed_audio(np.zeros(SR // 2, np.float32))
        assert await wait_for(lambda: any(r["event"] == "segment" for r in session.recent), 10.0)
        assert session.machine.state == InteractionState.IDLE
        assert primary.calls == []  # invariant 17: nothing went to the cloud slot
        # Wake name + question: engaged, cloud ASR on the clip, reply spoken.
        local.script = ["BANANA 今日天氣點呀"]
        primary.script = ["Banana，今日天氣點呀？"]
        backend.feed_audio(speech(1.2))
        backend.feed_audio(np.zeros(SR // 2, np.float32))
        assert await wait_for(lambda: session.last_turn is not None and session.last_turn.ok, 15.0)
        turn = session.last_turn
        assert turn.text_in == "今日天氣點呀？" and "今日好天呀" in turn.text_out
        assert (
            responder.messages[0].channel == "voice"
            and responder.messages[0].text == "今日天氣點呀？"
        )
        assert primary.calls and primary.calls[0][1] == "zh"  # the household's language
        assert fake_tts.streams and fake_tts.streams[0].sent[0].startswith("今日好天呀")
        assert backend.spoken_seconds() > 0.3
        assert turn.timing.first_audio_ms is not None and turn.timing.total_ms is not None
        assert session.machine.state in (InteractionState.ENGAGED, InteractionState.SPEAKING)
        # our own detector keeps faces centred; the daemon's tracker stays off (`face_tracker: own`)
        assert backend.tracking[0] is False and session.attention.snapshot()["tracker"] == "own"
        # Follow-up without the name while engaged.
        local.script = ["咁明日呢"]
        primary.script = ["咁明日呢？"]
        backend.feed_audio(speech(0.8))
        backend.feed_audio(np.zeros(SR // 2, np.float32))
        assert await wait_for(lambda: len(responder.messages) == 2, 8.0)
        assert responder.messages[1].text == "咁明日呢？"
        # Silence timeout ends the session.
        assert await wait_for(lambda: session.machine.state == InteractionState.IDLE, 8.0)
        assert backend.tracking[0] is False  # still our own tracker, idle glances resume
        rows = session.recent_decisions(100)
        assert any(r["event"] == "session" and "timeout" in r["reason"] for r in rows)
        assert any(r["event"] == "turn" and r["clip"] for r in rows)
    finally:
        await session.stop()


async def test_only_the_name_is_answered_out_loud_at_once(stack):
    """Block #92: the name alone got a flick of the antennas, and first-time callers thought
    the robot was broken. The answer is a clip made at start: no model call, no cloud ASR."""
    from sidekick.interaction.call import CALL_ANSWERS

    backend, _body, session, local, primary, _fake_tts, responder = stack
    await session.start()
    try:
        assert await wait_for(lambda: len(session.calls.clips) >= 4, 5.0)  # made at start
        local.script = ["BANANNA BANANA"]
        backend.feed_audio(speech(1.2))
        backend.feed_audio(np.zeros(SR // 2, np.float32))
        assert await wait_for(
            lambda: any(r["reason"] == "call answered" for r in session.recent), 10.0
        )
        row = next(r for r in session.recent if r["reason"] == "call answered")
        assert row["reply"] in CALL_ANSWERS["zh"]
        assert responder.messages == [] and primary.calls == []
        assert session.machine.session is not None and session.machine.session.asked
        # what they say next is the turn, without the name
        local.script = ["今日天氣點呀"]
        primary.script = ["今日天氣點呀？"]
        backend.feed_audio(speech(1.0))
        backend.feed_audio(np.zeros(SR // 2, np.float32))
        assert await wait_for(lambda: len(responder.messages) == 1, 10.0)
        assert responder.messages[0].text == "今日天氣點呀？"
        # already talking again when the name is recognised: their sentence is the answer
        session._speech_since = time.time()
        session._call_task = None
        session._answer_call(None)
        assert session._call_task is None
    finally:
        await session.stop()


async def test_barge_in_ducks_then_stops_and_touch_engages(stack):
    backend, _body, session, local, primary, fake_tts, responder = stack
    responder.reply = "我同你講個好長嘅故事。" * 6
    responder.delay = 0.05
    await session.start()
    try:
        # Touch engages (no name needed).
        await asyncio.sleep(0.6)
        backend.push_antenna("left", 0.6)
        assert await wait_for(lambda: session.machine.state == InteractionState.ENGAGED, 3.0)
        backend.push_antenna("left", 0.0)
        local.script = ["講個故事"]
        primary.script = ["講個故事"]
        backend.feed_audio(speech(0.8))
        backend.feed_audio(np.zeros(SR // 2, np.float32))
        assert await wait_for(lambda: session.machine.state == InteractionState.SPEAKING, 8.0)
        assert await wait_for(lambda: backend.spoken_seconds() > 0.2, 3.0)
        # Sustained speech from a known direction: duck then hard stop; the utterance is the next turn.
        backend.doa_value = BodyDoA(angle=math.pi / 2, speech=True)
        await asyncio.sleep(0.3)  # let the body monitor cache the direction
        assert await wait_for(lambda: not _body.moving(), 3.0)  # the thinking tilt is over
        local.script = ["等一下 我想問另一樣嘢"]
        primary.script = ["我想問另一樣嘢"]
        responder.reply = "好呀。"
        responder.delay = 0.01
        backend.feed_audio(speech(1.0))
        backend.feed_audio(np.zeros(SR // 2, np.float32))
        assert await wait_for(
            lambda: any(
                r["event"] == "barge_in" and r["reason"].startswith("stop") for r in session.recent
            ),
            5.0,
        )
        assert any(
            r["event"] == "barge_in" and r["reason"].startswith("duck") for r in session.recent
        )
        assert backend.cleared >= 1
        assert fake_tts.streams[-1].canceled >= 1
        assert await wait_for(
            lambda: (
                len(responder.messages) >= 2
                and session.last_turn is not None
                and session.last_turn.text_in == "我想問另一樣嘢"
            ),
            8.0,
        )
    finally:
        await session.stop()


async def test_say_opens_session_and_speaks(stack):
    backend, _body, session, *_ = stack
    await session.start()
    try:
        result = await session.say("早晨呀", expression="nod")
        assert result.ok and backend.spoken_seconds() > 0.1
        assert (
            session.machine.session is not None
            and session.machine.session.trigger == "robot_initiated"
        )
        snap = session.snapshot()
        assert snap["state"] in ("engaged", "speaking") and snap["tts_connected"]
    finally:
        await session.stop()


def test_hold_and_release_on_a_bare_session():
    session = InteractionSession()
    assert session.held is None and session.snapshot()["held"] is None
    asyncio.run(session.hold("controller"))
    assert session.held == "controller" and session.snapshot()["held"] == "controller"
    session.release_hold()
    assert session.held is None


async def test_speech_inside_our_own_motion_is_labelled_self_motion(stack):
    backend, body, session, local, *_ = stack
    await session.start()
    try:
        await asyncio.sleep(0.4)
        assert await wait_for(lambda: not body.moving(), 3.0)
        local.script = ["", ""]
        body.look(yaw=0.8, duration_s=0.6)  # a glance: the head motors run for ~0.9 s
        assert await wait_for(lambda: body.moving(), 1.0)
        backend.feed_audio(speech(0.3))
        backend.feed_audio(np.zeros(SR // 2, np.float32))
        assert await wait_for(
            lambda: any(r["reason"] == "self motion" for r in session.recent), 5.0
        )
        assert session.snapshot()["frontend"]["self_motion_segments"] >= 1
        # the Live page only says "listening" inside a session; the raw flag stays available
        captions = session.captions()
        assert captions["listening"] is False and "speech_open" in captions
        # a clean segment well after the motion is an ordinary rejection
        assert await wait_for(lambda: not body.moving(), 3.0)
        backend.feed_audio(speech(0.3))
        backend.feed_audio(np.zeros(SR // 2, np.float32))
        assert await wait_for(lambda: any(r["reason"] == "filler" for r in session.recent), 5.0)
    finally:
        await session.stop()


class FlushRecordingStream(FakeStream):
    """A fake bidi stream that logs the order of sends and flushes."""

    def __init__(self, backend):
        super().__init__(backend)
        self.log = []

    async def send(self, text):
        self.log.append(("send", text))
        await super().send(text)

    async def flush(self):
        self.log.append(("flush", None))
        await super().flush()


class SlowResponder:
    """Streams a reply in timed pieces: (text, pause after)."""

    def __init__(self, pieces):
        self.pieces = pieces

    async def respond(self, message):
        for text, pause in self.pieces:
            yield text
            await asyncio.sleep(pause)


async def _speak(pieces):
    from sidekick.interaction.expression import ExpressionMapper
    from sidekick.interaction.pipeline import TurnPipeline
    from sidekick.interaction.schemas import TurnTiming

    backend = BodyNullBackend()
    body = BodySession(backend, poll_hz=20.0)
    body.connect()
    tts = TTSSession()

    class Backend(FakeTTS):
        async def open_stream(self):
            s = FlushRecordingStream(self)
            self.streams.append(s)
            return s

    fake = Backend()
    tts.setup("primary", fake)
    try:
        pipeline = TurnPipeline(
            ASRSession(), tts, body, SlowResponder(pieces), ExpressionMapper(body), shadow_asr=False
        )
        result = await pipeline.speak_reply(
            ChannelMessage("voice", "dad", "hi"), TurnTiming(speech_end=time.monotonic())
        )
        return result, fake.streams[0].log, pipeline.keeper
    finally:
        body.close()


async def test_open_first_clause_is_flushed_early_and_the_turn_still_ends():
    """The TTS server waits for a sentence end: an open first clause is flushed (block #71)."""
    result, log, keeper = await _speak([("冇問題呀，", 0.4), ("聽日兩點半提你。", 0.0)])
    assert result.ok and result.text_out.startswith("冇問題呀")
    assert log[:2] == [("send", "冇問題呀，"), ("flush", None)]  # before the rest arrived
    # the clause, the sentence as it ends (block #76), the turn's end
    assert log[2:] == [("send", "聽日兩點半提你。"), ("flush", None), ("flush", None)]
    assert keeper.eager_flushes == 1 and keeper.flushes_pending == 0
    assert keeper.pauses == 0  # after a comma the server's own gap is right


async def test_a_quick_first_sentence_goes_out_whole():
    result, log, keeper = await _speak([("冇問題呀，", 0.02), ("聽日提你。", 0.0)])
    assert result.ok
    assert log == [
        ("send", "冇問題呀，"),
        ("send", "聽日提你。"),
        ("flush", None),  # the sentence
        ("flush", None),  # the turn's end
    ]
    assert keeper.eager_flushes == 0


async def test_a_full_stop_gets_a_pause_before_the_next_sentence():
    """The server leaves ~0.2 s between sentences, like a comma: a full stop adds its own."""
    result, log, keeper = await _speak([("好，等我睇下。", 0.0), ("今日天氣好好。", 0.0)])
    assert result.ok
    assert log == [
        ("send", "好，等我睇下。"),
        ("flush", None),
        ("send", "今日天氣好好。"),
        ("flush", None),
        ("flush", None),
    ]
    assert keeper.pauses == 1  # the first sentence was still playing


async def test_no_pause_is_added_to_a_silence_that_already_happened():
    """A tool round already left the speaker quiet longer than the pause: nothing is added."""
    result, _log, keeper = await _speak([("好，等我睇下。", 1.2), ("今日天氣好好。", 0.0)])
    assert result.ok and keeper.pauses == 0
