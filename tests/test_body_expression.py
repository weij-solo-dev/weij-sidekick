"""Bobby's own expressions: the library, the curves, plays, the motion owner's layers, styles."""

from __future__ import annotations

import asyncio
import itertools
import json
import math
import time

import numpy as np

from sidekick.body import BodyNullBackend, BodySession, ExpressionPlay, load_library
from sidekick.body.expression import ExpressionCurve, parse_expression
from sidekick.body.sway import SpeechSway
from sidekick.config import ConfigSession
from sidekick.interaction import ExpressionMapper
from sidekick.interaction.attention import Attention
from sidekick.interaction.frontend import AudioFrontEnd
from sidekick.storage import StorageSession


def wait_for(predicate, timeout=3.0, step=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


# ------------------------------------------------------------------ library and curves


def test_library_is_ours_complete_and_returns_to_rest():
    library = load_library()
    kinds = {spec.kind for spec in library.values()}
    assert kinds == {"beat", "emotion", "performance", "state"}
    assert {"nod", "shake", "tilt", "look_up", "perk"} <= set(library)  # the gestures
    assert {"think", "think_long", "ack", "mm_hm", "yield", "emphasis", "laugh"} <= set(library)
    seen: dict[str, str] = {}
    for spec in library.values():
        for alias in spec.aliases:
            assert alias.lower() not in library, f"{alias} shadows an entry"
            assert seen.setdefault(alias.lower(), spec.name) == spec.name, f"{alias} twice"
        if spec.kind != "state":
            end = spec.values(spec.duration)
            assert all(abs(v) < 0.5 for v in end.values()), spec.name
            assert spec.duration <= {"beat": 2.0, "emotion": 3.0, "performance": 8.0}[spec.kind]
    assert library["think"].then == "think_long" and library["think_long"].loop_from == 0.0


def test_monotone_curve_never_overshoots_and_holds_flat():
    curve = ExpressionCurve.from_keys([(0, 0), (0.6, 12), (2.0, 12), (2.5, 0)])
    samples = [curve.value(t / 100) for t in range(0, 251)]
    assert max(samples) <= 12.0 + 1e-9 and min(samples) >= -1e-9
    assert all(abs(curve.value(t) - 12.0) < 1e-9 for t in (0.8, 1.2, 1.9))  # the hold is flat
    steps = [abs(b - a) for a, b in itertools.pairwise(samples)]
    assert max(steps) < 0.6  # no jump anywhere


def test_play_scales_mirrors_fades_and_loops():
    library = load_library()
    wink = library["wink"]
    peak = max(ExpressionPlay(wink, 0.0).sample(t / 100).get("ant_l", 0.0) for t in range(50))
    half = max(ExpressionPlay(wink, 0.0, 0.5).sample(t / 100).get("ant_l", 0.0) for t in range(50))
    assert math.isclose(half, peak / 2, rel_tol=1e-6)
    mirrored = ExpressionPlay(wink, 0.0, mirror=True).sample(0.12)
    plain = ExpressionPlay(wink, 0.0).sample(0.12)
    assert mirrored["ant_r"] == plain["ant_l"] and mirrored["roll"] == -plain["roll"]
    play = ExpressionPlay(library["delighted"], 0.0)
    play.cancel(1.0, 0.25)
    assert play.sample(1.0) and not play.sample(1.3) and play.finished(1.3)
    loop = ExpressionPlay(library["think_long"], 0.0)
    span = library["think_long"].duration
    before, after = loop.sample(span - 0.001), loop.sample(span + 0.001)
    assert all(abs(before[ch] - after[ch]) < 0.2 for ch in before)  # the seam does not jump
    assert not loop.finished(60.0)


def test_bad_entries_are_refused_with_their_name():
    for raw in (
        {"kind": "mood", "duration": 1, "keys": {}},
        {"kind": "beat", "duration": 1, "keys": {"pitch": [[0, 0], [0, 1]]}},
        {"kind": "beat", "duration": 1, "keys": {"nose": [[0, 0], [1, 0]]}},
    ):
        try:
            parse_expression("bad", raw)
        except ValueError as exc:
            assert "bad" in str(exc)
        else:  # pragma: no cover
            raise AssertionError(raw)


# ------------------------------------------------------------------ the motion owner


def test_layers_play_on_top_of_the_gaze_and_chain_states():
    session = BodySession(BodyNullBackend(), poll_hz=20.0)
    session.connect()
    try:
        assert session.motion is not None
        session.look(yaw=0.3, duration_s=0.1)
        assert wait_for(lambda: abs(session.motion.pose_snapshot.yaw - 0.3) < 0.02)
        assert session.express("happy")  # an alias
        assert wait_for(lambda: session.motion.pose_snapshot.emotion == "delighted", 1.0)
        assert wait_for(lambda: session.motion.pose_snapshot.pitch < -0.05, 1.0)  # chin up
        assert session.gaze_held()
        assert abs(session.motion.pose_snapshot.yaw - 0.3) < 0.05  # the gaze stays
        assert not session.express("no_such_thing")
        assert session.hold_state("think")
        assert wait_for(lambda: session.motion.state.layers.get("state") == "think_long", 4.0)
        session.end_state(0.2)
        assert wait_for(lambda: "state" not in session.motion.state.layers, 1.0)
        assert wait_for(lambda: abs(session.motion.pose_snapshot.yaw - 0.3) < 0.02, 2.0)
    finally:
        session.close()


def test_style_energy_scales_new_expressions_and_resets():
    session = BodySession(BodyNullBackend(), poll_hz=20.0)
    session.connect()
    try:
        assert session.motion is not None

        def peak(name: str) -> float:
            session.express(name)
            best = 0.0
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                best = max(best, session.motion.pose_snapshot.pitch)
                time.sleep(0.005)
            return best

        natural = peak("nod")
        session.set_style("lively")
        assert session.motion.energy == 1.45
        lively = peak("nod")
        session.set_style("calm")
        calm = peak("nod")
        assert lively > natural * 1.25 and calm < natural * 0.75
        session.set_style("bogus")
        assert session.style == "natural"
        session.set_expressiveness(0.5)
        assert session.motion.energy == 0.5
    finally:
        session.close()


def test_controller_hold_drops_agent_expressions_but_plays_manual_ones():
    session = BodySession(BodyNullBackend(), poll_hz=20.0)
    session.connect()
    try:
        assert session.motion is not None
        session.take_control("test")
        assert wait_for(lambda: session.motion.state.manual, 1.0)
        session.express("laugh")
        time.sleep(0.2)
        assert "express" not in session.motion.state.layers
        session.express("laugh", manual=True)
        assert wait_for(lambda: session.motion.state.layers.get("express") == "laugh", 1.0)
    finally:
        session.release_control()
        session.close()


def test_speech_sway_reports_phrase_onsets_at_their_playback_time():
    sway = SpeechSway()
    silence = np.zeros(1600, dtype=np.float32)
    voice = (0.3 * np.sin(np.arange(1600) * 2 * np.pi * 220 / 16000)).astype(np.float32)
    t = 100.0
    for chunk in (
        silence,
        silence,
        silence,
        silence,
        voice,
        voice,
        silence,
        silence,
        silence,
        silence,
        voice,
        voice,
        silence,
        voice,
    ):
        sway.feed(chunk, t)
        t += 0.1
    assert sway.take_onsets(99.0) == 0
    # after 0.4 s of quiet (twice), not after 0.1 s (the detector is still on)
    assert sway.take_onsets(200.0) == 2


# ------------------------------------------------------------------ agent tags, attention


def test_tags_split_style_and_expressions_and_aliases_resolve():
    split = ExpressionMapper.split_tags("[style:lively][express:laugh] 從前有隻貓，[express:開心]")
    assert split.text == "從前有隻貓，" and split.expressions == ("laugh", "開心")
    assert split.style == "lively"
    assert ExpressionMapper.split_tags("[style:shouty] 你好").style is None
    session = BodySession(BodyNullBackend())
    mapper = ExpressionMapper(session)
    assert mapper.resolve("Happy") == "delighted" and mapper.resolve("拜拜") == "wave"
    assert mapper.resolve("listening") == "listening" and mapper.resolve("cheerful1") is None
    assert mapper.resolve("delight") == "delighted" and mapper.resolve("Laughing") == "laugh"
    assert mapper.resolve("su") is None  # too short to guess


class _Body:
    """Records what attention asks of the body."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.held = False

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args[0] if args else kwargs.get("name")))
            return True

        return record

    def gaze_held(self) -> bool:
        return self.held

    def camera_fov(self):
        return None

    def current_look(self):
        from sidekick.body import LookTarget

        return LookTarget()

    def face(self):
        from sidekick.body import BodyFace

        return BodyFace(False)


def test_thinking_keeps_the_servo_and_ends_before_speech():
    body = _Body()
    attention = Attention(body)  # type: ignore[arg-type]
    attention.engaged = True
    attention.acknowledge()
    attention.thinking()
    assert ("beat", "ack") in body.calls and ("hold_state", "think") in body.calls
    from sidekick.body import BodyFace

    face = BodyFace(True, x=0.4, y=0.0, ts=time.time())
    assert attention.on_face(face) is True  # thinking keeps the eyes on the person (block #80)
    attention.speaking(True)
    assert ("end_state", 0.35) in body.calls and not attention.thinking_now
    attention.speaking(False)
    assert ("beat", "yield") in body.calls
    body.calls.clear()
    attention.speaking(False)  # a second "not speaking" without speech: no second yield
    assert ("beat", "yield") not in body.calls
    attention.thinking()
    attention.heard_again()
    assert ("listening", None) in body.calls and not attention.thinking_now
    body.held = True
    assert attention.on_face(face) is False  # an expression moved the camera


def test_backchannel_nods_only_while_they_talk_and_not_too_often():
    body = _Body()
    attention = Attention(body)  # type: ignore[arg-type]
    attention.rng.seed(1)
    assert attention.backchannel(10.0) is False  # not engaged
    attention.engaged = True
    results = [attention.backchannel(10.0 + i) for i in range(0, 40, 1)]
    assert sum(results) >= 4 and attention.backchannels == sum(results)
    times = [10.0 + i for i, r in enumerate(results) if r]
    assert all(b - a >= 3.5 for a, b in itertools.pairwise(times))
    attention.speaking(True)
    assert attention.backchannel(100.0) is False  # never while Bobby speaks


def test_front_end_reports_a_pause_inside_a_sentence():
    class _VAD:
        sample_rate = 16000

    events = []
    front = AudioFrontEnd.__new__(AudioFrontEnd)
    front.vad = _VAD()
    front.emit = events.append
    front.pauses = 0
    front._peak_db, front._quiet_since, front._pause_sent = -100.0, None, False
    loud = (0.3 * np.ones(320)).astype(np.float32)
    quiet = (0.003 * np.ones(320)).astype(np.float32)
    front.speech_onset = 0.0
    t = 0.0
    for _ in range(100):  # 2 s of speech
        front._track_pause(loud, t, True)
        t += 0.02
    for _ in range(20):  # 0.4 s dip, the detector still in speech
        front._track_pause(quiet, t, True)
        t += 0.02
    assert [e.kind for e in events] == ["pause"] and front.pauses == 1


def test_retired_emotion_keys_are_dropped_on_load(tmp_path):
    storage = StorageSession(tmp_path)
    config = ConfigSession(storage)
    path = storage.layout.config_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"body": {"emotion_sound": True, "emotions_dataset": "x/y", "volume": 70}})
    )
    spec = config.load()
    assert spec is not None and spec.body.volume == 70 and spec.body.expressiveness == 1.0


def test_pipeline_style_lasts_one_reply():
    from sidekick.interaction.pipeline import TurnPipeline, TurnTiming

    class _Body:
        def __init__(self) -> None:
            self.styles: list[str] = []

        def set_style(self, style: str) -> None:
            self.styles.append(style)

    body = _Body()
    pipeline = TurnPipeline.__new__(TurnPipeline)
    pipeline.body = body
    pipeline.expressions = type("M", (), {"express": lambda self, name: True})()
    pipeline.current_text = ""

    async def go() -> None:
        async def send(text: str) -> bool:
            return True

        pipeline.keeper = type("K", (), {"send": staticmethod(send)})()
        await pipeline._say_fragment("[style:lively] 從前", [], [], TurnTiming(), None)

    asyncio.run(go())
    assert body.styles == ["lively"]
