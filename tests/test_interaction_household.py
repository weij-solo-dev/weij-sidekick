"""Block #89: what the family's session of 10-31 taught — the name, stories, emoji.

The robot was "Bobby" then; the lessons about the name are kept on the new one (block #94).
"""

from __future__ import annotations

import itertools
import time

from sidekick.config import ConfigInteraction, ConfigRobot
from sidekick.interaction import EngagementMachine, InteractionState, NameSpotter
from sidekick.interaction.engagement import asks
from sidekick.interaction.pipeline import TurnPipeline, speakable


def spotter() -> NameSpotter:
    robot = ConfigRobot()
    return NameSpotter(robot.name, robot.aliases, 0.8)


def test_every_name_at_the_edges_goes_and_one_inside_is_renamed():
    s = spotter()
    assert s.match("BANANNA BANANA").remainder == ""  # only the name, twice
    assert s.match("BANAA BANANNA 把娜娜").remainder == ""
    assert s.match("BANANA BANANNA BANANA BANANNA BANANA").remainder == ""
    assert s.match("机器人 BANANA BANANNA BANANA").remainder == "机器人"
    assert s.match("啊 BANANA 你可不可以放首歌给我听").remainder == "你可不可以放首歌给我听"
    assert s.match("我跟Banana讲了").remainder == "我跟Banana讲了"
    assert s.match("讲个把娜娜的故事").remainder == "讲个Banana的故事"
    assert (
        s.match("BANANNA 你为什么不认人 BANANAS 你为什么不认人").remainder
        == "你为什么不认人 Banana 你为什么不认人"
    )
    assert (
        s.match("今天天气怎么样 Banana？").remainder == "今天天气怎么样？"
    )  # the question mark stays
    assert s.without_name("今天天气很好") == "今天天气很好"


def test_a_reply_that_asks_waits_longer_for_the_answer():
    assert asks("你估下，跟住呢個係邊個嚟㗎？")
    assert asks("係咪叫我呀？咁夜咗，仲有咩事？[express:curious]")
    assert asks("What do you think?")
    assert not asks("故事講完啦。") and not asks("")
    m = EngagementMachine(ConfigInteraction(session_timeout_s=8.0, answer_timeout_s=15.0))
    m.begin_session("wake_name", 0.0, speaker="思源")
    m.on_robot_speaking(True, 1.0)
    m.on_robot_speaking(False, 50.0)  # a 49 s story
    m.on_turn_done(50.0, "講故事", False, reply="你估下，跟住呢個係邊個嚟㗎？")
    assert m.on_tick(59.0) is None  # 8 s would have closed it: 「唔知」 came at +3–5 s
    assert m.on_segment(54.0, 1.0, 0.0, None, "思源", "唔知").accept
    m.on_turn_done(80.0, "唔知", False, reply="咁我話你聽：係海龜。")
    assert m.on_tick(87.0) is None
    end = m.on_tick(88.1)  # no question: the usual 8 s
    assert end is not None and end.end_session and m.state == InteractionState.IDLE


def test_a_sentence_begun_in_time_holds_the_session():
    """Block #92: 13 sessions closed under people mid-sentence. 10-31 14:08: 思源 began 2.3 s
    after 「做咩？咁叫我。」 and talked for 7.8 s; the 8 s timer closed the session 5.7 s in."""
    m = EngagementMachine(ConfigInteraction(session_timeout_s=8.0))
    m.begin_session("wake_name", 0.0, speaker="思源")
    m.on_robot_speaking(True, 1.0)
    m.on_robot_speaking(False, 3.0)
    m.on_turn_done(3.0, "Banana", False, reply="做咩？咁叫我。")
    assert not m.session.asked  # no question mark at the end
    assert m.on_tick(11.5, speech_onset=5.3) is None  # the deadline (11.0) passed mid-sentence
    assert m.on_segment(13.1, 7.8, 0.0, None, "思源", "睇唔睇到个胶都系靓噶").accept
    # speech that begins after the silence ran out does not hold it
    end = m.on_tick(21.6, speech_onset=21.4)
    assert end is not None and end.end_session and m.state == InteractionState.IDLE


def test_call_answers_vary_and_wait_for_their_clips():
    import asyncio
    import random

    from sidekick.audio import AudioClip
    from sidekick.interaction.call import CALL_ANSWERS, CallAnswers

    calls = CallAnswers(random.Random(1))
    text, clip = calls.pick("yue")
    assert text in CALL_ANSWERS["yue"] and clip is None  # not synthesized: said via the stream
    picks = [calls.pick("yue")[0] for _ in range(20)]
    assert all(a != b for a, b in itertools.pairwise(picks))  # never twice in a row
    assert calls.pick("fr")[0] in CALL_ANSWERS["yue"]  # no phrases: the household's

    async def synthesize(text: str) -> AudioClip | None:
        if text.startswith("I"):
            raise RuntimeError("tts down")
        return AudioClip.silence(0.6)

    ready = asyncio.run(calls.prepare(synthesize, ["yue", "en", "yue"]))
    assert ready == len(CALL_ANSWERS["yue"]) + 2  # every English one but "I'm listening."
    assert calls.pick("yue")[1] is not None


def test_a_name_hit_adopts_the_voice_on_it():
    """10-31 22:52:33: a call of the name was credited to `guest:12`, because the keyword
    stream had opened the session without a speaker."""
    s = spotter()
    m = EngagementMachine(ConfigInteraction())
    assert m.on_keyword(10.0, 0.0).accept
    assert m.session is not None and m.session.speaker is None
    assert m.session.addressee.startswith("guest:")
    d = m.on_segment(11.0, 6.2, 0.0, s.match("BANANNA BANANA"), "黎思源", "BANANNA BANANA")
    assert d.accept and d.reason == "wake name in session"
    assert m.session.speaker == "黎思源" and m.session.addressee == "黎思源"


def test_emoji_are_never_spoken():
    assert (
        speakable("我屋企冇呢個人喎 😂 係咪想我講個故事？") == "我屋企冇呢個人喎 係咪想我講個故事？"
    )
    assert speakable("好呀👍") == "好呀" and speakable("👍") == ""
    assert speakable("普通句子，冇emoji。") == "普通句子，冇emoji。"
    from sidekick.agent.agent import _SpeakerIdScrubber

    assert _SpeakerIdScrubber("yue", spoken=True).feed("好笑😂！") == "好笑！"
    assert _SpeakerIdScrubber("yue").feed("好笑😂！") == "好笑😂！"  # a chat keeps them


class _Speaker:
    """A speaker with `left` seconds of audio queued; waiting plays it off without real time."""

    def __init__(self, left: float) -> None:
        self.left = left
        self.waits: list[float] = []

    def speaking_remaining_s(self) -> float:
        return self.left

    def wait_quiet(self, timeout: float | None = None) -> bool:
        assert timeout is not None
        self.waits.append(timeout)
        self.left = max(0.0, self.left - timeout)
        return self.left == 0.0


def test_a_turn_lasts_until_the_speaker_is_quiet():
    """A 50 s story: the 30 s cap ended the turn 20 s early and the session timed out under it."""
    pipeline = TurnPipeline.__new__(TurnPipeline)
    pipeline.body = _Speaker(50.0)  # type: ignore[assignment]
    started = time.monotonic()
    assert pipeline._wait_spoken(318)
    assert pipeline.body.waits[0] >= 50.0  # one wait for everything queued, not 30 s
    assert time.monotonic() - started < 1.0
    stuck = TurnPipeline.__new__(TurnPipeline)

    class Stuck(_Speaker):
        def wait_quiet(self, timeout: float | None = None) -> bool:
            time.sleep(min(timeout or 0.0, 0.01))
            return False

    stuck.body = Stuck(0.0)  # type: ignore[assignment]
    import sidekick.interaction.pipeline as pipeline_module

    saved = pipeline_module.time.monotonic
    clock = [time.monotonic()]

    def fake_monotonic() -> float:
        clock[0] += 5.0
        return clock[0]

    pipeline_module.time.monotonic = fake_monotonic  # type: ignore[assignment]
    try:
        assert not stuck._wait_spoken(10)  # a player that never drains is given up on
    finally:
        pipeline_module.time.monotonic = saved  # type: ignore[assignment]
