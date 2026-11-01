"""The memory writer (block #70): episodes and facts from closed conversations, kept by rules."""

from __future__ import annotations

import json
import sqlite3
import time

from sidekick.agent import DialogueMessage, DialogueStore, MemoryStore
from sidekick.agent.writer import MemoryWriter, parse_json
from sidekick.llm import LLMResult, LLMSession


class JsonLLM:
    """A `smart` backend that answers with a prepared JSON object and records the prompts."""

    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    async def infer(self, messages, options):
        self.prompts.append([m.content for m in messages])
        answer = self.answer(messages) if callable(self.answer) else self.answer
        text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        return LLMResult(True, text, "fake", "fake", "smart-model", "****")

    async def stream(self, messages, options):  # pragma: no cover - not used
        raise NotImplementedError


NAMES = {"dad": "爸爸", "mum": "媽媽"}


def make(tmp_path, answer):
    llm = LLMSession()
    llm.configure_trace(None)
    backend = JsonLLM(answer)
    llm.setup("smart", backend)
    memory = MemoryStore(tmp_path / "memory_v1.db")
    dialogue = DialogueStore(tmp_path / "dialogue_v1.db")
    writer = MemoryWriter(
        memory,
        dialogue,
        llm,
        name=lambda who: NAMES.get(who, who),
        named=lambda who: who in NAMES,
    )
    return writer, memory, dialogue, backend


def talk(dialogue, channel, chat, lines, start, private=False):
    """Append a conversation: (speaker, text) pairs alternating with Bobby's replies."""
    key = "voice" if channel == "voice" else f"{channel}:{chat}"
    conversation = dialogue.conversation_for(key, start)
    ts = start
    for speaker, text in lines:
        role = "assistant" if speaker == "bobby" else "user"
        dialogue.append(
            DialogueMessage(
                channel,
                "main" if role == "assistant" else speaker,
                role,
                text,
                ts=ts,
                visibility="private" if private else "public",
                agent="main" if role == "assistant" else None,
                conversation=conversation,
            )
        )
        ts += 10
    return conversation


def test_parse_json_tolerates_fences_and_chatter():
    assert parse_json('```json\n{"title": "a"}\n```') == {"title": "a"}
    assert parse_json('好的：{"facts": []} 完') == {"facts": []}
    assert parse_json("no json") is None and parse_json(None) is None


async def test_closed_conversation_becomes_an_episode_and_kept_facts(tmp_path):
    now = time.time()
    answer = {
        "title": "爸爸講飲茶同睇牙",
        "summary": "爸爸話鍾意飲凍檸茶，聽日要睇牙；媽媽話屋企星期日去飲茶。",
        "followups": [
            {
                "who": "dad",
                "text": "爸爸睇牙",
                "due": time.strftime("%Y-%m-%d", time.localtime(now + 86400)),
            },
            {"who": "person:3", "text": "訪客", "due": "2099-01-01"},
        ],
        "facts": [
            {
                "op": "add",
                "about": "dad",
                "teller": "dad",
                "category": "preference",
                "text": "爸爸鍾意飲凍檸茶",
            },
            {
                "op": "add",
                "about": "household",
                "teller": "mum",
                "category": "routine",
                "text": "屋企星期日去飲茶",
            },
            {
                "op": "add",
                "about": "mum",
                "teller": "dad",
                "category": "health",
                "text": "媽媽有高血壓",
            },
            {
                "op": "add",
                "about": "dad",
                "teller": "dad",
                "category": "health",
                "text": "爸爸聽日睇牙",
                "valid_until": "2099-01-01",
            },
            {
                "op": "add",
                "about": "person:3",
                "teller": "person:3",
                "category": "preference",
                "text": "訪客鍾意貓",
            },
            {
                "op": "add",
                "about": "mum",
                "teller": "dad",
                "category": "preference",
                "text": "爸爸話媽媽鍾意榴槤",
            },
        ],
    }
    writer, memory, dialogue, backend = make(tmp_path, answer)
    room = talk(
        dialogue,
        "voice",
        "",
        [
            ("dad", "我鍾意飲凍檸茶，聽日要去睇牙"),
            ("bobby", "好呀，祝你順利"),
            ("mum", "我哋星期日去飲茶"),
            ("person:3", "我鍾意貓"),
            ("dad", "老婆有高血壓，佢仲好鍾意榴槤"),
        ],
        now - 3600,
    )
    open_one = talk(dialogue, "voice", "", [("dad", "仲有呢")], now - 30)  # still going on
    assert open_one != room
    assert [i["conversation"] for i in writer.due(now)] == [room]
    assert await writer.tick(now) == 1
    episode = memory.episode_for(room)
    assert episode is not None and episode.title == "爸爸講飲茶同睇牙"
    assert episode.participants == ("dad", "mum", "person:3") and episode.visibility == "public"
    assert [f["who"] for f in episode.followups] == ["dad"]  # an unnamed person gets none
    facts = {f.text: f for f in memory.facts()}
    assert set(facts) == {
        "爸爸鍾意飲凍檸茶",
        "屋企星期日去飲茶",
        "爸爸聽日睇牙",
        "爸爸話媽媽鍾意榴槤",
    }
    assert (
        facts["屋企星期日去飲茶"].scope == "household" and facts["屋企星期日去飲茶"].teller == "mum"
    )
    assert facts["爸爸聽日睇牙"].visibility == "private"  # health: private, first person only
    assert (
        facts["爸爸話媽媽鍾意榴槤"].scope == "dad" and facts["爸爸話媽媽鍾意榴槤"].subject == "mum"
    )
    assert all(f.origin == "inferred" and f.episode == episode.id for f in facts.values())
    assert facts["爸爸鍾意飲凍檸茶"].sources  # the rows it came from
    prompt = backend.prompts[0][1]
    assert "visitor 1 (unnamed)" in prompt and "dad: 爸爸" in prompt and "睇牙" in prompt
    assert await writer.tick(now) == 0  # written once
    block = memory.block("dad", name=lambda who: NAMES.get(who, who))
    assert "爸爸鍾意飲凍檸茶" in block and "爸爸講飲茶同睇牙" in block and "爸爸睇牙" in block
    assert "聽日睇牙" not in block.split("Follow-ups")[0]  # the private health fact stays out


async def test_private_chat_facts_stay_with_the_teller(tmp_path):
    answer = {
        "title": "爸爸私下講嘢",
        "summary": "爸爸講咗屋企嘅事",
        "facts": [
            {
                "op": "add",
                "about": "household",
                "teller": "dad",
                "category": "routine",
                "text": "屋企逢星期六大掃除",
            },
        ],
    }
    writer, memory, dialogue, _ = make(tmp_path, answer)
    now = time.time()
    chat = talk(
        dialogue, "telegram", "dad", [("dad", "我哋逢星期六大掃除")], now - 7200, private=True
    )
    await writer.tick(now)
    episode = memory.episode_for(chat)
    assert episode.visibility == "private" and episode.private_to == "dad"
    fact = memory.facts()[0]
    assert fact.scope == "dad" and fact.visibility == "private"  # never into the household
    assert memory.block("dad", private=False).find("大掃除") < 0
    assert "大掃除" in memory.block("dad", private=True)
    assert memory.episodes_with("dad", private=False) == []  # a private episode stays private
    assert memory.episodes_with("dad", private=True)[0].id == episode.id


async def test_supersede_rules_and_unnamed_only_conversations(tmp_path):
    writer, memory, dialogue, backend = make(tmp_path, {})
    explicit = memory.remember("dad", "爸爸鍾意飲奶茶", teller="dad")
    mum_says = memory.remember("dad", "爸爸鍾意行山", teller="mum", origin="explicit")
    tea = memory.remember("household", "屋企星期日飲茶", teller="mum", origin="explicit")

    def answer(messages):
        return {
            "title": "改咗口味",
            "summary": "爸爸而家唔飲奶茶",
            "facts": [
                {
                    "op": "supersede",
                    "replaces": explicit.id[:8],
                    "about": "dad",
                    "teller": "dad",
                    "category": "preference",
                    "text": "爸爸而家鍾意飲豆漿",
                },
                {
                    "op": "supersede",
                    "replaces": mum_says.id[:8],
                    "about": "dad",
                    "teller": "dad",
                    "category": "preference",
                    "text": "爸爸唔鍾意行山",
                },
                {
                    "op": "supersede",
                    "replaces": tea.id[:8],
                    "about": "household",
                    "teller": "dad",
                    "category": "routine",
                    "text": "屋企唔再飲茶",
                },
            ],
        }

    backend.answer = answer
    now = time.time()
    talk(
        dialogue,
        "voice",
        "",
        [("dad", "我而家唔飲奶茶，飲豆漿"), ("dad", "我唔鍾意行山"), ("dad", "今個星期日唔去飲茶")],
        now - 3600,
    )
    await writer.tick(now)
    old = memory.fact(explicit.id)
    assert old is not None and not old.active and old.superseded_by  # kept as evidence
    assert not memory.fact(mum_says.id).active  # a person corrects what is said about them
    assert memory.fact(tea.id).active  # mum's explicit household fact: only mum changes it
    texts = {f.text for f in memory.facts("dad")}
    assert {"爸爸而家鍾意飲豆漿", "爸爸唔鍾意行山"} <= texts and "爸爸鍾意飲奶茶" not in texts
    assert "屋企唔再飲茶" in {f.text for f in memory.facts("household")}  # added beside it
    # a conversation of unnamed people: an episode, no facts
    backend.answer = {
        "title": "一位訪客問天氣",
        "summary": "一位訪客問今日天氣",
        "facts": [{"op": "add", "about": "person:9", "teller": "person:9", "text": "訪客住喺樓上"}],
    }
    before = memory.count()
    visitor = talk(dialogue, "voice", "", [("person:9", "今日天氣點")], now - 1200)
    await writer.tick(now)
    assert memory.episode_for(visitor).title == "一位訪客問天氣" and memory.count() == before


async def test_failures_retry_exclusions_and_rolling(tmp_path):
    writer, memory, dialogue, backend = make(tmp_path, "唔識答")
    now = time.time()
    room = talk(dialogue, "voice", "", [("dad", "早晨")], now - 4000)
    talk(dialogue, "dashboard", "dad", [("dad", "測試")], now - 4000)  # Agent → Test: never
    reminder = dialogue.conversation_for("voice", now - 2000)
    dialogue.append(
        DialogueMessage(
            "voice", "main", "assistant", "夠鐘食藥", ts=now - 2000, conversation=reminder
        )
    )  # Bobby alone: nothing to write
    assert [i["conversation"] for i in writer.due(now)] == [room]
    await writer.tick(now)
    failed = memory.episode_for(room)
    assert failed.status == "failed" and failed.attempts == 1 and writer.last_error
    await writer.tick(now)
    await writer.tick(now)
    assert memory.episode_for(room).attempts == 3 and writer.due(now) == []  # gives up
    # a long conversation is written as it goes, then again when it closes
    backend.answer = {"title": "傾咗好耐", "summary": "爸爸講咗好多", "facts": []}
    long_one = talk(dialogue, "voice", "", [("dad", f"第{i}句") for i in range(13)], now - 200)
    assert long_one in [i["conversation"] for i in writer.due(now)]
    await writer.tick(now)
    rolling = memory.episode_for(long_one)
    assert rolling.status == "ok" and rolling.user_turns == 13
    assert long_one not in [i["conversation"] for i in writer.due(now)]
    # busy: a turn in flight stops the writer
    writer.busy = lambda: True
    talk(dialogue, "voice", "", [("dad", "仲有")], now - 100)
    assert await writer.tick(now + 400) == 0


async def test_a_deleted_episode_is_not_written_again(tmp_path):
    """The dashboard's delete leaves an empty marker the writer skips (block #76)."""
    writer, memory, dialogue, _backend = make(
        tmp_path, {"title": "講咗天氣", "summary": "爸爸問天氣", "facts": []}
    )
    now = time.time()
    room = talk(dialogue, "voice", "", [("dad", "今日天氣點")], now - 4000)
    await writer.tick(now)
    episode = memory.episode_for(room)
    assert episode.status == "ok" and memory.episode_count() == 1
    assert memory.delete_episode(episode.id) and not memory.delete_episode(episode.id)
    gone = memory.episode(episode.id)
    assert gone.status == "deleted" and gone.summary == "" and gone.title == ""
    assert writer.due(now) == [] and await writer.tick(now) == 0  # not written again
    assert memory.episodes(include_failed=True) == [] and memory.episode_count() == 0
    # deleting a contact empties their private episodes the same way
    chat = talk(dialogue, "telegram", "tg:1", [("dad", "我好攰")], now - 3000, private=True)
    await writer.tick(now)
    assert memory.episode_for(chat).visibility == "private"
    memory.drop_scope("dad")
    assert memory.episode_for(chat).status == "deleted" and writer.due(now) == []


async def test_nightly_expires_digests_and_refuses_a_big_merge(tmp_path):
    writer, memory, _, backend = make(tmp_path, {})
    memory.remember("dad", "爸爸星期三睇牙", valid_until="2000-01-01", origin="inferred")
    for i in range(40):
        memory.remember("dad", f"爸爸鍾意第{i}樣嘢，佢話呢樣嘢好好，日日都要", origin="inferred")
    short = {f.text: f.id[:8] for f in memory.facts("dad")}
    backend.answer = lambda messages: (
        "爸爸鍾意好多嘢。"
        if "profile" in (messages[0].content or "")
        else {"retire": [{"id": v, "because": None} for v in list(short.values())[:20]]}
    )
    counts = await writer.nightly("2026-10-30")
    assert counts["expired"] == 1 and counts["merged"] == 0  # 20 of 40: refused
    assert counts["digests"] == 1 and memory.digest("dad")[0] == "爸爸鍾意好多嘢。"
    assert memory.meta("nightly") == "2026-10-30"
    block = memory.block("dad")
    assert "爸爸鍾意好多嘢。" in block and "第39樣" not in block  # the digest stands in


def test_migration_moves_the_first_table(tmp_path):
    path = tmp_path / "memory_v1.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE memory (id TEXT PRIMARY KEY, ts REAL NOT NULL, scope TEXT NOT NULL,"
            " kind TEXT NOT NULL, text TEXT NOT NULL, source_id TEXT);"
            "INSERT INTO memory VALUES ('f1', 1.0, 'household', 'fact', '屋企人鍾意飲奶茶', 'm1');"
            "INSERT INTO memory VALUES ('e1', 2.0, 'household', 'episode', 'old summary', NULL);"
            "PRAGMA user_version = 1;"
        )
    store = MemoryStore(path)
    facts = store.facts()
    assert [(f.id, f.text, f.origin, f.sources) for f in facts] == [
        ("f1", "屋企人鍾意飲奶茶", "explicit", ("m1",))
    ]
    assert store.db.user_version() == 2
