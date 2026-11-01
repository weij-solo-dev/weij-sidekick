"""sidekick.agent.tools — tool registry, confirm gating and the built-in tools

Overview
    `ToolRegistry` holds every `Tool` (core, extension, MCP) and renders the subset a profile may
    use into LLM function schemas. `ConfirmationGate` implements invariant 13: a `confirm=True`
    tool is not executed on first call; the request is parked per conversation and executed only
    after the speaker's explicit yes. The built-in tool factories here cover memory, skills, MCP
    CRUD and the clock; `delegate` lives in `agent.py` because it needs the swarm; the scheduling
    tools are `automation`'s own (`automation/tools.py`).
Design
    Tools are plain dataclasses with async handlers; registration carries an `origin` so an
    extension's (or `automation`'s) tools can be removed as a block, and `main_only` tools are
    left out of every subagent's set. Affirmatives are checked on normalised text and
    cover Cantonese, Mandarin and English. Arguments arrive as parsed JSON; handlers validate what
    they need and return `ToolResult` instead of raising. The memory tools work on the speaker's
    contact (resolved at call time, so a person befriended earlier in the turn counts) and the
    household: an unnamed speaker stores nothing of their own, and `forget` never reaches another
    person's facts (block #63).
Depends on
    sidekick.log, sidekick.llm, sidekick.contact (`is_person`).

See Also
--------
    AGENTS.md "Agent swarm" (Tools), "Dialogue and memory", invariant 13.

"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from sidekick.contact import is_person
from sidekick.llm import LLMToolSpec
from sidekick.log import Log

from .memory import CATEGORIES, MemoryStore
from .schemas import HOUSEHOLD, MCPServer, Skill, Tool, ToolContext, ToolResult
from .skills import SkillStore

AFFIRMATIVES = (
    "好",
    "好呀",
    "好啊",
    "係",
    "是",
    "是的",
    "確認",
    "确认",
    "可以",
    "得",
    "ok",
    "okay",
    "yes",
    "yep",
    "sure",
    "do it",
    "go ahead",
    "冇問題",
    "没问题",
    "就係",
    "對",
    "对",
    "嗯好",
)
NEGATIVES = (
    "唔",
    "不",
    "no",
    "nope",
    "cancel",
    "取消",
    "算",
    "唔好",
    "不要",
    "不用",
    "don't",
    "dont",
    "停",
)
_PUNCT = re.compile(r"[\s,.;:!?，。；：！？、…]+")


def normalize(text: str) -> str:
    """Lowercase, no punctuation."""
    return _PUNCT.sub("", text.strip().lower())


def is_affirmative(text: str) -> bool:
    """Whether a short reply means yes."""
    stripped = text.strip().lower()
    if not stripped:
        return False
    if stripped.isascii():
        words = _PUNCT.sub(" ", stripped).split()
        if not words or len(words) > 3:
            return False
        if words[0] in {normalize(n) for n in NEGATIVES if n.isascii()}:
            return False
        return words[0] in {normalize(a) for a in AFFIRMATIVES if a.isascii()} or " ".join(
            words[:2]
        ) in {normalize(a) for a in AFFIRMATIVES if a.isascii()}
    norm = normalize(stripped)
    if not norm or len(norm) > 8:
        return False
    if any(norm.startswith(normalize(n)) for n in NEGATIVES):
        return False
    if any(norm == normalize(a) for a in AFFIRMATIVES):
        return True
    return len(norm) <= 4 and any(norm.startswith(normalize(a)) for a in AFFIRMATIVES)


def is_negative(text: str) -> bool:
    """Whether a short reply means no."""
    norm = normalize(text)
    return bool(norm) and len(norm) <= 12 and any(norm.startswith(normalize(n)) for n in NEGATIVES)


class ToolRegistry:
    """All tools by name."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Add or replace."""
        self._tools[tool.name] = tool

    def register_many(self, tools: Iterable[Tool]) -> None:
        """Add several."""
        for tool in tools:
            self.register(tool)

    def unregister(self, name: str) -> None:
        """Remove one."""
        self._tools.pop(name, None)

    def unregister_origin(self, origin: str) -> int:
        """Remove every tool from an origin."""
        names = [n for n, t in self._tools.items() if t.origin == origin]
        for name in names:
            del self._tools[name]
        return len(names)

    def get(self, name: str) -> Tool | None:
        """Lookup."""
        return self._tools.get(name)

    def names(self) -> list[str]:
        """Sorted names."""
        return sorted(self._tools)

    def all(self) -> list[Tool]:
        """Every tool."""
        return [self._tools[n] for n in sorted(self._tools)]

    def for_allowlist(
        self, allow: tuple[str, ...], mcp_allow: tuple[str, ...] = ("*",), main: bool = True
    ) -> list[Tool]:
        """Tools a profile may use (`main=False`: a subagent, never given `main_only` tools)."""
        out: list[Tool] = []
        for tool in self.all():
            if tool.main_only and not main:
                continue
            if tool.origin.startswith("mcp:"):
                server = tool.origin.split(":", 1)[1]
                if not ("*" in mcp_allow or server in mcp_allow):
                    continue
                if not ("*" in allow or tool.name in allow or "mcp.*" in allow):
                    continue
            elif not ("*" in allow or tool.name in allow):
                continue
            out.append(tool)
        return out

    @staticmethod
    def specs(tools: Iterable[Tool]) -> tuple[LLMToolSpec, ...]:
        """Function schemas."""
        return tuple(t.spec() for t in tools)


class ConfirmationGate:
    """Parked sensitive calls per conversation (invariant 13)."""

    def __init__(self, ttl_s: float = 300.0) -> None:
        self.ttl_s = ttl_s
        self._pending: dict[str, tuple[str, dict[str, Any], float]] = {}

    def request(self, ctx: ToolContext, tool: Tool, arguments: dict[str, Any]) -> ToolResult:
        """Park the call and tell the model to ask."""
        self._pending[ctx.conversation_key] = (tool.name, dict(arguments), time.monotonic())
        summary = json.dumps(arguments, ensure_ascii=False)[:200]
        Log.info(f"confirmation requested for {tool.name} by {ctx.speaker}: {summary}")
        return ToolResult(
            False,
            f"This action needs the user's explicit confirmation first. Tell them briefly what "
            f"{tool.name} will do with {summary} and ask them to confirm. Do not call it again "
            f"now; it will run automatically when they say yes.",
            needs_confirmation=True,
        )

    def pending(self, key: str) -> tuple[str, dict[str, Any]] | None:
        """The parked call for a conversation, if still fresh."""
        item = self._pending.get(key)
        if item is None:
            return None
        name, arguments, ts = item
        if time.monotonic() - ts > self.ttl_s:
            del self._pending[key]
            return None
        return name, arguments

    def clear(self, key: str) -> None:
        """Forget."""
        self._pending.pop(key, None)

    def parked(self) -> list[dict[str, Any]]:
        """Calls waiting for a yes (Live page): conversation key, tool, age."""
        now = time.monotonic()
        return [
            {"key": key, "tool": name, "age_s": round(now - ts, 1)}
            for key, (name, _, ts) in self._pending.items()
            if now - ts <= self.ttl_s
        ]


# ------------------------------------------------------------------- built-in tools


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or []}


def time_tools() -> list[Tool]:
    """The clock."""

    async def now(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        stamp = datetime.now()
        return ToolResult(
            True,
            stamp.strftime("%Y-%m-%d %H:%M (%A)"),
            {"iso": stamp.isoformat(timespec="minutes")},
        )

    return [
        Tool(
            "time_now",
            "Current local date and time. Rarely needed: the prompt's context line already "
            "has them to the minute.",
            _schema({}),
            now,
        )
    ]


def memory_tools(
    store: MemoryStore,
    resolve: Callable[[str], str] | None = None,
    members: Callable[[], list[str]] | None = None,
    episode_rows: Callable[[str], list[str]] | None = None,
) -> list[Tool]:
    """Remember / forget / recall over the memory pyramid (blocks #63, #70).

    `resolve` maps the turn's speaker to the contact it stands for now (a `person:n` befriended
    earlier in the same turn); an unnamed speaker keeps no facts of their own. `remember`
    stores an explicit fact with its provenance (teller, channel, the row; private in a private
    chat or for a sensitive category). `recall` searches facts and episodes — the speaker's own,
    the household's and the other members' open facts (`members`) — and opens an episode's
    conversation (`episode_rows`, L0) when asked for its id.
    """

    def own(ctx: ToolContext) -> str:
        return resolve(ctx.speaker) if resolve is not None else ctx.speaker

    def private(ctx: ToolContext) -> bool:
        return bool(ctx.message.metadata.get("private"))

    async def remember(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        text = str(arguments.get("text", "")).strip()
        if not text:
            return ToolResult.error("text is required")
        speaker = own(ctx)
        household = arguments.get("scope") == "household" and not private(ctx)
        scope = HOUSEHOLD if household else speaker
        if is_person(scope):
            return ToolResult.error(
                "not stored: this speaker has no name yet, and unnamed people keep no memory. "
                "Tell them you don't know them yet; if they want to be remembered, ask their name "
                "and befriend them (their name and voice are kept by that)."
            )
        category = str(arguments.get("category") or "other")
        fact = store.remember(
            scope,
            text,
            ctx.message.id,
            subject=scope,
            teller=None if is_person(speaker) else speaker,
            channel=ctx.channel,
            visibility="private" if private(ctx) else "public",
            origin="explicit",
            category=category if category in CATEGORIES else "other",
        )
        note = " (kept private)" if fact.visibility == "private" else ""
        return ToolResult(True, f"remembered ({scope}){note}: {fact.text}", {"id": fact.id})

    async def forget(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        text = str(arguments.get("text", "")).strip()
        if not text:
            return ToolResult.error("text is required")
        household = arguments.get("scope") == "household"
        removed = 0 if household else store.forget(text=text, scope=own(ctx))
        if removed == 0:
            removed = store.forget(text=text, scope=HOUSEHOLD)
        return ToolResult(True, f"forgot {removed} item(s) matching {text!r}")

    async def recall(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        speaker = own(ctx)
        episode_id = str(arguments.get("episode") or "").strip()
        if episode_id:
            episode = store.episode(episode_id)
            if episode is None or not store.visible(episode, speaker, private(ctx)):
                return ToolResult.error(f"no episode {episode_id!r} you may open")
            lines = episode_rows(episode.conversation) if episode_rows is not None else []
            text = "\n".join(lines) or "(no rows)"
            if len(text) > 1800:
                text = text[:1800] + "…"
            return ToolResult(True, f"{episode.title} — {episode.summary}\n{text}")
        query = str(arguments.get("query", "")).strip()
        others = [m for m in (members() if members is not None else []) if m != speaker]
        facts, episodes = store.search(speaker, query, private=private(ctx), others=others)
        if not facts and not episodes:
            return ToolResult(True, "nothing remembered about that")
        lines = [
            f"- ({f.scope}, {f.category}{', private' if f.visibility == 'private' else ''}) {f.text}"
            for f in facts
        ]
        lines += [
            f"- episode {e.id} {time.strftime('%Y-%m-%d %H:%M', time.localtime(e.ts_start))}"
            f" ({e.channel}): {e.title} — {e.summary}"
            for e in episodes
        ]
        return ToolResult(True, "\n".join(lines))

    return [
        Tool(
            "remember",
            "Store a fact worth keeping about the speaker (default) or the whole household, "
            "when they ask you to remember it. Conversations are also summarised into memory "
            "automatically after they end.",
            _schema(
                {
                    "text": {"type": "string"},
                    "scope": {"type": "string", "enum": ["speaker", "household"]},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                },
                ["text"],
            ),
            remember,
        ),
        Tool(
            "forget",
            "Delete remembered facts containing the text (the speaker's own, else the "
            "household's).",
            _schema(
                {
                    "text": {"type": "string"},
                    "scope": {"type": "string", "enum": ["speaker", "household"]},
                },
                ["text"],
            ),
            forget,
        ),
        Tool(
            "recall",
            "Search what you remember: facts about the speaker, the household and the family, "
            "and earlier conversations (episodes). Pass an episode id to read that "
            "conversation.",
            _schema({"query": {"type": "string"}, "episode": {"type": "string"}}),
            recall,
        ),
    ]


def skill_tools(store: SkillStore) -> list[Tool]:
    """skill_list / skill_read / skill_create / skill_update / skill_delete."""

    async def skill_list(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        skills = store.list()
        if not skills:
            return ToolResult(True, "no skills")
        return ToolResult(
            True,
            "\n".join(
                f"- {s.name} [{'on' if s.enabled else 'off'}, {s.origin}]: {s.description}"
                for s in skills
            ),
        )

    async def skill_read(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        skill = store.get(str(arguments.get("name", "")))
        if skill is None:
            return ToolResult.error("no such skill")
        return ToolResult(True, skill.body)

    async def skill_create(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        name = str(arguments.get("name", "")).strip()
        if not name:
            return ToolResult.error("name is required")
        skill = store.upsert(
            Skill(
                name, str(arguments.get("description", "")), str(arguments.get("body", "")), "user"
            )
        )
        return ToolResult(True, f"skill {skill.name} saved")

    async def skill_delete(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        ok = store.delete(str(arguments.get("name", "")))
        return ToolResult(ok, "deleted" if ok else "no such skill")

    params = _schema(
        {"name": {"type": "string"}, "description": {"type": "string"}, "body": {"type": "string"}},
        ["name"],
    )
    return [
        Tool("skill_list", "List skills (name, description).", _schema({}), skill_list),
        Tool(
            "skill_read",
            "Read a skill's full instructions.",
            _schema({"name": {"type": "string"}}, ["name"]),
            skill_read,
        ),
        Tool(
            "skill_create", "Create a skill: a Markdown instruction document.", params, skill_create
        ),
        Tool("skill_update", "Replace a skill's description and body.", params, skill_create),
        Tool(
            "skill_delete",
            "Delete a skill.",
            _schema({"name": {"type": "string"}}, ["name"]),
            skill_delete,
            confirm=True,
        ),
    ]


def mcp_tools(registry: Any, pool: Any, on_change: Any = None) -> list[Tool]:
    """mcp_list / mcp_add / mcp_remove / mcp_enable."""

    async def mcp_list(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        servers = registry.list()
        if not servers:
            return ToolResult(True, "no MCP servers")
        return ToolResult(
            True,
            "\n".join(
                f"- {s.name} [{s.transport}, {'on' if s.enabled else 'off'}, {s.origin}] {s.command or s.url}"
                for s in servers
            ),
        )

    async def mcp_add(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            server = MCPServer(
                str(arguments.get("name", "")).strip(),
                "http" if arguments.get("url") else "stdio",
                command=str(arguments.get("command", "")),
                args=tuple(str(a) for a in arguments.get("args", []) or []),
                url=str(arguments.get("url", "")),
            )
            registry.upsert(server)
        except Exception as exc:
            return ToolResult.error(str(exc))
        if on_change is not None:
            await on_change()
        return ToolResult(True, f"mcp server {server.name} added")

    async def mcp_remove(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        name = str(arguments.get("name", ""))
        await pool.disconnect(name)
        ok = registry.delete(name)
        if on_change is not None:
            await on_change()
        return ToolResult(ok, "removed" if ok else "no such server")

    async def mcp_enable(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        name = str(arguments.get("name", ""))
        enabled = bool(arguments.get("enabled", True))
        ok = registry.set_enabled(name, enabled)
        if not enabled:
            await pool.disconnect(name)
        if on_change is not None:
            await on_change()
        return ToolResult(
            ok, f"{name} {'enabled' if enabled else 'disabled'}" if ok else "no such server"
        )

    return [
        Tool("mcp_list", "List configured MCP servers.", _schema({}), mcp_list),
        Tool(
            "mcp_add",
            "Add an MCP server: either a stdio command (+args) or an http url.",
            _schema(
                {
                    "name": {"type": "string"},
                    "command": {"type": "string"},
                    "args": {"type": "array", "items": {"type": "string"}},
                    "url": {"type": "string"},
                },
                ["name"],
            ),
            mcp_add,
            confirm=True,
        ),
        Tool(
            "mcp_remove",
            "Remove an MCP server.",
            _schema({"name": {"type": "string"}}, ["name"]),
            mcp_remove,
            confirm=True,
        ),
        Tool(
            "mcp_enable",
            "Enable or disable an MCP server.",
            _schema({"name": {"type": "string"}, "enabled": {"type": "boolean"}}, ["name"]),
            mcp_enable,
        ),
    ]
