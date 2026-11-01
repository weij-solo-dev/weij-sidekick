"""sidekick.agent.memory — the memory pyramid's stores: L2 facts, L1 episodes, digests

Overview
    `memory_v1.db` keeps what Bobby takes from the conversations (blocks #66 / #70): **facts**
    (L2) — one short sentence each about a contact or the household, with where it came from —,
    **episodes** (L1) — one per conversation: title, summary, follow-ups, participants — and
    **digests**, a scope's facts condensed once they no longer fit the prompt. L0 is the
    timeline itself (`dialogue.py`). `block()` renders what one speaker may see into the memory
    block a conversation's prompt carries; `search()` is the `recall` tool's keyword search.
Design
    A fact records its provenance: `scope` (whose profile — a contact id or `household`),
    `subject` (who it is about), `teller`, `channel`, `visibility` (`private`: the teller's
    only), `origin` (`explicit`: the remember tool or the dashboard; `inferred`: the memory
    writer), `category`, `valid_until`, `sources` (timeline row ids) and `episode`. Facts are
    never rewritten: a changed one is superseded (`superseded_by`, `retired_ts`) and stays as
    evidence, an expired one is retired; only a person's own `forget`, the dashboard and the
    deletion of a contact delete rows. Sensitive categories (health, money, relationships) are
    always private. Memory follows identity (invariant 23): an unnamed speaker's scope
    (`person:N`, `guest:N`) raises, so nothing is left behind when a person is befriended or
    forgotten; `move_scope` hands a scope to a contact that takes it over (the dashboard's
    `owner`), `drop_scope` deletes a deleted contact's facts and private episodes. A deleted
    episode keeps an empty `deleted` row, so the writer does not write its conversation again
    (block #76).
    The block (no model, no search — built once per conversation by the agent and frozen):
    the speaker's facts — their private ones only in a private conversation —, the
    household's, the last conversations they took part in (the newest with its summary when it
    is recent), and the follow-ups due; a scope with a digest shows the digest and the facts
    newer than it. Search is a LIKE over the query's terms, scored by how many match (a few
    thousand rows at most; FTS5 when the volume asks for it). Migration 2 moved the facts of the
    first table (`memory`) into `facts` as explicit, public facts.
Depends on
    sidekick.log, sidekick.storage, sidekick.contact (`is_person`).

See Also
--------
    AGENTS.md "Dialogue and memory", invariant 23; PLAN.md blocks "[2026-10-27 #35]",
    "[2026-10-29 #63]", "[2026-10-29 #66]", "[2026-10-29 #70]".

"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from sidekick.contact import is_person
from sidekick.log import Log
from sidekick.storage import Database

from .schemas import HOUSEHOLD, MemoryEpisode, MemoryFact

CATEGORIES = (
    "identity",
    "style",
    "preference",
    "routine",
    "date",
    "health",
    "money",
    "relationship",
    "other",
)
SENSITIVE = frozenset({"health", "money", "relationship"})
RECENT_EPISODE_S = 2 * 86400.0  # the newest conversation shows its summary when this recent
EPISODES_IN_BLOCK = 3
_TERM = re.compile(r"[\s,.;:!?，。；：！？、…「」『』()（）\[\]\"']+")

MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS memory (
        id TEXT PRIMARY KEY, ts REAL NOT NULL, scope TEXT NOT NULL, kind TEXT NOT NULL,
        text TEXT NOT NULL, source_id TEXT
    );
    CREATE INDEX IF NOT EXISTS memory_scope ON memory(scope, ts);
    """,
    """
    CREATE TABLE IF NOT EXISTS facts (
        id TEXT PRIMARY KEY, ts REAL NOT NULL, updated_ts REAL NOT NULL,
        scope TEXT NOT NULL, subject TEXT, teller TEXT, channel TEXT,
        visibility TEXT NOT NULL DEFAULT 'public', origin TEXT NOT NULL DEFAULT 'explicit',
        category TEXT NOT NULL DEFAULT 'other', text TEXT NOT NULL, valid_until TEXT,
        sources TEXT NOT NULL DEFAULT '[]', episode TEXT,
        superseded_by TEXT, retired_ts REAL
    );
    CREATE INDEX IF NOT EXISTS facts_scope ON facts(scope, retired_ts, ts);
    CREATE TABLE IF NOT EXISTS episodes (
        id TEXT PRIMARY KEY, conversation TEXT NOT NULL UNIQUE, channel TEXT NOT NULL,
        ts_start REAL NOT NULL, ts_end REAL NOT NULL, participants TEXT NOT NULL DEFAULT '[]',
        visibility TEXT NOT NULL DEFAULT 'public', private_to TEXT,
        title TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
        followups TEXT NOT NULL DEFAULT '[]', rows INTEGER NOT NULL DEFAULT 0,
        user_turns INTEGER NOT NULL DEFAULT 0, upto_ts REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'ok', attempts INTEGER NOT NULL DEFAULT 1, error TEXT,
        model TEXT, written_ts REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS episodes_end ON episodes(ts_end);
    CREATE TABLE IF NOT EXISTS digests (
        scope TEXT PRIMARY KEY, text TEXT NOT NULL, ts REAL NOT NULL, facts INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    INSERT OR IGNORE INTO facts (id, ts, updated_ts, scope, subject, visibility, origin,
                                 category, text, sources)
        SELECT id, ts, ts, scope, scope, 'public', 'explicit', 'other', text,
               CASE WHEN source_id IS NULL THEN '[]' ELSE json_array(source_id) END
        FROM memory WHERE kind = 'fact';
    DROP TABLE memory;
    """,
]


def terms(query: str) -> list[str]:
    """The search terms of a query: words split on spaces and punctuation, longest first."""
    words = [w for w in _TERM.split(query.strip().lower()) if w]
    return sorted(dict.fromkeys(words), key=len, reverse=True)[:6]


# Deleting an episode empties it and marks it, so the writer does not write it again (block #76).
_EPISODE_TOMBSTONE = (
    "UPDATE episodes SET status = 'deleted', title = '', summary = '', followups = '[]'"
)


class MemoryStore:
    """Facts, episodes and digests."""

    def __init__(self, path: Path) -> None:
        self.db = Database(path, MIGRATIONS)

    # ------------------------------------------------------------------- rows

    @staticmethod
    def _fact(row: Any) -> MemoryFact:
        return MemoryFact(
            scope=row["scope"],
            text=row["text"],
            id=row["id"],
            ts=row["ts"],
            subject=row["subject"],
            teller=row["teller"],
            channel=row["channel"],
            visibility=row["visibility"],
            origin=row["origin"],
            category=row["category"],
            valid_until=row["valid_until"],
            sources=tuple(json.loads(row["sources"] or "[]")),
            episode=row["episode"],
            updated_ts=row["updated_ts"],
            superseded_by=row["superseded_by"],
            retired_ts=row["retired_ts"],
        )

    @staticmethod
    def _episode(row: Any) -> MemoryEpisode:
        return MemoryEpisode(
            conversation=row["conversation"],
            channel=row["channel"],
            ts_start=row["ts_start"],
            ts_end=row["ts_end"],
            title=row["title"],
            summary=row["summary"],
            participants=tuple(json.loads(row["participants"] or "[]")),
            visibility=row["visibility"],
            private_to=row["private_to"],
            followups=tuple(json.loads(row["followups"] or "[]")),
            rows=row["rows"],
            user_turns=row["user_turns"],
            upto_ts=row["upto_ts"],
            status=row["status"],
            attempts=row["attempts"],
            error=row["error"],
            model=row["model"],
            id=row["id"],
            written_ts=row["written_ts"],
        )

    # ------------------------------------------------------------------ facts

    def remember(
        self,
        scope: str,
        text: str,
        source_id: str | None = None,
        *,
        subject: str | None = None,
        teller: str | None = None,
        channel: str | None = None,
        visibility: str = "public",
        origin: str = "explicit",
        category: str = "other",
        valid_until: str | None = None,
        episode: str | None = None,
        sources: Sequence[str] = (),
    ) -> MemoryFact:
        """Store a fact (an unnamed speaker's scope raises `ValueError`).

        The same text already active in the scope is returned instead of a second copy; a
        sensitive category is always private.
        """
        if is_person(scope):
            raise ValueError(f"{scope} is not named yet: unnamed people keep no memory")
        text = text.strip()
        existing = self.db.query(
            "SELECT * FROM facts WHERE scope = ? AND text = ? AND retired_ts IS NULL",
            (scope, text),
        )
        if existing:
            return self._fact(existing[0])
        category = category if category in CATEGORIES else "other"
        fact = MemoryFact(
            scope,
            text,
            subject=subject or scope,
            teller=teller,
            channel=channel,
            visibility="private" if visibility == "private" or category in SENSITIVE else "public",
            origin="inferred" if origin == "inferred" else "explicit",
            category=category,
            valid_until=valid_until,
            sources=tuple(dict.fromkeys([*([source_id] if source_id else []), *sources])),
            episode=episode,
        )
        self._insert(fact)
        Log.info(f"remembered for {scope} ({fact.origin}, {fact.category}): {text[:60]!r}")
        return fact

    def _insert(self, fact: MemoryFact, conn: Any = None) -> None:
        sql = (
            "INSERT INTO facts (id, ts, updated_ts, scope, subject, teller, channel, visibility,"
            " origin, category, text, valid_until, sources, episode)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        values = (
            fact.id,
            fact.ts,
            fact.updated_ts or fact.ts,
            fact.scope,
            fact.subject,
            fact.teller,
            fact.channel,
            fact.visibility,
            fact.origin,
            fact.category,
            fact.text,
            fact.valid_until,
            json.dumps(list(fact.sources)),
            fact.episode,
        )
        if conn is not None:
            conn.execute(sql, values)
        else:
            self.db.execute(sql, values)

    def supersede(self, old_id: str, new: MemoryFact) -> MemoryFact:
        """Store `new` and retire `old_id` in its favour (one transaction)."""
        if is_person(new.scope):
            raise ValueError(f"{new.scope} is not named yet: unnamed people keep no memory")
        with self.db.transaction() as conn:
            self._insert(new, conn)
            conn.execute(
                "UPDATE facts SET superseded_by = ?, retired_ts = ? WHERE id = ? AND retired_ts IS NULL",
                (new.id, time.time(), old_id),
            )
        Log.info(f"memory: {old_id[:8]} superseded by {new.text[:60]!r} ({new.scope})")
        return new

    def retire(self, fact_id: str, reason: str = "expired") -> bool:
        """Retire one fact (kept as evidence)."""
        return bool(
            self.db.execute(
                "UPDATE facts SET superseded_by = ?, retired_ts = ? WHERE id = ? AND retired_ts IS NULL",
                (reason, time.time(), fact_id),
            )
        )

    def expire(self, today: str) -> int:
        """Retire dated facts whose day has passed (`valid_until < today`); how many."""
        expired = self.db.execute(
            "UPDATE facts SET superseded_by = 'expired', retired_ts = ?"
            " WHERE retired_ts IS NULL AND valid_until IS NOT NULL AND valid_until < ?",
            (time.time(), today),
        )
        if expired:
            Log.info(f"memory: {expired} dated fact(s) expired")
        return expired

    def forget(
        self, fact_id: str | None = None, text: str | None = None, scope: str | None = None
    ) -> int:
        """Delete by id, or by substring within one scope; returns how many went."""
        if fact_id:
            return self.db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        if text and scope:
            return self.db.execute(
                "DELETE FROM facts WHERE scope = ? AND text LIKE ?", (scope, f"%{text}%")
            )
        return 0

    def move_scope(self, old: str, new: str) -> int:
        """Hand every fact of one scope to another (a contact took it over); how many moved."""
        if old == new:
            return 0
        with self.db.transaction() as conn:
            moved = int(
                conn.execute("UPDATE facts SET scope = ? WHERE scope = ?", (new, old)).rowcount
            )
            conn.execute("UPDATE facts SET subject = ? WHERE subject = ?", (new, old))
            conn.execute("UPDATE facts SET teller = ? WHERE teller = ?", (new, old))
            conn.execute("UPDATE episodes SET private_to = ? WHERE private_to = ?", (new, old))
        if moved:
            Log.info(f"memory: {moved} fact(s) moved from {old} to {new}")
        return moved

    def drop_scope(self, scope: str) -> int:
        """Delete a scope's facts and the private episodes kept for it (its contact went)."""
        with self.db.transaction() as conn:
            dropped = int(conn.execute("DELETE FROM facts WHERE scope = ?", (scope,)).rowcount)
            conn.execute(f"{_EPISODE_TOMBSTONE} WHERE private_to = ?", (scope,))
            conn.execute("DELETE FROM digests WHERE scope = ?", (scope,))
        if dropped:
            Log.info(f"memory: {dropped} fact(s) of {scope} deleted")
        return dropped

    def recall(
        self,
        scopes: list[str],
        query: str | None = None,
        limit: int = 20,
        include_private: bool = True,
    ) -> list[MemoryFact]:
        """Active facts in the given scopes, matching `query` when given, newest first."""
        if not scopes:
            return []
        marks = ", ".join("?" for _ in scopes)
        sql = f"SELECT * FROM facts WHERE scope IN ({marks}) AND retired_ts IS NULL"
        params: list[Any] = list(scopes)
        if not include_private:
            sql += " AND visibility = 'public'"
        if query:
            sql += " AND text LIKE ?"
            params.append(f"%{query}%")
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        return [self._fact(r) for r in self.db.query(sql, tuple(params))]

    def facts(
        self, scope: str | None = None, include_retired: bool = False, limit: int = 500
    ) -> list[MemoryFact]:
        """Facts of one scope (or all), newest first."""
        sql = "SELECT * FROM facts WHERE 1 = 1"
        params: list[Any] = []
        if scope is not None:
            sql += " AND scope = ?"
            params.append(scope)
        if not include_retired:
            sql += " AND retired_ts IS NULL"
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        return [self._fact(r) for r in self.db.query(sql, tuple(params))]

    def fact(self, fact_id: str) -> MemoryFact | None:
        """One fact by id."""
        rows = self.db.query("SELECT * FROM facts WHERE id = ?", (fact_id,))
        return self._fact(rows[0]) if rows else None

    def all(self, limit: int = 200) -> list[MemoryFact]:
        """Every fact, active and retired, newest first (dashboard)."""
        return self.facts(include_retired=True, limit=limit)

    def count(self) -> int:
        """Active facts."""
        return int(
            self.db.query("SELECT COUNT(*) AS n FROM facts WHERE retired_ts IS NULL")[0]["n"]
        )

    def scopes(self) -> list[str]:
        """Scopes that hold active facts."""
        rows = self.db.query("SELECT DISTINCT scope FROM facts WHERE retired_ts IS NULL")
        return sorted(r["scope"] for r in rows)

    # --------------------------------------------------------------- episodes

    def save_episode(self, episode: MemoryEpisode) -> MemoryEpisode:
        """Insert or replace the episode of a conversation (one row per conversation)."""
        existing = self.episode_for(episode.conversation)
        if existing is not None:
            episode = replace(episode, id=existing.id)
        self.db.execute(
            "INSERT OR REPLACE INTO episodes (id, conversation, channel, ts_start, ts_end,"
            " participants, visibility, private_to, title, summary, followups, rows, user_turns,"
            " upto_ts, status, attempts, error, model, written_ts)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                episode.id,
                episode.conversation,
                episode.channel,
                episode.ts_start,
                episode.ts_end,
                json.dumps(list(episode.participants), ensure_ascii=False),
                episode.visibility,
                episode.private_to,
                episode.title,
                episode.summary,
                json.dumps(list(episode.followups), ensure_ascii=False),
                episode.rows,
                episode.user_turns,
                episode.upto_ts,
                episode.status,
                episode.attempts,
                episode.error,
                episode.model,
                episode.written_ts,
            ),
        )
        return episode

    def episode(self, episode_id: str) -> MemoryEpisode | None:
        """One episode by id."""
        rows = self.db.query("SELECT * FROM episodes WHERE id = ?", (episode_id,))
        return self._episode(rows[0]) if rows else None

    def episode_for(self, conversation: str) -> MemoryEpisode | None:
        """The episode written for a conversation, if any."""
        rows = self.db.query("SELECT * FROM episodes WHERE conversation = ?", (conversation,))
        return self._episode(rows[0]) if rows else None

    def episodes(
        self, since: float | None = None, limit: int = 200, include_failed: bool = False
    ) -> list[MemoryEpisode]:
        """Episodes, newest first."""
        sql = "SELECT * FROM episodes WHERE 1 = 1"
        params: list[Any] = []
        if since is not None:
            sql += " AND ts_end >= ?"
            params.append(since)
        sql += " AND status != 'deleted'" if include_failed else " AND status = 'ok'"
        sql += " ORDER BY ts_end DESC LIMIT ?"
        params.append(limit)
        return [self._episode(r) for r in self.db.query(sql, tuple(params))]

    def episode_count(self) -> int:
        """Written episodes."""
        return int(self.db.query("SELECT COUNT(*) AS n FROM episodes WHERE status = 'ok'")[0]["n"])

    def delete_episode(self, episode_id: str) -> bool:
        """Delete an episode (the dashboard); its facts stay.

        Its words go, the row stays as an empty `deleted` marker: the memory writer writes a
        conversation that has no episode, and wrote a deleted one again within minutes (block
        #76). A conversation that goes on afterwards is written afresh.
        """
        return bool(
            self.db.execute(
                f"{_EPISODE_TOMBSTONE} WHERE id = ? AND status != 'deleted'", (episode_id,)
            )
        )

    @staticmethod
    def visible(episode: MemoryEpisode, speaker: str, private: bool) -> bool:
        """Whether `speaker` may be shown an episode (private ones: their own, privately)."""
        if episode.visibility == "private":
            return private and episode.private_to == speaker
        return True

    def episodes_with(
        self, speaker: str, private: bool, limit: int = EPISODES_IN_BLOCK
    ) -> list[MemoryEpisode]:
        """The newest written episodes `speaker` took part in and may be shown."""
        rows = self.db.query(
            "SELECT * FROM episodes WHERE status = 'ok' AND participants LIKE ?"
            " ORDER BY ts_end DESC LIMIT ?",
            (f'%"{speaker}"%', limit * 4),
        )
        out = [e for e in map(self._episode, rows) if self.visible(e, speaker, private)]
        return out[:limit]

    def followups_due(
        self, speaker: str, today: str, private: bool, horizon: str | None = None
    ) -> list[tuple[MemoryEpisode, dict[str, str]]]:
        """Follow-ups for `speaker` (or the household) due from yesterday to `horizon`."""
        horizon = horizon or today
        since = time.time() - 21 * 86400.0
        rows = self.db.query(
            "SELECT * FROM episodes WHERE status = 'ok' AND followups != '[]' AND ts_end >= ?"
            " ORDER BY ts_end DESC LIMIT 50",
            (since,),
        )
        yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400.0))
        out: list[tuple[MemoryEpisode, dict[str, str]]] = []
        for episode in map(self._episode, rows):
            if not self.visible(episode, speaker, private):
                continue
            for item in episode.followups:
                due = str(item.get("due") or "")
                who = str(item.get("who") or "")
                if who not in (speaker, HOUSEHOLD, "") or not due:
                    continue
                if yesterday <= due <= horizon:
                    out.append((episode, item))
        return out

    # ---------------------------------------------------------------- digests

    def digest(self, scope: str) -> tuple[str, float, int] | None:
        """A scope's digest: text, when it was written, how many facts it covered."""
        rows = self.db.query("SELECT * FROM digests WHERE scope = ?", (scope,))
        return (rows[0]["text"], rows[0]["ts"], rows[0]["facts"]) if rows else None

    def save_digest(self, scope: str, text: str, facts: int) -> None:
        """Store a scope's digest."""
        self.db.execute(
            "INSERT OR REPLACE INTO digests (scope, text, ts, facts) VALUES (?, ?, ?, ?)",
            (scope, text.strip(), time.time(), facts),
        )

    def digests(self) -> dict[str, str]:
        """Every digest by scope."""
        return {r["scope"]: r["text"] for r in self.db.query("SELECT * FROM digests")}

    # ------------------------------------------------------------------- meta

    def meta(self, key: str) -> str | None:
        """A small persisted value (the writer's bookkeeping)."""
        rows = self.db.query("SELECT value FROM meta WHERE key = ?", (key,))
        return str(rows[0]["value"]) if rows else None

    def set_meta(self, key: str, value: str) -> None:
        """Store a small value."""
        self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    # ------------------------------------------------------------------ block

    @staticmethod
    def _rank(fact: MemoryFact) -> tuple[int, int, float]:
        order = CATEGORIES.index(fact.category) if fact.category in CATEGORIES else len(CATEGORIES)
        return (0 if fact.origin == "explicit" else 1, order, -fact.ts)

    def _scope_lines(self, scope: str, private: bool, budget: int) -> list[str]:
        facts = [f for f in self.facts(scope, limit=300) if private or f.visibility == "public"]
        digest = self.digest(scope)
        lines: list[str] = []
        used = 0
        if digest is not None:
            lines.append(digest[0])
            used += len(digest[0])
            facts = [f for f in facts if f.ts > digest[1] or f.visibility == "private"]
        for fact in sorted(facts, key=self._rank):
            line = f"- {fact.text}" + (" (private)" if fact.visibility == "private" else "")
            if used + len(line) > budget and lines:
                break
            lines.append(line)
            used += len(line)
        return lines

    def block(
        self,
        speaker: str,
        *,
        private: bool = False,
        today: str | None = None,
        name: Callable[[str], str] | None = None,
        budget: int = 1000,
    ) -> str:
        """The memory block of a conversation for `speaker` (rendered once and frozen).

        `private` is a one-to-one chat with the speaker (their private facts and episodes
        may show); an unnamed speaker gets the household's facts only (invariant 23).
        """
        today = today or time.strftime("%Y-%m-%d")
        label = name or (lambda who: who)
        named = speaker != HOUSEHOLD and not is_person(speaker)
        parts: list[str] = []
        if named:
            mine = self._scope_lines(speaker, private, budget * 2 // 5)
            if mine:
                parts.append(
                    f"About {label(speaker)}, who is talking to you now:\n" + "\n".join(mine)
                )
        household = self._scope_lines(HOUSEHOLD, False, budget * 3 // 10)
        if household:
            parts.append("About the household:\n" + "\n".join(household))
        if named:
            lines = []
            for index, episode in enumerate(self.episodes_with(speaker, private)):
                when = time.strftime("%m-%d %H:%M", time.localtime(episode.ts_start))
                line = f"- {when} {episode.title}"
                if index == 0 and time.time() - episode.ts_end < RECENT_EPISODE_S:
                    line += f": {episode.summary}"
                lines.append(line)
            if lines:
                parts.append(f"Earlier conversations with {label(speaker)}:\n" + "\n".join(lines))
            horizon = time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400.0))
            due = [
                f"- {item.get('due')}: {item.get('text')}"
                for _, item in self.followups_due(speaker, today, private, horizon)
            ]
            if due:
                parts.append(
                    "Follow-ups due (ask how it went when it fits):\n" + "\n".join(due[:4])
                )
        if not parts:
            return ""
        return (
            "What you remember from earlier conversations (it may be out of date; never claim "
            "more than this):\n" + "\n\n".join(parts)
        )

    # ----------------------------------------------------------------- search

    def search(
        self,
        speaker: str,
        query: str,
        *,
        private: bool = False,
        others: Iterable[str] = (),
        limit: int = 8,
    ) -> tuple[list[MemoryFact], list[MemoryEpisode]]:
        """The `recall` search: facts and episodes matching the query's terms, best first.

        Visible facts: the speaker's own (private ones in a private chat), the household's, and
        the open, non-sensitive facts of `others` (the family members — what was said openly is
        shared, block #68). Visible episodes: open ones, and the speaker's private ones in a
        private chat. An empty query returns the newest.
        """
        words = terms(query)
        scopes = [HOUSEHOLD, *([speaker] if not is_person(speaker) else []), *others]
        marks = ", ".join("?" for _ in scopes)
        rows = self.db.query(
            f"SELECT * FROM facts WHERE retired_ts IS NULL AND scope IN ({marks})"
            " ORDER BY ts DESC LIMIT 2000",
            tuple(scopes),
        )
        facts: list[tuple[int, MemoryFact]] = []
        for fact in map(self._fact, rows):
            own = fact.scope in (speaker, HOUSEHOLD)
            if fact.visibility == "private" and not (private and fact.scope == speaker):
                continue
            if not own and (fact.category in SENSITIVE or fact.visibility != "public"):
                continue
            score = sum(1 for w in words if w in fact.text.lower()) if words else 1
            if score:
                facts.append((score, fact))
        facts.sort(key=lambda item: (-item[0], -item[1].ts))
        episodes: list[tuple[int, MemoryEpisode]] = []
        for episode in self.episodes(limit=500):
            if not self.visible(episode, speaker, private):
                continue
            haystack = " ".join(
                [episode.title, episode.summary, *(str(f.get("text")) for f in episode.followups)]
            ).lower()
            score = sum(1 for w in words if w in haystack) if words else 1
            if score:
                episodes.append((score, episode))
        episodes.sort(key=lambda item: (-item[0], -item[1].ts_end))
        return [f for _, f in facts[:limit]], [e for _, e in episodes[: max(3, limit // 2)]]
