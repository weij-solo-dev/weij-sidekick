"""AgentSession with a scripted LLM: tools, confirm gating, delegation and delivery."""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from sidekick.agent import AgentSession
from sidekick.channel import ChannelMessage, ChannelSession
from sidekick.config import ConfigAgents, ConfigSubagent
from sidekick.llm import LLMResult, LLMSession, LLMStreamEvent, LLMToolCall

NOTE = re.compile(r"^\[Context:[^\]]*\]\n(?:\[[^\n]*\]\n)?")


class ScriptedLLM:
    """Backend whose replies are chosen by matching the latest message text / tool results."""

    def __init__(self, slot):
        self.slot = slot
        self.calls = []

    def plan(self, messages, options):
        """Return ("text", str) or ("tools", [(name, args)]) based on the conversation."""
        last = messages[-1]
        # the turn's message is led by its context note (block #71): read what was said
        user_texts = [NOTE.sub("", m.content) for m in messages if m.role == "user" and m.content]
        notes = " ".join(m.content for m in messages if m.role == "user" and m.content)
        tool_names = {t.name for t in options.tools}
        if last.role == "tool":
            return ("text", f"搞掂：{last.content[:40]}")
        text = user_texts[-1] if user_texts else ""
        if self.slot == "smart":
            return ("text", f"[helper] 完成任務：{text[-20:]}")
        if "記住" in text and "remember" in tool_names:
            return ("tools", [("remember", {"text": text.replace("記住", "").strip()})])
        if "睇下" in text and "slow_look" in tool_names:
            return ("tools", [("slow_look", {})])
        if "直接刪除" in text and "skill_delete" in tool_names:
            # a model that writes the confirmation itself (block #94)
            return ("tools", [("skill_delete", {"name": "quiet", "confirmed": True})])
        if "刪除" in text and "skill_delete" in tool_names:
            return ("tools", [("skill_delete", {"name": "quiet"})])
        if "提我" in text and "schedule" in tool_names:
            return ("tools", [("schedule", {"prompt": "提你食藥", "when": "2020-01-01T08:00"})])
        if "幫我查" in text and "delegate" in tool_names:
            mode = "async" if "慢慢" in text else "sync"
            return ("tools", [("delegate", {"agent": "helper", "task": "查天氣", "mode": mode})])
        if "電視" in text:
            return ("text", "NO_REPLY")
        if "我係邊個" in text:
            return ("text", "你係 person:6，我仲未知你個名。")
        if "confirmed the pending action" in notes:
            return ("text", "已經刪除咗。")
        if "Subagent" in text:
            return ("text", "helper 搞掂咗，天氣好好。")
        if "Heartbeat" in text:
            return ("text", "NO_REPLY")
        if "[internal]" in text or "scheduled task" in text or "[event" in text:
            return ("text", "提你食藥啦！")
        if "敏感" in text:
            return ("refuse", None)
        return ("text", f"收到：{text[-12:]}")

    async def stream(self, messages, options):
        self.calls.append([m.content for m in messages])
        kind, payload = self.plan(messages, options)
        if kind == "refuse":
            yield LLMStreamEvent(
                "done",
                result=LLMResult(
                    False,
                    None,
                    "fake",
                    "fake",
                    "m",
                    "****",
                    status_code=422,
                    api_code=1026,
                    error_message="input new_sensitive (1026)",
                ),
            )
            return
        if kind == "text":
            for i in range(0, len(payload), 4):
                yield LLMStreamEvent("text", payload[i : i + 4])
            yield LLMStreamEvent(
                "done",
                result=LLMResult(True, payload, "fake", "fake", "m", "****", finish_reason="stop"),
            )
            return
        calls = tuple(
            LLMToolCall(f"call{i}", name, json.dumps(args, ensure_ascii=False))
            for i, (name, args) in enumerate(payload)
        )
        for call in calls:
            yield LLMStreamEvent("tool_call", tool_call=call)
        yield LLMStreamEvent(
            "done",
            result=LLMResult(
                True,
                None,
                "fake",
                "fake",
                "m",
                "****",
                tool_calls=calls,
                finish_reason="tool_calls",
            ),
        )

    async def infer(self, messages, options):  # pragma: no cover - not used
        raise NotImplementedError


class FakeVoice:
    def __init__(self):
        self.spoken = []

    async def say(self, text, expression=None):
        self.spoken.append(text)


class RecordingAdapter:
    name = "telegram"
    capabilities = None

    def __init__(self):
        self.sent = []

    async def start(self, handler):
        pass

    async def stop(self):
        pass

    async def send(self, reply):
        self.sent.append(reply)
        return True


@pytest.fixture
def session(tmp_path):
    llm = LLMSession()
    fast, smart = ScriptedLLM("fast"), ScriptedLLM("smart")
    llm.setup("fast", fast)
    llm.setup("smart", smart)
    voice = FakeVoice()
    agents = ConfigAgents(
        subagents={"helper": ConfigSubagent(role="You help.", description="looks things up")}
    )
    s = AgentSession(llm)
    s.setup(
        home=tmp_path,
        agents=agents,
        default_language="yue",
        say=voice.say,
        can_speak=lambda: True,
    )
    channels = ChannelSession()
    ChannelSession.shared = channels
    tg = RecordingAdapter()
    channels.register(tg)
    return s, fast, smart, voice, tg


async def collect(session, text, speaker="dad", channel="voice"):
    out = []
    async for delta in session.respond(ChannelMessage(channel, speaker, text, language="yue")):
        out.append(delta)
    return "".join(out)


async def test_plain_turn_records_timeline_and_no_reply(session, tmp_path):
    s, _fast, *_ = session
    s.llm.configure_trace(tmp_path / "llm_trace_v1.db")
    text = await collect(s, "你好呀")
    assert text == "收到：你好呀"
    rows = s.dialogue.recent(5)
    assert [r.role for r in rows] == ["assistant", "user"]
    assert await collect(s, "電視講乜嘢") == ""  # NO_REPLY yields nothing
    assert s.dialogue.recent(1)[0].role == "user"  # no assistant row for NO_REPLY
    assert [r["answer"] for r in s.llm._trace.recent()] == ["NO_REPLY", "收到：你好呀"]  # traced
    assert "main" in s.snapshot()["agents"] and "helper" in s.snapshot()["agents"]


async def test_context_view_leaves_performance_tags_out(session):
    s, fast, *_ = session
    from sidekick.agent import DialogueMessage

    s.dialogue.append(
        DialogueMessage(
            "voice",
            "main",
            "assistant",
            "[style:lively][express:laugh] 哈哈！",
            conversation=s.dialogue.conversation_for("voice"),
        )
    )
    await collect(s, "你好呀")
    history = [m for m in fast.calls[-1] if m and "哈哈" in m]
    assert history == ["哈哈！"]


async def test_unnamed_speaker_labels_never_reach_the_reply(session):
    s, fast, *_ = session
    text = await collect(s, "我係邊個", speaker="person:6")
    assert text == "你係呢位朋友，我仲未知你個名。"  # the label arrived cut across chunks
    assert s.dialogue.recent(1)[0].content == text
    assert "never say or write" in fast.calls[-1][0].lower()


async def test_tool_call_remember_then_reply(session):
    s, *_ = session
    text = await collect(s, "記住我鍾意飲奶茶")
    assert text.startswith("搞掂")  # a quick tool earns no acknowledgement (block #76)
    assert s.memory.recall(["dad"])[0].text == "我鍾意飲奶茶"
    rows = s.dialogue.recent(5)
    assert any(
        r.role == "tool" and r.visibility == "internal" and r.meta["tool"] == "remember"
        for r in rows
    )
    assert any(r.role == "assistant" and r.meta.get("tools") for r in rows)
    assert len({r.conversation for r in rows}) == 1  # one conversation: the room
    # the same conversation sees the call in its context; the block is frozen for it
    await collect(s, "你知道咩")
    call = s.llm.backend("fast").calls[-1]
    assert "鍾意飲奶茶" not in (call[0] or "") and any("鍾意飲奶茶" in (m or "") for m in call[1:])
    # a new conversation (dad on Telegram) gets the fact in its memory block
    await collect(s, "你記得我咩", channel="telegram")
    assert "我鍾意飲奶茶" in (s.llm.backend("fast").calls[-1][0] or "")


async def test_memory_tools_follow_identity(session, tmp_path):
    """Unnamed speakers keep no facts, forget stays in scope, `owner` moves to the owner (#63)."""
    s, *_ = session
    tools = {t.name: t for t in s.registry.all()}
    from sidekick.agent import ToolContext

    def ctx(speaker):
        return ToolContext(ChannelMessage("voice", speaker, "x"), "main")

    refused = await tools["remember"].handler({"text": "我叫阿明"}, ctx("person:7"))
    assert not refused.ok and "befriend" in refused.content and s.memory.count() == 0
    shared = await tools["remember"].handler(
        {"text": "屋企有隻貓", "scope": "household"}, ctx("person:7")
    )
    assert shared.ok and s.memory.recall(["household"])[0].text == "屋企有隻貓"
    s.memory.remember("dad", "鍾意飲奶茶")
    gone = await tools["forget"].handler({"text": "奶茶"}, ctx("mum"))
    assert "forgot 0" in gone.content and s.memory.recall(["dad"])  # never another person's
    gone = await tools["forget"].handler({"text": "貓"}, ctx("mum"))
    assert "forgot 1" in gone.content  # their own first, then the household's
    # contacts: a person befriended in this turn, and the dashboard's `owner`
    from sidekick.contact import ContactSession, ContactStore

    class Contacts(ContactSession):
        ready = True  # type: ignore[assignment]

    contacts = Contacts()
    contacts.store = ContactStore(tmp_path / "contact_v1.db")
    s.contacts = contacts
    contacts.store.create_person("person:3")
    ming = contacts.promote_person("person:3", "阿明")
    stored = await tools["remember"].handler({"text": "鍾意行山"}, ctx("person:3"))
    assert stored.ok and s.memory.recall([ming.id])[0].text == "鍾意行山"
    s.memory.remember("owner", "主人鍾意飲奶茶")
    message = s.resolve_message(ChannelMessage("dashboard", "owner", "hi"))
    assert message.speaker == "owner" and s.memory.recall(["owner"])  # no owner contact yet
    wei = contacts.create("Wei", is_owner=True)
    message = s.resolve_message(ChannelMessage("dashboard", "owner", "hi"))
    assert message.speaker == wei.id and s.memory.recall(["owner"]) == []
    assert s.memory.recall([wei.id])[0].text == "主人鍾意飲奶茶"


async def test_confirm_gate_blocks_then_executes_on_yes(session):
    s, _fast, *_ = session
    from sidekick.agent import Skill

    s.skills.upsert(Skill("quiet", "q", "body"))
    text = await collect(s, "刪除 quiet 技能")
    assert "搞掂" in text and s.skills.get("quiet") is not None  # not executed yet
    assert s.gate.pending("voice:dad") is not None
    text = await collect(s, "好呀")
    assert s.skills.get("quiet") is None and "刪除" in text
    assert s.gate.pending("voice:dad") is None
    s.skills.upsert(Skill("quiet", "q", "body"))
    await collect(s, "刪除 quiet 技能")
    await collect(s, "唔好")
    assert s.skills.get("quiet") is not None and s.gate.pending("voice:dad") is None


async def test_confirm_gate_takes_no_confirmation_from_the_model(session):
    s, *_ = session
    from sidekick.agent import Skill

    s.skills.upsert(Skill("quiet", "q", "body"))
    await collect(s, "直接刪除 quiet 技能")  # the model calls it with `confirmed: true`
    assert s.skills.get("quiet") is not None  # still parked: only the speaker confirms
    assert s.gate.pending("voice:dad") is not None
    await collect(s, "好呀")
    assert s.skills.get("quiet") is None


async def test_delegate_sync_and_async(session):
    s, _fast, smart, voice, _ = session
    text = await collect(s, "幫我查天氣")
    assert "helper" in text or "完成任務" in text
    assert smart.calls and any("Task from the main agent" in (c[-1] or "") for c in smart.calls)
    assert any(r.role == "internal" and "helper result" in r.content for r in s.dialogue.recent(10))
    before = len(voice.spoken)
    text = await collect(s, "慢慢幫我查天氣")
    assert "background" in text or "搞掂" in text
    for _ in range(50):
        if len(voice.spoken) > before:
            break
        await asyncio.sleep(0.05)
    assert len(voice.spoken) == before + 1 and "提你食藥" not in voice.spoken[-1]
    for _ in range(50):  # the relayed result is recorded once, with its delivery
        relayed = [r for r in s.dialogue.recent(20) if "helper 搞掂咗" in r.content]
        if relayed:
            break
        await asyncio.sleep(0.05)
    assert len(relayed) == 1 and relayed[0].meta.get("delivery") == "auto"


async def test_text_channel_handle_replies_to_origin(session):
    s, _fast, _smart, voice, tg = session
    await s.handle(ChannelMessage("telegram", "mum", "你好", language="yue"))
    assert tg.sent and tg.sent[-1].text == "收到：你好" and tg.sent[-1].channel == "telegram"
    assert not voice.spoken


async def test_content_refusal_becomes_a_polite_reply(session):
    s, *_ = session
    text = await collect(s, "講下嗰單敏感新聞")
    assert "唔方便講" in text
    assert s.dialogue.recent(1)[0].role == "assistant"


async def test_warm_is_throttled_and_keep_warm_runs(tmp_path, monkeypatch):
    """Speech onset warms the main agent's LLM connection at most every WARM_GAP_S (block #71)."""
    import asyncio

    from sidekick.agent import agent as agent_module

    calls: list[str] = []

    class FakeLLM:
        async def warm(self, slot, connections=1):
            calls.append(slot)

        def slots(self):
            return []  # nothing bound: the start pings no model

    session = AgentSession(FakeLLM(), tmp_path)  # type: ignore[arg-type]
    session.setup()
    session.warm()
    session.warm()
    await asyncio.sleep(0)
    assert calls == ["fast"]
    monkeypatch.setattr(agent_module, "KEEP_WARM_S", 0.01)
    await session.start()
    await asyncio.sleep(0.05)
    await session.stop()
    assert len(calls) >= 3


async def test_live_follows_turns_tools_and_counts(session):
    """The Live page sees each turn: first token, the tools it called, the outcome (block #69)."""
    s = session[0]
    seen: list[dict] = []
    original = s.turn_step

    def spy(message_id, kind, data):
        original(message_id, kind, data)
        if kind == "tool_start":
            seen.append(dict(s.live()["inflight"][0]))

    s.turn_step = spy  # type: ignore[method-assign]
    await collect(s, "記住我鍾意飲奶茶", speaker="household")
    assert seen and seen[0]["state"] == "tool" and seen[0]["tool"] == "remember"
    live = s.live()
    assert live["inflight"] == []
    last = live["last"]
    assert last["outcome"] == "done" and last["agent"] == "main" and last["channel"] == "voice"
    assert last["tools"] == [{"tool": "remember", "ok": True, "ms": last["tools"][0]["ms"]}]
    assert last["first_token_ms"] is not None and last["steps"] == 2
    assert live["today"]["turns"] == 1 and live["today"]["tools"] == 1
    assert live["first_token_median_ms"] is not None
    texts = [row["text"] for row in s.activity()]
    assert any("remember ok" in t for t in texts) and any("main turn (voice" in t for t in texts)
    assert s.activity(since=s.activity()[0]["ts"]) == []


def _slow_look(delay=0.6):
    from sidekick.agent import Tool, ToolResult

    async def handler(arguments, ctx):
        await asyncio.sleep(delay)
        return ToolResult(True, "一個人坐喺書枱前面")

    return Tool("slow_look", "Look around with the camera.", {"type": "object"}, handler)


async def test_a_slow_tool_gets_one_acknowledgement_the_model_never_sees(session):
    """Only a tool still running after ACK_AFTER_S is acknowledged aloud (block #76); the
    transcript keeps it, the model's context does not."""
    s, fast, *_ = session
    s.register_tools([_slow_look()])
    text = await collect(s, "你睇下周圍")
    ack = text.split("搞掂")[0]
    assert ack in ("好，等我睇下。", "稍等吓。", "等我諗諗。") and "搞掂" in text
    row = s.dialogue.recent(1)[0]
    assert row.role == "assistant" and row.content == text
    assert row.meta["reply"].startswith("搞掂")  # the model's own words only
    await collect(s, "你好呀")
    history = [m for m in fast.calls[-1][1:] if m]
    assert not any(ack in m for m in history)  # never shown back to the model
    assert any(m.startswith("搞掂") for m in history)


async def test_words_said_before_the_calls_stay_before_them(session):
    """The rebuilt step carries what the model said before its calls (block #76)."""
    s = session[0]
    from sidekick.agent import DialogueMessage

    conversation = s.dialogue.conversation_for("voice")
    s.dialogue.append(
        DialogueMessage("voice", "dad", "user", "今日有咩新聞", id="u1", conversation=conversation)
    )
    s.dialogue.append(
        DialogueMessage(
            "voice",
            "main",
            "tool",
            "- 新聞一",
            visibility="internal",
            agent="main",
            reply_to="u1",
            meta={
                "tool_call_id": "c1",
                "tool": "news_latest",
                "arguments": "{}",
                "step": 0,
                "said": "等我查下。",
            },
            conversation=conversation,
        )
    )
    s.dialogue.append(
        DialogueMessage(
            "voice",
            "main",
            "assistant",
            "等我查下。今日有一單新聞。",
            agent="main",
            reply_to="u1",
            meta={"tools": [{"name": "news_latest"}], "reply": "今日有一單新聞。"},
            conversation=conversation,
        )
    )
    view = s.dialogue.context_view(conversation, "main")
    assert [(m.role, m.content) for m in view] == [
        ("user", "今日有咩新聞"),
        ("assistant", "等我查下。"),
        ("tool", "- 新聞一"),
        ("assistant", "今日有一單新聞。"),
    ]
    assert view[1].tool_calls[0].name == "news_latest"


async def test_turns_someone_waits_for_are_hedged_and_jobs_are_not(session):
    """The main agent asks again after `main_hedge_s` on a person's turn (block #78)."""
    s = session[0]
    seen = []
    real = s.llm.stream

    def spy(*args, **kwargs):
        seen.append(kwargs.get("hedge_after_s"))
        return real(*args, **kwargs)

    s.llm.stream = spy
    await collect(s, "你好呀")
    await collect(s, "你好呀", channel="telegram")
    await s.run_job_turn("提我食藥", "household", "voice", "in_person", "job-9")
    assert seen == [2.5, 2.5, None]
    assert s._warm_connections() == 2  # its second request needs a pooled connection too
    from sidekick.config import ConfigAgents

    s.configure_main(ConfigAgents(main_hedge_s=0, main_max_steps=3))  # the Swarm card, live
    assert s.main.profile.hedge_after_s == 0 and s.main.profile.max_steps == 3
    assert s._warm_connections() == 1
    roster = s.roster()
    assert roster[0]["name"] == "main" and roster[0]["main"] and roster[0]["origin"] == "core"
    assert "Banana" in roster[0]["role"] and "delegate" in roster[0]["resolved_tools"]


async def test_acknowledgement_only_for_someone_waiting_in_the_room(session):
    """Text chats and jobs get no spoken acknowledgement before their tools (block #71)."""
    s = session[0]
    s.register_tools([_slow_look()])
    chat = await collect(s, "你睇下周圍", channel="telegram")
    assert chat.startswith("搞掂")
    chat = await collect(s, "記住我鍾意飲咖啡", channel="telegram")
    assert chat.startswith("搞掂")
    said = await s.run_job_turn("記住呢個測試", "household", "voice", "in_person", "job-1")
    assert said is not None and said.startswith("搞掂")
