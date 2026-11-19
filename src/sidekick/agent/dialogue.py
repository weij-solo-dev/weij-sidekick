"""sidekick.agent.dialogue — the one append-only timeline (L0), its conversations, the context view

Overview
    Every message from every channel lands in `dialogue_v1.db` (invariant 12): user utterances,
    assistant replies, tool calls and results, internal notes (subagent results). Each row
    belongs to a **conversation** (L0 of the memory pyramid, block #70): the room (`voice`) is
    one conversation while turns follow each other within `VOICE_GAP_S`, a chat (channel + chat
    id, the dashboard's test card per speaker) within `TEXT_GAP_S`. A turn never replays the
    raw table; it gets `context_view()`: the rows of its own conversation that the agent may
    see, within a character budget, rendered as LLM messages — so other people's chats and old
    test turns no longer act as examples, and what is older lives in memory (`memory.py`).
Design
    A conversation id is readable: `<key>@<start, local time>` (`voice@20261029-185600`,
    `telegram:tg:42@…`); the open conversation of a key is kept in memory and, after a restart,
    read back from its newest row. Rows written before conversations existed get theirs once,
    by the same rule (replies follow the row they answer). Inside a conversation the visibility
    rules still apply: `internal` rows only for the agent that produced them; a private chat is
    a conversation of its own, so its rows never reach anyone else's view. Tool rows carry
    their `tool_call_id`, tool name and raw arguments in `meta`, and the view rebuilds the call
    step from them (an assistant message with those calls, then the results, cut to
    `HISTORY_TOOL_CHARS`): the call step itself is not stored, and without it every past reply
    looked tool-free, so the model learned to answer 「記低咗」 without calling `remember`
    (block #63). Each step is rebuilt on its own with the words the model said before its calls
    (`said`), and an assistant row whose transcript holds more than the model's last words (the
    platform's acknowledgement, words said before the calls) shows the model only those
    (`reply`): with the whole transcript after the results, it learned to open every reply with
    「好，等我睇下。」 (block #76). When a long conversation outgrows the budget, the summary of its earlier part
    (the memory writer's rolling episode) leads the view. Performance cues in assistant text
    (`[express:…]`, `[style:…]`) stay on the timeline but are left out of the view, so old
    replies do not teach the model to tag every reply (block #50). User rows carry the
    speaker's display name in a room with several people. The raw table is never rewritten.
    `recent(…, conversation=True, before=…)` pages back through the rows people saw (user and
    assistant rows of every channel) for the dashboard's Live card.
Depends on
    sidekick.log, sidekick.storage, sidekick.llm.

See Also
--------
    AGENTS.md "Dialogue and memory", PLAN.md blocks "[2026-10-29 #63]", "[2026-10-29 #70]".

"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sidekick.llm import LLMMessage, LLMToolCall
from sidekick.log import Log
from sidekick.storage import Database

from .schemas import DialogueMessage

# Performance cues in assistant text (`[express:laugh]`, `[style:lively]`): kept on the timeline,
# left out of the context view so old replies do not teach the model to tag every reply.
PERFORMANCE_TAG = re.compile(r"\[\s*(?:express|style)\s*:[^\]]*\]\s*", re.IGNORECASE)
# A past tool result in the view is cut to this many characters: the call is what matters.
HISTORY_TOOL_CHARS = 400
# A conversation goes on while its rows follow each other within this gap (block #70).
VOICE_GAP_S = 300.0  # the room
TEXT_GAP_S = 900.0  # a chat

MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY, ts REAL NOT NULL, channel TEXT NOT NULL, speaker TEXT NOT NULL,
        role TEXT NOT NULL, content TEXT NOT NULL, visibility TEXT NOT NULL, agent TEXT,
        reply_to TEXT, attachments TEXT, delivered_to TEXT, meta TEXT
    );
    CREATE INDEX IF NOT EXISTS messages_ts ON messages(ts);
    CREATE INDEX IF NOT EXISTS messages_channel ON messages(channel, ts);
    """,
    """
    ALTER TABLE messages ADD COLUMN conversation TEXT;
    CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation, ts);
    """,
]


def conversation_key(channel: str, chat: str) -> str:
    """The key conversations are tracked by: the room for voice, else the chat."""
    return "voice" if channel == "voice" else f"{channel}:{chat}"


def key_of(conversation: str) -> str:
    """The key part of a conversation id (`telegram:tg:42@20261029-190102` → `telegram:tg:42`)."""
    return conversation.rsplit("@", 1)[0]


class DialogueStore:
    """Append-only timeline."""

    def __init__(self, path: Path) -> None:
        self.db = Database(path, MIGRATIONS)
        self._open: dict[str, tuple[str, float]] = {}  # key → (conversation, last row ts)
        self.voice_gap_s = VOICE_GAP_S
        self.text_gap_s = TEXT_GAP_S
        if self.db.query(
            "SELECT 1 FROM messages WHERE conversation IS NULL AND role = 'user' LIMIT 1"
        ):
            self.backfill()

    def append(self, message: DialogueMessage) -> str:
        """Store one row; returns its id."""
        self.db.execute(
            "INSERT INTO messages (id, ts, channel, speaker, role, content, visibility, agent, reply_to, attachments, delivered_to, meta, conversation)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message.id,
                message.ts,
                message.channel,
                message.speaker,
                message.role,
                message.content,
                message.visibility,
                message.agent,
                message.reply_to,
                json.dumps(list(message.attachments)),
                message.delivered_to,
                json.dumps(message.meta, ensure_ascii=False),
                message.conversation,
            ),
        )
        if message.conversation:
            key = key_of(message.conversation)
            open_ = self._open.get(key)
            if open_ is None or open_[0] == message.conversation:
                self._open[key] = (
                    message.conversation,
                    max(message.ts, open_[1] if open_ else 0.0),
                )
        return message.id

    # --------------------------------------------------------- conversations

    def gap_for(self, key: str) -> float:
        """How long a conversation of `key` may pause and still go on."""
        return self.voice_gap_s if key == "voice" else self.text_gap_s

    def conversation_for(self, key: str, ts: float | None = None) -> str:
        """The conversation a new row of `key` belongs to: the open one, or a new one."""
        ts = time.time() if ts is None else ts
        open_ = self._open.get(key)
        if open_ is None:
            rows = self.db.query(
                "SELECT conversation, ts FROM messages WHERE substr(conversation, 1, ?) = ?"
                " ORDER BY ts DESC LIMIT 1",
                (len(key) + 1, key + "@"),
            )
            if rows:
                open_ = (rows[0]["conversation"], float(rows[0]["ts"]))
        if open_ is not None and ts - open_[1] <= self.gap_for(key):
            self._open[key] = (open_[0], max(ts, open_[1]))
            return open_[0]
        conversation = f"{key}@{time.strftime('%Y%m%d-%H%M%S', time.localtime(ts))}"
        self._open[key] = (conversation, ts)
        return conversation

    def conversation_rows(self, conversation: str, limit: int = 400) -> list[DialogueMessage]:
        """A conversation's rows, oldest first."""
        rows = self.db.query(
            "SELECT * FROM messages WHERE conversation = ? ORDER BY ts ASC LIMIT ?",
            (conversation, limit),
        )
        return [self._row(r) for r in rows]

    def conversations(self, since: float) -> list[dict[str, Any]]:
        """Every conversation with a row after `since`: channel, start, end, rows, user turns."""
        rows = self.db.query(
            "SELECT conversation, MIN(channel) AS channel, MIN(ts) AS start, MAX(ts) AS end,"
            " COUNT(*) AS rows, SUM(CASE WHEN role = 'user' THEN 1 ELSE 0 END) AS user_turns,"
            " SUM(CASE WHEN visibility = 'private' AND role = 'user' THEN 1 ELSE 0 END) AS private"
            " FROM messages WHERE conversation IS NOT NULL AND conversation != ''"
            " GROUP BY conversation HAVING MAX(ts) > ? ORDER BY MAX(ts) ASC",
            (since,),
        )
        return [dict(r) for r in rows]

    def backfill(self) -> int:
        """Give rows written before conversations existed theirs (once, by the same rule)."""
        rows = self.db.query(
            "SELECT id, ts, channel, speaker, role, reply_to, conversation FROM messages"
            " ORDER BY ts ASC"
        )
        assigned: dict[str, str] = {}  # row id → conversation
        last: dict[str, tuple[str, float]] = {}  # key → (conversation, ts)
        updates: list[tuple[str, str]] = []

        def place(key: str, ts: float) -> str:
            open_ = last.get(key)
            if open_ is not None and ts - open_[1] <= self.gap_for(key):
                last[key] = (open_[0], ts)
                return open_[0]
            conversation = f"{key}@{time.strftime('%Y%m%d-%H%M%S', time.localtime(ts))}"
            last[key] = (conversation, ts)
            return conversation

        for row in rows:
            if row["conversation"]:
                assigned[row["id"]] = row["conversation"]
                last[key_of(row["conversation"])] = (row["conversation"], row["ts"])
                continue
            if row["role"] == "user":
                conversation = place(conversation_key(row["channel"], row["speaker"]), row["ts"])
            elif row["reply_to"] and row["reply_to"] in assigned:
                conversation = assigned[row["reply_to"]]
            elif row["role"] == "assistant" and row["channel"] == "voice":
                conversation = place("voice", row["ts"])  # Banana spoke first in the room
            else:
                conversation = ""  # a job's steps, a delivery to a chat we cannot tell
            assigned[row["id"]] = conversation
            updates.append((conversation, row["id"]))
        with self.db.transaction() as conn:
            conn.executemany("UPDATE messages SET conversation = ? WHERE id = ?", updates)
        Log.info(f"conversations: {len(updates)} earlier row(s) placed")
        return len(updates)

    @staticmethod
    def _row(row: Any) -> DialogueMessage:
        return DialogueMessage(
            channel=row["channel"],
            speaker=row["speaker"],
            role=row["role"],
            content=row["content"],
            id=row["id"],
            ts=row["ts"],
            visibility=row["visibility"],
            agent=row["agent"],
            reply_to=row["reply_to"],
            attachments=tuple(json.loads(row["attachments"] or "[]")),
            delivered_to=row["delivered_to"],
            meta=json.loads(row["meta"] or "{}"),
            conversation=row["conversation"],
        )

    def recent(
        self,
        limit: int = 50,
        channel: str | None = None,
        *,
        before: float | None = None,
        conversation: bool = False,
    ) -> list[DialogueMessage]:
        """Newest rows first, paged back with `before` (a timestamp).

        `conversation` keeps the user and assistant rows people saw (no tool steps, no internal
        notes): the dashboard's Live card.
        """
        where: list[str] = []
        params: list[Any] = []
        if channel:
            where.append("channel = ?")
            params.append(channel)
        if before is not None:
            where.append("ts < ?")
            params.append(before)
        if conversation:
            where.append("role IN ('user', 'assistant') AND visibility != 'internal'")
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        rows = self.db.query(
            f"SELECT * FROM messages{clause} ORDER BY ts DESC LIMIT ?", (*params, limit)
        )
        return [self._row(r) for r in rows]

    def since(self, ts: float, role: str | None = None, limit: int = 200) -> list[DialogueMessage]:
        """Rows after a timestamp, oldest first."""
        if role:
            rows = self.db.query(
                "SELECT * FROM messages WHERE ts > ? AND role = ? ORDER BY ts ASC LIMIT ?",
                (ts, role, limit),
            )
        else:
            rows = self.db.query(
                "SELECT * FROM messages WHERE ts > ? ORDER BY ts ASC LIMIT ?", (ts, limit)
            )
        return [self._row(r) for r in rows]

    def between(self, start_ts: float, end_ts: float, limit: int = 1000) -> list[DialogueMessage]:
        """Rows with `start_ts <= ts < end_ts`, oldest first (replay by time range)."""
        rows = self.db.query(
            "SELECT * FROM messages WHERE ts >= ? AND ts < ? ORDER BY ts ASC LIMIT ?",
            (start_ts, end_ts, limit),
        )
        return [self._row(r) for r in rows]

    def search(self, text: str, limit: int = 20) -> list[DialogueMessage]:
        """Substring search, newest first."""
        rows = self.db.query(
            "SELECT * FROM messages WHERE content LIKE ? ORDER BY ts DESC LIMIT ?",
            (f"%{text}%", limit),
        )
        return [self._row(r) for r in rows]

    def count(self) -> int:
        """Row count."""
        return int(self.db.query("SELECT COUNT(*) AS n FROM messages")[0]["n"])

    def mark_delivered(self, message_id: str, to: str) -> None:
        """Record where a reply went."""
        self.db.execute("UPDATE messages SET delivered_to = ? WHERE id = ?", (to, message_id))

    # ----------------------------------------------------------------- views

    def view_rows(self, conversation: str, agent: str, limit: int = 60) -> list[DialogueMessage]:
        """The newest rows of a conversation this agent may see, oldest first."""
        rows = [
            self._row(r)
            for r in self.db.query(
                "SELECT * FROM messages WHERE conversation = ?"
                " AND (visibility != 'internal' OR agent = ?) ORDER BY ts DESC LIMIT ?",
                (conversation, agent, limit),
            )
        ]
        rows.reverse()
        return rows

    def context_view(
        self,
        conversation: str | None,
        agent: str,
        budget_chars: int = 6000,
        limit: int = 60,
        earlier: str | None = None,
        name: Callable[[str], str] | None = None,
    ) -> list[LLMMessage]:
        """The rows of one conversation rendered as LLM messages within a character budget.

        `earlier` (the summary of a long conversation's earlier part) leads the view when rows
        had to be left out; `name` labels user rows with display names.
        """
        if not conversation:
            return []
        rows = self.view_rows(conversation, agent, limit)
        # Keep the newest rows that fit the budget.
        kept: list[DialogueMessage] = []
        used = 0
        for row in reversed(rows):
            size = len(row.content)
            if row.role == "tool":
                size = min(size, HISTORY_TOOL_CHARS)
            cost = size + 20
            if used + cost > budget_chars and kept:
                break
            kept.append(row)
            used += cost
        kept.reverse()
        # Drop tool results whose call was cut off, and calls whose results were.
        call_ids = {
            call["id"]
            for row in kept
            if row.role == "assistant"
            for call in row.meta.get("tool_calls", [])
        }
        result_ids = {row.meta.get("tool_call_id") for row in kept if row.role == "tool"}
        messages: list[LLMMessage] = []
        steps: list[DialogueMessage] = []  # tool rows whose call step is rebuilt here

        def flush_steps() -> None:
            # One assistant message per model step, carrying the words said before its calls
            # where they were said (block #76); rows written before then have no step.
            groups: list[list[DialogueMessage]] = []
            for r in steps:
                last = groups[-1][0] if groups else None
                if (
                    last is not None
                    and last.reply_to == r.reply_to
                    and last.meta.get("step") == r.meta.get("step")
                ):
                    groups[-1].append(r)
                else:
                    groups.append([r])
            for group in groups:
                said = next((str(r.meta["said"]) for r in group if r.meta.get("said")), "")
                messages.append(
                    LLMMessage(
                        "assistant",
                        PERFORMANCE_TAG.sub("", said).strip() or None,
                        tuple(
                            LLMToolCall(
                                str(r.meta["tool_call_id"]),
                                str(r.meta["tool"]),
                                str(r.meta.get("arguments") or "{}"),
                            )
                            for r in group
                        ),
                    )
                )
                for r in group:
                    content = r.content
                    if len(content) > HISTORY_TOOL_CHARS:
                        content = content[:HISTORY_TOOL_CHARS] + "…"
                    messages.append(
                        LLMMessage(
                            "tool",
                            content,
                            tool_call_id=str(r.meta["tool_call_id"]),
                            name=r.meta["tool"],
                        )
                    )
            steps.clear()

        if earlier and len(kept) < len(rows):
            messages.append(
                LLMMessage("user", f"[earlier in this conversation, summarised] {earlier}")
            )
        speakers = {row.speaker for row in kept if row.role == "user"}
        for row in kept:
            if row.role == "tool" and row.meta.get("tool_call_id") not in call_ids:
                if row.meta.get("tool_call_id") and row.meta.get("tool"):
                    steps.append(row)
                continue
            flush_steps()
            if row.role == "user":
                label = name(row.speaker) if name is not None else row.speaker
                prefix = (
                    "" if len(speakers) <= 1 or row.speaker in ("owner", "user") else f"[{label}] "
                )
                messages.append(LLMMessage("user", prefix + row.content))
            elif row.role == "assistant":
                calls = tuple(
                    LLMToolCall(c["id"], c["name"], c["arguments"])
                    for c in row.meta.get("tool_calls", [])
                    if c["id"] in result_ids
                )
                # `reply`: the model's own last words, when the transcript holds more (block #76)
                content = PERFORMANCE_TAG.sub("", str(row.meta.get("reply", row.content))).strip()
                if not content and not calls:
                    continue
                messages.append(LLMMessage("assistant", content or None, calls))
            elif row.role == "tool":
                call_id = row.meta.get("tool_call_id")
                messages.append(
                    LLMMessage("tool", row.content, tool_call_id=call_id, name=row.meta.get("tool"))
                )
            else:  # internal
                messages.append(LLMMessage("user", f"[internal note] {row.content}"))
        flush_steps()
        Log.debug(f"context view: {len(messages)} messages, {used} chars")
        return messages
