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
    assert s.match("BANANA").hit
    m = s.match("Banana，今天天气怎么样")
    assert m.hit and m.alias == "banana" and m.remainder == "今天天气怎么样"
    m = s.match("巴娜娜呀，帮我开灯")
    assert m.hit and m.remainder == "帮我开灯"
    assert s.match("Banana，今天天气怎么样？").remainder == "今天天气怎么样？"
    assert s.match("今天天气怎么样 Banana").remainder == "今天天气怎么样"
    # the spellings SenseVoice really wrote (block #94) are aliases, matched as written
    assert s.match("BANANNA 今天天气怎么样").remainder == "今天天气怎么样"
    assert s.match("ANANNA 今天天气怎么样").remainder == "今天天气怎么样"
    assert s.match("banaa").hit and s.match("BNAA").hit
    assert s.match("你好 PAANANNA").remainder == "你好"
    assert s.match("Banana 比较好").remainder == "比较好"
    assert s.match("hey banana, what time is it").hit
    assert not s.match("今天天气很好").hit
    assert not s.match("我想吃香蕉").hit  # the fruit in Chinese is not the name
    assert not s.match("the baby is sleeping").hit
    assert s.match("").hit is False
    assert s.without_name("今天天气很好") == "今天天气很好"


def test_only_the_name_itself_is_matched_loosely_and_word_by_word():
    """Block #94: with every alias matched loosely, "ananna" took "NANNA is not coming" and
    "banaa" took "Panama", "cabana" and "nana"; 「把娜娜」 would have taken 「娜娜」; and windows
    sliding over the text without its spaces found a "banana" in "a banner and a"."""
    s = spotter()
    m = s.match("VANANA what's the weather today")  # a spelling nobody has seen: the name, loosely
    assert m.hit and m.alias == "banana" and 0.8 <= m.score < 1.0
    assert m.remainder == "what's the weather today"  # the word goes, the spaces stay
    assert s.match("你好 VANANA").remainder == "你好"
    assert s.match("VANANA，今天天气怎么样？").remainder == "今天天气怎么样？"
    assert s.match("我想跟 VANANA 说句话").remainder == "我想跟 Banana 说句话"  # inside: renamed
    assert s.match("BAANA 给我讲个故事吧").remainder == "给我讲个故事吧"
    for text in (
        "NANNA IS NOT COMING TODAY",
        "NANA",
        "THE PANAMA CANAL IS LONG",
        "WE STAYED IN A CABANA NEAR HAVANA",
        "HANNAH AND SUSANNA ORDERED A PIANO FROM VIENNA",
        "THE CANTINA SENT A BANNER AND A BANDAGE",
        "HER UNCLE MOVED FROM MONTANA TO INDIANA",
        "娜娜今天不来了",
        "把那个拿来",
        "巴拿马运河很长",
        "爸爸那天拿了一个苹果",
        "BB",  # the first name's trap (block #89): a parent calling a child
        "BONAA",  # too far from the name, and not an alias
    ):
        assert not s.match(text).hit, text
    # a short name is never matched loosely: two of three letters score 0.8
    short = NameSpotter("Bob", ["bob"], 0.8)
    assert short.match("bob 你好").hit and not short.match("听到啦 BB").hit
    assert not short.match("about the robot").hit


def test_engagement_wake_name_touch_timeout_and_closing():
    cfg = ConfigInteraction(session_timeout_s=8.0)
    m = EngagementMachine(cfg, awake=True)
    s = spotter()
    assert m.state == InteractionState.IDLE
    # plain speech in IDLE is rejected and stays local
    d = m.on_segment(10.0, 1.0, 0.1, s.match("今日天氣好好"), None, "今日天氣好好")
    assert not d.accept and d.reason == "no wake name" and m.state == InteractionState.IDLE
    # wake name opens a session and strips the name
    d = m.on_segment(11.0, 1.5, 0.1, s.match("Banana 今日天氣點呀"), None, "Banana 今日天氣點呀")
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
    assert tv.on_segment(2.0, 1.0, -0.8, s.match("Banana"), None, "Banana").accept
    # asleep: nothing happens
    tv.set_awake(False, 3.0)
    assert tv.state == InteractionState.SLEEPING and not tv.on_touch(4.0).accept
    tv.set_awake(True, 5.0)
    assert tv.state == InteractionState.IDLE


def test_engagement_session_speaker_follows_the_voice_not_the_wake_clip():
    """Block #80: a short call of the name has no identity; unnamed ids defer to the direction."""
    m = EngagementMachine(ConfigInteraction(), awake=True)
    s = spotter()
    d = m.on_segment(10.0, 0.8, 0.0, s.match("Banana"), None, "Banana")
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
    assert b.on_speech_end(3.3, 0.3, "Banana").action == "stop"
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
