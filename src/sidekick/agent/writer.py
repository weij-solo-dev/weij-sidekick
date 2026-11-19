"""sidekick.agent.writer — the memory writer: conversations into episodes (L1) and facts (L2)

Overview
    `MemoryWriter` runs beside the agent as one background task (block #70). When a
    conversation has closed — no row for its gap (`DialogueStore.gap_for`) — it reads the
    conversation once and writes its episode (title, summary, follow-ups) and the facts worth
    keeping, with one call on the `smart` slot traced as `memory.writer`; a long conversation is
    also written every `ROLLING_TURNS` user turns, so its earlier part has a summary while it
    goes on. At start it catches up on the last `CATCH_UP_DAYS`. Once a night (at
    `nightly_hour`) it retires dated facts whose day has passed, writes a digest for a scope
    whose facts outgrew the prompt budget and merges duplicates in a large scope.
Design
    Never on a turn's hot path (block #68: memory must not slow the first word): it writes only
    closed conversations (or a long one between its turns), steps aside while a turn is in
    flight, and the turn's memory block comes from SQLite, never from the writer. The model
    proposes; the code decides what is kept (blocks #66 / #68): facts only from named
    participants who spoke, about themselves, another person or the household; household facts
    only from an open conversation; a private chat's facts belong to its teller and stay
    private; health, money and relationships only about the teller and always private; a fact
    about another person stays in the teller's scope; a change supersedes the old fact, never
    deletes it — a person may correct what is known about them, and an explicit household fact
    is changed only by its own teller; at most `MAX_FACTS` per
    conversation; a conversation with unnamed people only yields an episode about "a visitor".
    Not written: conversations without a user turn (a reminder nobody answered), the
    dashboard's test card (`EXCLUDED_CHANNELS`), job and heartbeat turns and subagent steps
    (they belong to no conversation). A failed write is kept as a failed episode and retried up
    to `MAX_ATTEMPTS` times. The nightly merge refuses a result that would retire more than a
    quarter of a scope's facts. Everything it does lands in `recent` for the Live page.
Depends on
    sidekick.log, sidekick.llm.

See Also
--------
    AGENTS.md "Dialogue and memory", invariant 23; PLAN.md blocks "[2026-10-29 #65]",
    "[2026-10-29 #66]", "[2026-10-29 #70]".

"""

from __future__ import annotations

import asyncio
import collections
import datetime
import json
import re
import time
from collections.abc import Callable
from typing import Any

from sidekick.llm import LLMInferOptions, LLMMessage, LLMSession
from sidekick.log import Log

from .dialogue import PERFORMANCE_TAG, DialogueStore, key_of
from .memory import CATEGORIES, SENSITIVE, MemoryStore
from .schemas import HOUSEHOLD, DialogueMessage, MemoryEpisode, MemoryFact

EXCLUDED_CHANNELS = frozenset({"dashboard"})  # the Agent → Test card (owner, block #68)
ROLLING_TURNS = 12  # a long conversation is written every this many user turns
CATCH_UP_DAYS = 7
MAX_FACTS = 8
MAX_ATTEMPTS = 3
TRANSCRIPT_CHARS = 8000
POLL_S = 30.0
START_DELAY_S = 20.0
DIGEST_BUDGET = 400  # a scope's facts longer than this get a digest (the block's share)
MERGE_MIN_FACTS = 30
MERGE_MAX_SHARE = 0.25
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LANGUAGE_NAMES = {
    "yue": "colloquial written Cantonese in Traditional Chinese characters (係 / 唔 / 嘅)",
    "zh": "Mandarin Chinese in Simplified characters",
    "en": "English",
}

WRITER_ROLE = """You keep the long-term memory of Banana, a small robot butler living with one household.
You read one finished conversation and decide what is worth remembering. Write the title, the
summary, the follow-ups and the facts in {language}; never mention the room or the app in them.

Return one JSON object and nothing else:
{{"title": "...", "summary": "...", "followups": [...], "facts": [...]}}

title: at most 40 characters — what the conversation was about.
summary: at most 300 characters — what happened and what was agreed, naming the people (the
participants are listed below; an unnamed person is "{visitor}"). Plain facts, no judgement.
Leave health, money and relationship details out of the summary (they may only be facts).
followups: a question Banana could ask after a dated event the conversation mentions ("睇牙順唔順利？"
after the dentist), due on the day of the event or the day after:
{{"who": "<participant id or household>", "text": "<the question>", "due": "YYYY-MM-DD"}}.
Not reminders — those are scheduled separately. Usually none.
facts: what will still be useful in weeks or months, said by a named participant — who people
are and how they are related, likes and dislikes, routines and schedules, important dates,
health, how they like Banana to talk. Each one:
{{"op": "add" or "supersede", "replaces": "<known fact id>" or null, "about": "<participant id>" or
"household" or "<name of someone else>", "teller": "<id of the participant who said it>",
"category": "identity|style|preference|routine|date|health|money|relationship|other",
"text": "<one short sentence in the third person, with the person's name>", "valid_until": "YYYY-MM-DD" or null}}
Rules for facts:
- Only what the people said or clearly showed; never what Banana said or guessed.
- One fact per sentence, third person, with the name ("爸爸鍾意飲凍檸茶"), never 我 / 你 / I / you;
  each must make sense on its own months later — skip vague ones.
- Something said about another person keeps who said it ("爸爸話媽媽鍾意榴槤"); a household
  fact needs no teller in its text.
- Health, money and relationships only when people said them about themselves — then they
  are worth keeping (they stay private): "爸爸膝頭哥痛，呢排唔想行山".
- Requests and reminders are not facts ("提我訂位" belongs to the schedule).
- If a known fact (listed below) already says it, leave it out; if it changed, "supersede" it.
- Skip greetings, small talk, jokes, questions Banana answered, one-off requests already done,
  and anything about unnamed visitors.
- Dates: work them out with the calendar below ("下個禮拜三" is Wednesday of next week).
  Birthdays and anniversaries come back every year: day and month, no year, no valid_until.
  Something that ends (an appointment, a trip) gets valid_until.
- Usually zero to three facts; never more than eight.
Today is {today} ({weekday}).
Calendar (weeks run Monday to Sunday):
{calendar}"""

DIGEST_ROLE = """You condense what a household robot remembers about {who} into one short profile,
in {language}, at most {limit} characters, third person, the most useful things first (who they
are, how to talk with them, likes, routines, dates). Use only the facts given; return the text only."""

MERGE_ROLE = """These are facts a household robot remembers about {who}. Find facts that repeat
another fact or that a newer fact contradicts. Return JSON only:
{{"retire": [{{"id": "<fact id to retire>", "because": "<id of the fact that covers it>"}}]}}
Retire nothing when in doubt."""


def calendar(now: float) -> str:
    """The current week, the next and the one after, day by day (relative dates in speech)."""
    today = datetime.date.fromtimestamp(now)
    monday = today - datetime.timedelta(days=today.weekday())
    lines = []
    for label, offset in (("this week", 0), ("next week", 7), ("the week after", 14)):
        days = [monday + datetime.timedelta(days=offset + i) for i in range(7)]
        lines.append(
            f"{label}: "
            + " ".join(f"{d:%a} {d:%m-%d}{' (today)' if d == today else ''}" for d in days)
        )
    return "\n".join(lines)


def parse_json(text: str | None) -> dict[str, Any] | None:
    """The first JSON object in a model's answer (code fences and chatter tolerated)."""
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


class MemoryWriter:
    """Writes episodes and facts from closed conversations; one background task."""

    def __init__(
        self,
        memory: MemoryStore,
        dialogue: DialogueStore,
        llm: LLMSession,
        *,
        slot: str = "smart",
        name: Callable[[str], str] | None = None,
        named: Callable[[str], bool] | None = None,
        busy: Callable[[], bool] | None = None,
        language: str = "yue",
        enabled: bool = True,
        nightly_hour: int = 3,
    ) -> None:
        self.memory = memory
        self.dialogue = dialogue
        self.llm = llm
        self.slot = slot
        self.name = name or (lambda who: who)
        self.named = named or (lambda who: False)
        self.busy = busy or (lambda: False)
        self.language = language
        self.enabled = enabled
        self.nightly_hour = nightly_hour
        self.state = "idle"
        self.waiting = 0
        self.written = 0
        self.last_run_ts: float | None = None
        self.last_error: str | None = None
        self.recent: collections.deque[dict[str, Any]] = collections.deque(maxlen=100)
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Start the background loop on the running event loop."""
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._loop(), name="memory-writer")

    async def stop(self) -> None:
        """Stop the loop (a write in progress is abandoned; it is retried next start)."""
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        await asyncio.sleep(START_DELAY_S)
        while True:
            try:
                if self.enabled:
                    await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = repr(exc)[:300]
                Log.error(f"memory writer: {exc!r}")
            await asyncio.sleep(POLL_S)

    def _note(self, text: str, level: str = "info") -> None:
        self.recent.append({"ts": time.time(), "module": "memory", "text": text, "level": level})

    # ------------------------------------------------------------------ what

    def due(self, now: float | None = None, include_open: bool = False) -> list[dict[str, Any]]:
        """Conversations to write now: closed and not written, failed and retryable, or long."""
        now = time.time() if now is None else now
        out = []
        for info in self.dialogue.conversations(now - CATCH_UP_DAYS * 86400.0):
            if info["channel"] in EXCLUDED_CHANNELS or not info["user_turns"]:
                continue
            closed = now - info["end"] > self.dialogue.gap_for(key_of(info["conversation"]))
            episode = self.memory.episode_for(info["conversation"])
            if episode is not None and episode.status == "failed":
                if episode.attempts < MAX_ATTEMPTS and (closed or include_open):
                    out.append(info)
                continue
            if episode is not None and episode.upto_ts >= info["end"]:
                continue
            if closed or include_open:
                out.append(info)
            elif self._turns_since(info, episode) >= ROLLING_TURNS:
                out.append(info)
        return out

    def _turns_since(self, info: dict[str, Any], episode: MemoryEpisode | None) -> int:
        if episode is None:
            return int(info["user_turns"])
        rows = self.dialogue.conversation_rows(info["conversation"])
        return sum(1 for r in rows if r.role == "user" and r.ts > episode.upto_ts)

    async def tick(self, now: float | None = None, include_open: bool = False) -> int:
        """Write what is due (one conversation at a time), then the nightly pass when due."""
        async with self._lock:
            due = self.due(now, include_open)
            self.waiting = len(due)
            written = 0
            for info in due:
                if self.busy() and not include_open:
                    break  # a turn is in flight: never compete with it
                await self.write(info, now)
                written += 1
                self.waiting -= 1
            await self._maybe_nightly(now)
            return written

    # ---------------------------------------------------------------- writing

    def _transcript(
        self, rows: list[DialogueMessage], labels: dict[str, str], earlier: str | None
    ) -> str:
        lines: list[str] = []
        for row in rows:
            at = time.strftime("%H:%M", time.localtime(row.ts))
            if row.role == "user":
                lines.append(f"[{at}] {labels.get(row.speaker, row.speaker)}: {row.content}")
            elif row.role == "assistant":
                text = PERFORMANCE_TAG.sub("", row.content).strip()
                own = " (on its own initiative)" if row.meta.get("delivery") else ""
                lines.append(f"[{at}] Banana{own}: {text}")
            elif row.role == "tool" and row.meta.get("tool"):
                arguments = str(row.meta.get("arguments") or "")[:100]
                lines.append(
                    f"[{at}] (Banana used {row.meta['tool']} {arguments} → "
                    f"{'ok' if row.meta.get('ok') else 'failed'})"
                )
        text = "\n".join(lines)
        if len(text) > TRANSCRIPT_CHARS:
            text = "…\n" + text[-TRANSCRIPT_CHARS:]
            if earlier:
                text = f"[earlier in this conversation, summarised] {earlier}\n" + text
        return text

    async def write(self, info: dict[str, Any], now: float | None = None) -> MemoryEpisode | None:
        """Write one conversation's episode and facts; a failure is kept as a failed episode."""
        conversation = str(info["conversation"])
        previous = self.memory.episode_for(conversation)
        rows = self.dialogue.conversation_rows(conversation)
        users = [r for r in rows if r.role == "user"]
        if not users:
            return None
        self.state = "writing"
        started = time.time()
        participants = list(dict.fromkeys(r.speaker for r in users))
        private = any(r.visibility == "private" for r in users)
        private_to = users[0].speaker if private else None
        named = [p for p in participants if self.named(p)]
        labels: dict[str, str] = {}
        visitors = 0
        for who in participants:
            if who in named:
                labels[who] = self.name(who)
            else:
                visitors += 1
                labels[who] = f"visitor {visitors}"
        known = {
            f.id[:8]: f
            for scope in [*named, *([] if private else [HOUSEHOLD])]
            for f in self.memory.facts(scope, limit=80)
            if (not private and f.visibility == "public") or f.scope == private_to
        }
        today = time.strftime("%Y-%m-%d")
        visitor = {"yue": "一位訪客", "zh": "一位访客"}.get(self.language, "a visitor")
        system = WRITER_ROLE.format(
            language=LANGUAGE_NAMES.get(self.language, self.language),
            visitor=visitor,
            today=today,
            weekday=time.strftime("%A"),
            calendar=calendar(time.time()),
        )
        where = (
            f"a private chat with {labels[private_to]}"
            if private and private_to
            else "spoken with Banana in person"
            if info["channel"] == "voice"
            else f"a {info['channel']} group chat"
        )
        people = "\n".join(
            f"- {who}: {labels[who]}" if who in named else f"- {labels[who]} (unnamed)"
            for who in participants
        )
        facts_text = (
            "\n".join(
                f"- {short} | {f.subject or f.scope} | {f.category} | {f.text}"
                for short, f in known.items()
            )
            or "(none)"
        )
        user = (
            f"Conversation ({where}), "
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(rows[0].ts))} – "
            f"{time.strftime('%H:%M', time.localtime(rows[-1].ts))}.\n"
            f"Participants:\n{people}\n\nKnown facts (id | about | category | text):\n{facts_text}\n\n"
            f"Transcript:\n{self._transcript(rows, labels, previous.summary if previous else None)}"
        )
        result = await self.llm.infer(
            self.slot,
            [LLMMessage("system", system), LLMMessage("user", user)],
            LLMInferOptions(max_tokens=3000, temperature=0.3),
            task="memory.writer",
        )
        data = parse_json(result.output) if result.success else None
        base = MemoryEpisode(
            conversation=conversation,
            channel=str(info["channel"]),
            ts_start=rows[0].ts,
            ts_end=rows[-1].ts,
            title=previous.title if previous else "",
            summary=previous.summary if previous else "",
            participants=tuple(participants),
            visibility="private" if private else "public",
            private_to=private_to,
            rows=len(rows),
            user_turns=len(users),
            upto_ts=rows[-1].ts,
            model=result.model or None,
            id=previous.id if previous else MemoryEpisode("", "", 0, 0, "", "").id,
        )
        if data is None:
            error = result.error_message or "no JSON in the answer"
            attempts = (previous.attempts + 1) if previous and previous.status == "failed" else 1
            failed = MemoryEpisode(
                **{**_fields(base), "status": "failed", "attempts": attempts, "error": error[:300]}
            )
            if previous is None or previous.status == "failed":
                self.memory.save_episode(failed)
            self.last_error = error[:300]
            self.state = "idle"
            self._note(f"could not write {conversation}: {error[:80]}", "warn")
            Log.warning(f"memory writer: {conversation} failed ({error[:120]})")
            return None
        followups = []
        for item in data.get("followups") or []:
            if not isinstance(item, dict):
                continue
            who = str(item.get("who") or "")
            due = str(item.get("due") or "")
            text = _clean(item.get("text"), 80)
            if text and _DATE.match(due) and due >= today and who in (*named, HOUSEHOLD):
                followups.append({"who": who, "text": text, "due": due})
        episode = MemoryEpisode(
            **{
                **_fields(base),
                "title": _clean(data.get("title"), 60) or base.title or "(untitled)",
                "summary": _clean(data.get("summary"), 500) or base.summary,
                "followups": tuple(followups[:4]),
                "status": "ok",
                "attempts": 1,
                "error": None,
            }
        )
        sources: dict[str, list[str]] = {}
        for row in users:
            sources.setdefault(row.speaker, []).append(row.id)
        kept = self._apply(
            data.get("facts") or [],
            tellers=set(named),
            private=private,
            private_to=private_to,
            channel=episode.channel,
            known=known,
            sources=sources,
            episode=episode.id,
        )
        self.memory.save_episode(episode)
        self.written += 1
        self.last_run_ts = time.time()
        self.last_error = None
        self.state = "idle"
        added = sum(1 for _, old in kept if old is None)
        changed = len(kept) - added
        self._note(
            f"episode “{episode.title}” ({conversation.split('@')[0]}): "
            f"{added} new fact(s){f', {changed} updated' if changed else ''}"
            f" · {time.time() - started:.1f} s"
        )
        Log.info(
            f"memory writer: {conversation} → {episode.title!r}, {added} new / {changed} updated fact(s)"
        )
        return episode

    def _apply(
        self,
        items: list[Any],
        *,
        tellers: set[str],
        private: bool,
        private_to: str | None,
        channel: str,
        known: dict[str, MemoryFact],
        sources: dict[str, list[str]],
        episode: str,
    ) -> list[tuple[MemoryFact, MemoryFact | None]]:
        """The rules of blocks #66 / #68: what of the model's proposal is kept, and where."""
        kept: list[tuple[MemoryFact, MemoryFact | None]] = []
        for item in items:
            if len(kept) >= MAX_FACTS:
                break
            if not isinstance(item, dict):
                continue
            text = _clean(item.get("text"), 200)
            teller = str(item.get("teller") or "")
            if not text or teller not in tellers:
                continue  # only named participants who spoke keep facts (invariant 23)
            about = str(item.get("about") or teller)
            category = str(item.get("category") or "other")
            category = category if category in CATEGORIES else "other"
            sensitive = category in SENSITIVE
            if sensitive and about != teller:
                continue  # health, money, relationships: only about themselves
            household = about == HOUSEHOLD and not private
            scope = HOUSEHOLD if household else teller
            valid = str(item.get("valid_until") or "")
            fact = MemoryFact(
                scope,
                text,
                subject=HOUSEHOLD if about == HOUSEHOLD else about,
                teller=teller,
                channel=channel,
                visibility="private" if private or sensitive else "public",
                origin="inferred",
                category=category,
                valid_until=valid if _DATE.match(valid) else None,
                sources=tuple(sources.get(teller, [])[-5:]),
                episode=episode,
            )
            old = (
                known.get(str(item.get("replaces") or "")[:8])
                if item.get("op") == "supersede"
                else None
            )
            if old is not None and (
                old.scope != scope
                or not old.active
                or (
                    old.scope == HOUSEHOLD
                    and old.origin == "explicit"
                    and old.teller not in (None, teller)
                )
            ):
                # Only within the teller's own scope (a person corrects what is said about
                # them) or the household's — where an explicit fact only by its own teller.
                old = None
            if old is not None:
                if old.text == text:
                    continue
                self.memory.supersede(old.id, fact)
            else:
                if any(f.text == text for f in known.values()):
                    continue
                stored = self.memory.remember(
                    fact.scope,
                    fact.text,
                    subject=fact.subject,
                    teller=fact.teller,
                    channel=fact.channel,
                    visibility=fact.visibility,
                    origin="inferred",
                    category=fact.category,
                    valid_until=fact.valid_until,
                    episode=episode,
                    sources=fact.sources,
                )
                if stored.id != fact.id:
                    continue  # the same text was already there
            kept.append((fact, old))
        return kept

    # ---------------------------------------------------------------- nightly

    async def _maybe_nightly(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        local = time.localtime(now)
        day = time.strftime("%Y-%m-%d", local)
        if local.tm_hour != self.nightly_hour or self.memory.meta("nightly") == day:
            return
        if self.busy():
            return
        await self.nightly(day)

    async def nightly(self, today: str | None = None) -> dict[str, int]:
        """Expire dated facts, digest scopes that outgrew the block, merge large scopes."""
        today = today or time.strftime("%Y-%m-%d")
        self.state = "nightly"
        counts = {"expired": self.memory.expire(today), "digests": 0, "merged": 0}
        try:
            for scope in self.memory.scopes():
                counts["merged"] += await self.merge(scope)
                counts["digests"] += int(await self.digest(scope))
        finally:
            self.state = "idle"
        self.memory.set_meta("nightly", today)
        self._note(
            f"nightly: {counts['expired']} expired, {counts['merged']} merged, "
            f"{counts['digests']} digest(s)"
        )
        Log.info(f"memory nightly: {counts}")
        return counts

    async def digest(self, scope: str) -> bool:
        """Write a digest for a scope whose open facts outgrew `DIGEST_BUDGET` (when stale)."""
        facts = [f for f in self.memory.facts(scope, limit=300) if f.visibility == "public"]
        size = sum(len(f.text) + 3 for f in facts)
        current = self.memory.digest(scope)
        if size <= DIGEST_BUDGET:
            return False
        if (
            current is not None
            and current[2] == len(facts)
            and all(f.ts <= current[1] for f in facts)
        ):
            return False
        who = "the household" if scope == HOUSEHOLD else self.name(scope)
        result = await self.llm.infer(
            self.slot,
            [
                LLMMessage(
                    "system",
                    DIGEST_ROLE.format(
                        who=who,
                        language=LANGUAGE_NAMES.get(self.language, self.language),
                        limit=DIGEST_BUDGET,
                    ),
                ),
                LLMMessage("user", "\n".join(f"- {f.text}" for f in facts)),
            ],
            LLMInferOptions(max_tokens=2000, temperature=0.3),
            task="memory.digest",
        )
        text = _clean(result.output, DIGEST_BUDGET + 100) if result.success else ""
        if not text:
            return False
        self.memory.save_digest(scope, text, len(facts))
        return True

    async def merge(self, scope: str) -> int:
        """Retire duplicates in a scope of more than `MERGE_MIN_FACTS` inferred facts."""
        facts = self.memory.facts(scope, limit=300)
        if sum(1 for f in facts if f.origin == "inferred") <= MERGE_MIN_FACTS:
            return 0
        by_short = {f.id[:8]: f for f in facts}
        result = await self.llm.infer(
            self.slot,
            [
                LLMMessage("system", MERGE_ROLE.format(who=scope)),
                LLMMessage(
                    "user",
                    "\n".join(
                        f"- {short} | {time.strftime('%Y-%m-%d', time.localtime(f.ts))} | {f.text}"
                        for short, f in by_short.items()
                    ),
                ),
            ],
            LLMInferOptions(max_tokens=2000, temperature=0.2),
            task="memory.merge",
        )
        data = parse_json(result.output) if result.success else None
        items = [i for i in (data or {}).get("retire") or [] if isinstance(i, dict)]
        pairs = [
            (by_short[str(i.get("id"))[:8]], by_short.get(str(i.get("because"))[:8]))
            for i in items
            if str(i.get("id"))[:8] in by_short
        ]
        pairs = [(f, keep) for f, keep in pairs if f.origin == "inferred" and keep is not f]
        if not pairs:
            return 0
        if len(pairs) > MERGE_MAX_SHARE * len(facts):
            Log.warning(f"memory merge for {scope} refused: {len(pairs)} of {len(facts)} facts")
            self._note(
                f"merge for {scope} refused: it would retire {len(pairs)} of {len(facts)}", "warn"
            )
            return 0
        for fact, keep in pairs:
            self.memory.retire(fact.id, keep.id if keep is not None else "merged")
        return len(pairs)

    # -------------------------------------------------------------- reporting

    def live(self) -> dict[str, Any]:
        """The writer's state for the Live page."""
        return {
            "state": self.state if self.enabled else "off",
            "waiting": self.waiting,
            "written": self.written,
            "last_s": None if self.last_run_ts is None else round(time.time() - self.last_run_ts),
            "error": self.last_error,
        }

    def activity(self, since: float = 0.0, limit: int = 20) -> list[dict[str, Any]]:
        """What the writer did, newest first."""
        return [r for r in reversed(self.recent) if r["ts"] > since][:limit]


def _fields(episode: MemoryEpisode) -> dict[str, Any]:
    return {name: getattr(episode, name) for name in MemoryEpisode.__dataclass_fields__}
