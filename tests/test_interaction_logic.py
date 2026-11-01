"""Pure-logic parts of interaction: name spotting, engagement machine, barge-in, sentence splitter."""

from __future__ import annotations

import math

from sidekick.config import ConfigInteraction, ConfigRobot
from sidekick.interaction import (
    BargeInController,
    EngagementMachine,
    InteractionState,
    NameSpotter,
    SentenceSplitter,
)


def spotter():
    robot = ConfigRobot()
    return NameSpotter(robot.name, robot.aliases, 0.8)


def test_name_spotting_across_languages():
    s = spotter()
    assert s.match("BOBBY").hit
    m = s.match("Bobby，今日天氣點呀")
    assert m.hit and m.alias == "bobby" and m.remainder == "今日天氣點呀"
    m = s.match("波比呀，幫我開燈")
    assert m.hit and m.remainder == "幫我開燈"
    assert s.match("Bobby，今日天氣點呀？").remainder == "今日天氣點呀？"
    assert s.match("今日天氣點呀 Bobby").remainder == "今日天氣點呀"
    assert s.match("BOBY 今日天气点呀").remainder == "今日天气点呀"
    assert s.match("boby").hit and s.match("Bobbie，你好").remainder == "你好"
    assert s.match("BO比I 可唔可以講故事").remainder == "可唔可以講故事"
    assert s.match("BOB 比可唔可以講故事").remainder == "可唔可以講故事"
    assert s.match("Bobby 比較好").remainder == "比較好"
    assert s.match("宝比你好").hit
    assert s.match("hey bob, what time is it").hit
    assert not s.match("今日天氣好好").hit
    assert not s.match("the baby is sleeping").hit
    assert s.match("").hit is False
    assert s.without_name("今日天氣好好") == "今日天氣好好"


def test_engagement_wake_name_touch_timeout_and_closing():
    cfg = ConfigInteraction(session_timeout_s=8.0)
    m = EngagementMachine(cfg, awake=True)
    s = spotter()
    assert m.state == InteractionState.IDLE
    # plain speech in IDLE is rejected and stays local
    d = m.on_segment(10.0, 1.0, 0.1, s.match("今日天氣好好"), None, "今日天氣好好")
    assert not d.accept and d.reason == "no wake name" and m.state == InteractionState.IDLE
    # wake name opens a session and strips the name
    d = m.on_segment(11.0, 1.5, 0.1, s.match("Bobby 今日天氣點呀"), None, "Bobby 今日天氣點呀")
    assert d.accept and d.trigger == "wake_name" and d.text == "今日天氣點呀"
    assert m.state == InteractionState.ENGAGED and m.session is not None
    # follow-up from the same direction needs no name; other direction is rejected
    assert m.on_segment(12.0, 1.0, 0.2, s.match("咁明日呢"), None, "咁明日呢").accept
    assert (
        m.on_segment(12.5, 1.0, 0.2 + 1.2, s.match("我哋食飯啦"), None, "我哋食飯啦").reason
        == "other direction"
    )
    # robot speaks then quiet; silence timeout ends the session
    m.on_robot_speaking(True, 13.0)
    assert m.state == InteractionState.SPEAKING
    assert m.on_tick(30.0) is None  # no timeout while speaking
    m.on_robot_speaking(False, 15.0)
    assert m.on_tick(22.0) is None
    end = m.on_tick(23.1)
    assert end is not None and end.end_session and m.state == InteractionState.IDLE
    # touch opens a session for a guest; closing phrase ends it after the turn
    d = m.on_touch(40.0)
    assert d.accept and m.session is not None and m.session.addressee.startswith("guest:")
    assert m.on_turn_done(41.0, "好呀多謝", False) is not None and m.state == InteractionState.IDLE
    # two NO_REPLY in a row end the session
    m.on_touch(50.0)
    assert m.on_turn_done(51.0, "blah", True) is None
    assert m.on_turn_done(52.0, "blah", True).end_session
    # TV sector: speech from that direction never triggers without the name
    tv = EngagementMachine(ConfigInteraction(tv_sector=[-0.8]), awake=True)
    assert (
        tv.on_segment(1.0, 1.0, -0.8, s.match("有人講嘢"), None, "有人講嘢").reason == "tv sector"
    )
    assert tv.on_segment(2.0, 1.0, -0.8, s.match("Bobby"), None, "Bobby").accept
    # asleep: nothing happens
    tv.set_awake(False, 3.0)
    assert tv.state == InteractionState.SLEEPING and not tv.on_touch(4.0).accept
    tv.set_awake(True, 5.0)
    assert tv.state == InteractionState.IDLE


def test_engagement_session_speaker_follows_the_voice_not_the_wake_clip():
    """Block #80: the short "Bobby" has no identity; unnamed ids defer to the direction."""
    m = EngagementMachine(ConfigInteraction(), awake=True)
    s = spotter()
    d = m.on_segment(10.0, 0.8, 0.0, s.match("Bobby"), None, "Bobby")
    assert d.accept and m.session is not None and m.session.speaker is None
    assert m.on_segment(12.0, 2.4, 0.05, None, "person:25", "今日天氣點呀").accept
    assert m.session.speaker == "person:25"
    # another unnamed id from the same direction is the same person, more likely than not
    assert m.on_segment(14.0, 3.2, 0.1, None, "person:26", "都可以呀").accept
    assert m.session.speaker == "person:25"
    # the voice is recognised: the session's speaker becomes the contact
    assert m.on_segment(16.0, 3.9, 0.0, None, "发瘟鸡", "我叫發瘟雞").accept
    assert m.session.speaker == "发瘟鸡" and m.session.addressee == "发瘟鸡"
    # an unnamed id or no identity later on: the direction decides, the contact stays
    assert m.on_segment(18.0, 1.5, 0.05, None, "person:27", "你認唔認得我").accept
    assert m.on_segment(19.0, 1.5, None, None, None, "好呀").accept
    assert m.session.speaker == "发瘟鸡"
    assert m.on_segment(20.0, 1.5, 0.05 + 1.2, None, None, "我哋食飯啦").reason == "other direction"
    # two known voices that disagree are two people
    assert m.on_segment(21.0, 2.0, 0.0, None, "阿明", "食咗飯未").reason == "other speaker"


def test_barge_in_two_stages():
    cfg = ConfigInteraction()
    b = BargeInController(
        spotter(), cfg.stop_words, cfg.backchannels, cfg.duck_db, cfg.hard_stop_speech_s
    )
    assert b.on_speech_start(0.0, qualifying=False).action == "ignore"
    assert b.on_speech_start(0.0, qualifying=True).action == "duck" and b.ducked
    assert b.on_speech_ongoing(0.3, 0.3).action == "ignore"
    # short backchannel resumes
    assert b.on_speech_end(0.4, 0.4, "嗯").action == "resume" and not b.ducked
    # sustained speech stops
    b.on_speech_start(1.0, True)
    assert b.on_speech_ongoing(1.8, 0.8).action == "ignore"
    assert b.on_speech_ongoing(2.0, 1.0).action == "stop" and b.stopped
    # stop word stops even when short
    b.reset()
    b.on_speech_start(2.0, True)
    assert b.on_speech_end(2.3, 0.3, "停").action == "stop"
    b.reset()
    b.on_speech_start(3.0, True)
    assert b.on_speech_end(3.3, 0.3, "Bobby").action == "stop"
    b.reset()
    assert b.on_touch().action == "stop"
    assert b.is_backchannel("好") and b.is_backchannel("ok") and not b.is_backchannel("等一下先")
    assert b.is_stop_word("等陣") and b.is_stop_word("stop")


def test_sentence_splitter_fragments():
    sp = SentenceSplitter(soft_min_chars=6, hard_max_chars=20)
    out = []
    for delta in ["今日", "天氣好好。", "我哋一齊去公園，", "好唔好呀？"]:
        out += sp.feed(delta)
    out += [sp.flush()] if sp.flush() else []
    assert out[0] == "今日天氣好好。"
    assert out[1] == "我哋一齊去公園，"
    assert out[2] == "好唔好呀？"
    sp = SentenceSplitter()
    assert sp.feed("今日係晴天，早晨有啲涼，") == ["今日係晴天，", "早晨有啲涼，"]
    sp = SentenceSplitter()
    assert sp.feed("唔好意思，[express:") == []  # tag still open: no cut inside it
    assert sp.feed(" sad] 我睇唔到。") == ["唔好意思，[express: sad] 我睇唔到。"]
    sp = SentenceSplitter(soft_min_chars=6, hard_max_chars=10)
    assert sp.feed("abcdefghijklmnop") == ["abcdefghij"]
    assert sp.flush() == "klmnop"
    # runs of sentence ends stay together; an ellipsis and an English full stop end a sentence
    sp = SentenceSplitter()
    assert sp.feed("咩話？！真係？") == ["咩話？！", "真係？"]
    assert sp.feed("咩意思呀……你係問我") == ["咩意思呀……"]
    sp = SentenceSplitter()
    assert sp.feed("Sure. It is 3.5 degrees") == ["Sure."]
    sp = SentenceSplitter()
    assert sp.feed("第一句\n第二句") == ["第一句\n"]  # a newline still marks the end


def test_sentence_final_fragments():
    """Which fragments end a sentence, so the pipeline flushes them (block #76)."""
    from sidekick.interaction.pipeline import SENTENCE_FINAL

    for text in ["好，等我睇下。", "真係？！", "咩意思呀……", "佢話「好。」", "Sure.", "第一句\n"]:
        assert SENTENCE_FINAL.search(text), text
    for text in ["冇問題呀，", "今日天氣", "Sure,"]:
        assert not SENTENCE_FINAL.search(text), text
    assert math.isclose(1.0, 1.0)
