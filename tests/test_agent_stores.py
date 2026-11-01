"""Agent stores: timeline visibility view, memory, skills, confirmation words."""

from __future__ import annotations

import pytest

from sidekick.agent import (
    DialogueMessage,
    DialogueStore,
    MemoryStore,
    Skill,
    SkillStore,
    is_affirmative,
    is_negative,
    parse_markdown,
    render_markdown,
)
from sidekick.agent.dialogue import HISTORY_TOOL_CHARS


def test_timeline_conversations_visibility_and_tool_pairs(tmp_path):
    """A turn sees only its own conversation (block #70), with the visibility rules inside."""
    store = DialogueStore(tmp_path / "dialogue_v1.db")
    room = store.conversation_for("voice", 1000.0)
    assert room.startswith("voice@") and store.conversation_for("voice", 1200.0) == room
    assert store.conversation_for("voice", 1200.0 + store.voice_gap_s + 1) != room  # a pause
    chat = store.conversation_for("telegram:tg:7", 1000.0)
    store.append(DialogueMessage("voice", "dad", "user", "你好", ts=1000.0, conversation=room))
    store.append(
        DialogueMessage(
            "telegram",
            "mum",
            "user",
            "secret plan",
            ts=1001.0,
            visibility="private",
            conversation=chat,
        )
    )
    store.append(
        DialogueMessage(
            "voice",
            "main",
            "assistant",
            "我查下",
            ts=1002.0,
            agent="main",
            meta={"tool_calls": [{"id": "c1", "name": "recall", "arguments": "{}"}]},
            conversation=room,
        )
    )
    store.append(
        DialogueMessage(
            "voice",
            "main",
            "tool",
            "nothing remembered",
            ts=1003.0,
            visibility="internal",
            agent="main",
            meta={"tool_call_id": "c1", "tool": "recall"},
            conversation=room,
        )
    )
    store.append(
        DialogueMessage(
            "voice",
            "news",
            "internal",
            "news result",
            ts=1004.0,
            visibility="internal",
            agent="news",
            conversation=room,
        )
    )
    store.append(
        DialogueMessage(
            "voice", "main", "assistant", "我唔記得啦", ts=1005.0, agent="main", conversation=room
        )
    )
    store.append(DialogueMessage("voice", "mum", "user", "我都想知", ts=1006.0, conversation=room))
    view = store.context_view(room, "main", name=lambda who: {"dad": "爸爸"}.get(who, who))
    texts = [(m.role, m.content) for m in view]
    assert ("user", "[爸爸] 你好") in texts and ("user", "[mum] 我都想知") in texts  # two speakers
    assert all("secret" not in (m.content or "") for m in view)  # another conversation
    assert any(m.role == "tool" and m.tool_call_id == "c1" for m in view)
    assert all("news result" not in (m.content or "") for m in view)  # other agent's internal row
    assert [m.content for m in store.context_view(chat, "main")] == ["secret plan"]
    assert store.context_view(None, "main") == []
    assert store.count() == 7 and len(store.recent(2)) == 2
    # the Live card: the rows people saw (no tool steps, no internal notes), paged back by time
    said = store.recent(10, conversation=True)
    assert [m.content for m in said] == ["我都想知", "我唔記得啦", "我查下", "secret plan", "你好"]
    earlier = store.recent(10, conversation=True, before=said[2].ts)
    assert [m.content for m in earlier] == ["secret plan", "你好"]
    assert store.search("查下")[0].content == "我查下"
    # budget keeps the newest rows, drops orphan tool results, and leads with the earlier part
    tiny = store.context_view(room, "main", budget_chars=30, earlier="佢哋傾緊天氣")
    assert tiny and tiny[-1].content == "我都想知" and tiny[0].content.startswith("[earlier")
    assert all(
        m.role != "tool" or m.tool_call_id in {c.id for v in tiny for c in v.tool_calls}
        for m in tiny
    )
    # conversations for the writer
    infos = {i["conversation"]: i for i in store.conversations(0.0)}
    assert infos[room]["user_turns"] == 2 and infos[chat]["private"] == 1


def test_conversation_backfill(tmp_path):
    """Rows written before conversations existed get theirs once, by the same rule."""
    import sqlite3

    path = tmp_path / "dialogue_v1.db"
    store = DialogueStore(path)
    rows = [
        ("u1", 1000.0, "voice", "dad", "user", None),
        ("a1", 1001.0, "voice", "main", "assistant", "u1"),
        ("u2", 1100.0, "voice", "mum", "user", None),
        ("u3", 5000.0, "voice", "dad", "user", None),
        ("t1", 5001.0, "telegram", "tg:7", "user", None),
        ("a2", 5002.0, "telegram", "main", "assistant", "t1"),
        ("j1", 5003.0, "voice", "main", "tool", "job-message"),
    ]
    with sqlite3.connect(path) as conn:
        for row_id, ts, channel, speaker, role, reply_to in rows:
            conn.execute(
                "INSERT INTO messages (id, ts, channel, speaker, role, content, visibility,"
                " reply_to) VALUES (?, ?, ?, ?, ?, 'x', 'public', ?)",
                (row_id, ts, channel, speaker, role, reply_to),
            )
    store = DialogueStore(path)  # reopening places the rows
    by_id = {
        r["id"]: r["conversation"] for r in store.db.query("SELECT id, conversation FROM messages")
    }
    assert by_id["u1"] == by_id["a1"] == by_id["u2"] and by_id["u1"].startswith("voice@")
    assert by_id["u3"] != by_id["u1"]  # more than five minutes later
    assert by_id["t1"] == by_id["a2"] and by_id["t1"].startswith("telegram:tg:7@")
    assert by_id["j1"] == ""  # a job's step belongs to no conversation
    assert store.conversation_for("voice", 5100.0) == by_id["u3"]  # read back after a restart


def test_context_view_rebuilds_tool_steps(tmp_path):
    """Past replies show the calls behind them, as the turn recorded them (block #63)."""
    store = DialogueStore(tmp_path / "dialogue_v1.db")
    room = store.conversation_for("voice")
    store.append(DialogueMessage("voice", "dad", "user", "記住我鍾意飲烏龍茶", conversation=room))
    for call_id, tool, result in (
        ("c1", "remember", "remembered (dad): 鍾意飲烏龍茶"),
        ("c2", "news_latest", "x" * 1000),
    ):
        store.append(
            DialogueMessage(
                "voice",
                "main",
                "tool",
                result,
                visibility="internal",
                agent="main",
                meta={
                    "tool_call_id": call_id,
                    "tool": tool,
                    "arguments": '{"text": "t"}',
                    "ok": True,
                },
                conversation=room,
            )
        )
    store.append(
        DialogueMessage("voice", "main", "assistant", "記低咗。", agent="main", conversation=room)
    )
    view = store.context_view(room, "main")
    assert [m.role for m in view] == ["user", "assistant", "tool", "tool", "assistant"]
    assert [(c.id, c.name, c.arguments) for c in view[1].tool_calls] == [
        ("c1", "remember", '{"text": "t"}'),
        ("c2", "news_latest", '{"text": "t"}'),
    ]
    assert view[2].tool_call_id == "c1" and view[2].content.startswith("remembered")
    assert len(view[3].content) == HISTORY_TOOL_CHARS + 1  # cut, with an ellipsis
    assert view[4].content == "記低咗。"
    other = store.context_view(room, "news")  # another agent sees no steps
    assert [m.role for m in other] == ["user", "assistant"] and not other[1].tool_calls


def test_memory_scopes_and_block(tmp_path):
    store = MemoryStore(tmp_path / "memory_v1.db")
    store.remember("dad", "爸爸鍾意飲奶茶", "m1")
    store.remember("household", "屋企有隻貓叫波波", "m2")
    store.remember("mum", "媽媽對花生敏感", "m3", category="health")
    store.remember("dad", "爸爸有高血壓", category="health", teller="dad")
    assert store.remember("dad", "爸爸鍾意飲奶茶").id  # duplicate collapses
    assert store.count() == 4
    assert [f.text for f in store.recall(["dad", "household"])][-2:] == [
        "屋企有隻貓叫波波",
        "爸爸鍾意飲奶茶",
    ]
    assert store.recall(["dad", "household"], "貓")[0].text == "屋企有隻貓叫波波"
    assert store.facts("mum")[0].visibility == "private"  # a sensitive category is private
    block = store.block("dad", name=lambda who: {"dad": "爸爸"}.get(who, who))
    assert block.startswith("What you remember") and "About 爸爸" in block
    assert "爸爸鍾意飲奶茶" in block and "波波" in block and "花生" not in block
    assert "高血壓" not in block  # private: not in the room
    assert "高血壓" in store.block("dad", private=True)  # in their own private chat
    assert store.forget(text="奶茶", scope="dad") == 1 and store.count() == 3
    guest = store.block("guest:1")
    assert "波波" in guest and "花生" not in guest and "About guest" not in guest


def test_memory_follows_identity(tmp_path):
    """Unnamed people keep no facts; scopes move to a contact and go with a deleted one (#63)."""
    store = MemoryStore(tmp_path / "memory_v1.db")
    for unnamed in ("person:7", "guest:2"):
        with pytest.raises(ValueError):
            store.remember(unnamed, "我叫阿明")
    assert store.count() == 0
    store.remember("owner", "主人鍾意飲奶茶")
    store.remember("mum", "對花生敏感")
    assert store.forget(text="花生") == 0  # a substring delete needs a scope
    assert (
        store.move_scope("owner", "wei") == 1 and store.recall(["wei"])[0].text == "主人鍾意飲奶茶"
    )
    assert store.move_scope("owner", "wei") == 0 and store.move_scope("wei", "wei") == 0
    assert store.drop_scope("mum") == 1 and store.recall(["mum"]) == []
    assert store.count() == 1


def test_skills_parse_and_crud(tmp_path):
    name, description, body = parse_markdown(
        "---\nname: briefing\ndescription: Morning news style\n---\nKeep it short.\n"
    )
    assert (name, description, body) == ("briefing", "Morning news style", "Keep it short.")
    name2, desc2, _ = parse_markdown("# Story time\nTell stories with sound effects.\n")
    assert name2 == "Story time" and desc2.startswith("Tell stories")
    store = SkillStore(tmp_path / "skills_v1.db")
    skill = store.upsert_markdown(
        "---\nname: briefing\ndescription: Morning news style\n---\nKeep it short.\n",
        origin="extension:news",
    )
    store.upsert(Skill("quiet", "Be quiet at night", "Whisper.", enabled=False))
    assert store.get("briefing").body == "Keep it short." and skill.origin == "extension:news"
    block = store.descriptions_block()
    assert "briefing" in block and "quiet" not in block
    assert store.descriptions_block(("quiet",)) == ""
    assert "name: briefing" in render_markdown(skill)
    assert store.set_enabled("quiet", True) and "quiet" in store.descriptions_block()
    assert store.delete_origin("extension:news") == 1 and store.get("briefing") is None
    assert store.delete("quiet") and store.list() == []


def test_affirmatives():
    assert (
        is_affirmative("好呀")
        and is_affirmative("確認")
        and is_affirmative("yes please")
        and is_affirmative("OK")
    )
    assert (
        not is_affirmative("唔好")
        and not is_affirmative("好長嘅一段說話，唔係確認")
        and is_negative("不要")
    )
    assert not is_affirmative("今日天氣好好")


def test_short_skills_ride_in_the_prompt(tmp_path):
    """A short skill's body is inlined (no skill_read round); a long one is listed only (#71)."""
    store = SkillStore(tmp_path / "skills_v1.db")
    store.upsert(Skill("storytelling", "how to tell a story", "Short paragraphs, one beat each."))
    store.upsert(Skill("robot body", "expressions", "x" * 2000))
    block = store.descriptions_block()
    assert "Skill storytelling:\nShort paragraphs, one beat each." in block
    assert "storytelling: how to tell a story (below, no need to read it)" in block
    assert "- robot body: expressions\n" in block + "\n" and "x" * 50 not in block
