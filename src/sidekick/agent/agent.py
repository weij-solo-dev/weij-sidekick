"""sidekick.agent.agent — AgentSession: the swarm (main agent + subagents), turns, delegation

Overview
    One `Agent` class, many profiles. The **main** agent owns every inbound turn (voice or text):
    it appends the message to the timeline, builds its context view plus memory and skill blocks,
    runs the ReAct loop with its tool set, appends the reply, and streams text to the caller.
    **Subagents** (from config — kept by the dashboard's Subagents view through `set_subagent` —
    or extensions; each profile says its `origin`) run on request through the `delegate` tool, either
    synchronously (the main agent composes the answer) or in the background (`task-…`: the
    result lands on the timeline as an internal note and a follow-up turn relays it).
    `AgentSession` also owns the stores, the tool registry (the tool protocol other modules
    implement: `automation`'s scheduling tools, the extensions'), the MCP pool, the confirmation
    gate and the delivery policy. It knows no jobs: `automation` asks for `run_job_turn()` (one
    main-agent turn on a job's prompt, then delivery) and `delivered_since()` (the heartbeat's
    "already said" list).
Design
    The surface the rest of sidekick uses is unchanged from Phase 1: `respond(message)` yields
    text deltas (voice pipeline), `handle(message)` answers text channels through
    `ChannelSession`. Confirmation (invariant 13) is resolved before the loop runs: a yes to a
    parked sensitive call executes it and the agent is told so. Delivery of unprompted messages
    (jobs, background results): `in_person` speaks through `say`, `remote` sends to the job's
    channel, `auto` prefers speech when `can_speak()` and falls back to the remote channel (both
    hooks come from the voice front end through `setup`; `say` answers False when nothing was
    spoken); the delivered reply is recorded once, with `delivered_to` and the policy (a job's
    own turn does not record it a second time). `main_only` tools (`delegate`, scheduling) are
    never in a subagent's set: subagents are experts for one domain (invariant 22). Unnamed-speaker labels (`person:6`,
    `guest:2`) are for tool calls only: the prompt forbids them and `run_main` replaces any that
    slip into the streamed reply (held back while a label may still be cut across chunks), so
    they are never spoken, sent or shown. Every LLM call goes through `LLMSession` (invariant 5);
    the agent never touches the body (invariant 7). Memory follows identity (block #63): a
    turn's speaker is resolved to its contact (`tg:42`, the dashboard's `owner` once an owner
    contact exists), the memory tools resolve again at call time (a person befriended earlier
    in the turn), unnamed speakers keep no facts, and facts the dashboard kept under `owner`
    before there was an owner contact move to it on that contact's first turn.
    The service's start (block #86) makes one real call per model slot the agents use, which
    also opens the connection the first turn will use; `check()` reports them (a `fast` slot
    that does not answer aborts the start); `stop()` waits for its cancelled tasks.
Depends on
    sidekick.log, sidekick.storage, sidekick.llm, sidekick.channel, sidekick.contact (through
    `memory` / `tools`; the contact and perception sessions are peers handed to `setup`).

See Also
--------
    AGENTS.md "Agent swarm", "Dialogue and memory", "Automations, heartbeat, delivery";
    PLAN.md block "[2026-10-26 #14]".

"""

from __future__ import annotations

import asyncio
import collections
import dataclasses
import json
import re
import statistics
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, ClassVar, Literal

from sidekick.channel import ChannelMessage, ChannelReply, ChannelSession
from sidekick.contact import OWNER_ALIAS, SELF_ID, is_person
from sidekick.llm import LLMInferOptions, LLMMessage, LLMResult, LLMSession
from sidekick.log import Log

from .dialogue import PERFORMANCE_TAG, DialogueStore, conversation_key
from .loop import ReActLoop
from .mcp import MCPClientPool, MCPRegistry
from .memory import MemoryStore
from .schemas import (
    NO_REPLY,
    AgentEvent,
    AgentProfile,
    AgentReplyEvent,
    DialogueMessage,
    Tool,
    ToolContext,
    ToolResult,
)
from .skills import SkillStore
from .tools import (
    ConfirmationGate,
    ToolRegistry,
    is_affirmative,
    is_negative,
    mcp_tools,
    memory_tools,
    skill_tools,
    time_tools,
)
from .writer import MemoryWriter

LANGUAGE_NAMES = {"zh": "Mandarin Chinese", "en": "English", "yue": "Cantonese"}

MAIN_ROLE = """You are Banana, a small desktop robot and the household's butler.
You speak with the family in person through a speaker, and sometimes through chat apps.
Rules:
- Be brief: one or two short sentences, like a person talking. No lists, no markdown, no emoji.
- Answer in the reply language the context line names. For Mandarin, write natural spoken
  Mandarin in Simplified Chinese characters. For Cantonese, write colloquial spoken Cantonese
  (係 / 唔 / 嘅 / 喺 / 啲) in Traditional Chinese characters, never formal written Chinese.
- You are warm, a little playful, and honest when you do not know something.
- If the utterance was clearly not addressed to you (people talking to each other, the TV),
  answer exactly NO_REPLY and nothing else.
- Spoken turns are speech-recognition transcripts and can be wrong, above all names and short
  words. Read them for what was most likely said (a word that sounds like your name or a
  household member's is that name); if you still cannot tell, ask briefly instead of answering
  a different question. Your name is the English word "banana"; it comes out as BANANA,
  BANANNA, ANANNA, 把娜娜 or 巴娜娜: that is someone calling you, never another person and not
  the fruit (the fruit is 香蕉).
- You have no hands and cannot leave your desk: never offer to cook, fetch, carry or make
  anything. Offer only what your tools can do.
- Someone shown as person:N or guest:N has no name yet. Never say or write such a label; it is
  only for tool calls. Talk to them as 你; if they ask who they are, say you don't know their
  name yet; about them, say 那位朋友 / that friend.
- Your memory is the block "What you remember" (when there is one): what you know about the
  speaker and the household and your recent conversations with them; conversations are
  summarised into it automatically after they end. Never claim to remember more than it says;
  for anything older or more detailed, call `recall` first. When someone explicitly asks you to
  remember something, call `remember` before answering; never claim to have remembered without
  calling it.
- Use tools instead of guessing: `schedule` for reminders and timers, `delegate` for long or
  specialised work. The context line gives the date and the time to the minute: answer time
  and date questions from it directly, without a tool. Call tools straight away, without
  announcing them (no 「我看看」 first); after the result, answer in a sentence or two.
- Your body moves naturally on its own while you talk and listen, so most replies carry no
  expression: an answer, a confirmation, a reminder, small talk — none. Add one
  [express:name] only when you truly feel something: laughing at a joke, surprise, delight at
  good news, sympathy for bad news, being touched. Never more than one per reply and never just
  to be friendly; it is performed, not spoken. The `robot body` skill lists the names.
- Style: a story, a game or play with a child starts with [style:lively]; comforting someone,
  sad or serious news (a pet died, someone is ill) starts with [style:calm]; otherwise no style.
  It lasts for that reply only.
- Today's date and time are given in the context; use them when asked.
"""

SUBAGENT_ROLE_SUFFIX = (
    "\nYou are a specialist working on a task delegated by the main agent. Do the work with your "
    "tools and return a concise result in the household's language; the main agent will relay it."
)

SayCallback = Callable[[str, str | None], Awaitable[Any]]  # False: not spoken
# The main agent's LLM connection is kept open (block #71): a fresh one cost a 1.3 s TLS
# handshake on every turn. Re-opened every KEEP_WARM_S, and when someone starts talking in a
# session (at most every WARM_GAP_S).
KEEP_WARM_S = 50.0
WARM_GAP_S = 20.0

# Unnamed-speaker labels (`person:6`, `guest:2`) are for tool calls; they never reach the room.
_SPEAKER_ID = re.compile(r"[ \t]?(?<![A-Za-z])(?:person|guest)\s*[:：]\s*\d+[ \t]?", re.IGNORECASE)
_SPEAKER_ID_TAIL = re.compile(
    r"[ \t]?(?<![A-Za-z])(?:p(?:e(?:r(?:s(?:o(?:n\s*(?:[:：]\s*\d*)?)?)?)?)?)?"
    r"|g(?:u(?:e(?:s(?:t\s*(?:[:：]\s*\d*)?)?)?)?)?)$",
    re.IGNORECASE,
)
_UNNAMED = {"zh": "这位朋友", "yue": "呢位朋友", "en": " this friend "}
_EMOJI = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff\ufe0f\u200d\u20e3]")


class _SpeakerIdScrubber:
    """Replace unnamed-speaker labels in streamed reply text, holding back a label cut mid-way.

    A spoken reply also loses its emoji: the voice cannot say them, and a 😂 kept in the
    timeline teaches the model to write more (block #89).
    """

    def __init__(self, language: str | None, spoken: bool = False) -> None:
        self.word = _UNNAMED.get(language or "", _UNNAMED["zh"])
        self.spoken = spoken
        self.pending = ""

    def scrub(self, text: str) -> str:
        """Every complete label replaced (whole texts)."""
        text = _SPEAKER_ID.sub(self.word, text)
        return _EMOJI.sub("", text) if self.spoken else text

    def feed(self, text: str) -> str:
        """The part of the stream that is safe to emit now."""
        buffer = self.pending + text
        tail = _SPEAKER_ID_TAIL.search(buffer)
        cut = tail.start() if tail else len(buffer)
        self.pending = buffer[cut:]
        return self.scrub(buffer[:cut])

    def flush(self) -> str:
        """Whatever was held back, at the end of the stream or before a non-text event."""
        text, self.pending = self.pending, ""
        return self.scrub(text)


class Agent:
    """One agent with a profile."""

    def __init__(self, profile: AgentProfile, session: AgentSession) -> None:
        self.profile = profile
        self.session = session
        self.turns = 0
        self.last_error: str | None = None

    def system_prompt(self, message: ChannelMessage) -> str:
        """Role, skills, subagents and the conversation's memory block: stable for a conversation.

        MiniMax caches prompt prefixes (`cached_tokens` in the usage; an identical prefix
        answered 0.3–0.9 s sooner, block #71), so nothing in here changes during a conversation:
        the per-turn line (time, speaker, language, channel) leads the turn's own message
        instead (`turn_note`), and the history after the system prompt only grows.
        """
        parts = [self.profile.role]
        skills = self.session.skills.descriptions_block(self.profile.skills)
        if skills:
            parts.append(skills)
        if self.session.agents_block and self.profile.name == "main":
            parts.append(self.session.agents_block)
        memory = self.session.memory_block(message)
        if memory:
            parts.append(memory)
        return "\n\n".join(parts)

    def turn_note(self, message: ChannelMessage, extra: str = "") -> str:
        """The per-turn context that leads the turn's message (time, speaker, language, channel)."""
        language = message.language or self.session.default_language
        now = time.strftime("%Y-%m-%d %H:%M %A")
        channel_hint = (
            "The person is in the room talking to you; your words are spoken aloud."
            if message.channel == "voice"
            else f"The message arrived through {message.channel}; reply as a text message."
        )
        speaker_label = self.session._label(message.speaker)
        if message.speaker.startswith("guest:"):
            speaker_label = "an unidentified guest"
        note = (
            f"[Context: now is {now}. Speaker: {speaker_label}. "
            f"Reply language: {LANGUAGE_NAMES.get(language, language)}. {channel_hint}]"
        )
        return note + (f"\n[{extra}]" if extra else "")

    async def run(
        self,
        message: ChannelMessage,
        context: list[LLMMessage] | None = None,
        confirmed: bool = False,
        extra_prompt: str = "",
        record: bool = True,
    ) -> AsyncIterator[AgentEvent]:
        """One turn; yields `AgentEvent`s and records steps on the timeline."""
        self.turns += 1
        session = self.session
        ctx = ToolContext(message, self.profile.name, confirmed, session)
        tools = session.tools_for(self.profile)
        conversation = message.metadata.get("conversation")
        if context is None:
            rolling = session.memory.episode_for(conversation) if conversation else None
            context = session.dialogue.context_view(
                conversation,
                self.profile.name,
                self.profile.context_chars,
                earlier=rolling.summary if rolling is not None else None,
                name=session._label,
            )
            last = context[-1] if context else None
            if (
                last is None
                or last.role != "user"
                or not (last.content or "").endswith(message.text)
            ):
                context = [*context, LLMMessage("user", message.text)]
        # The per-turn line leads this turn's message, after the stable prefix (block #71).
        if context and context[-1].role == "user":
            note = self.turn_note(message, extra_prompt)
            context = [*context[:-1], LLMMessage("user", f"{note}\n{context[-1].content or ''}")]

        def on_step(kind: str, data: dict[str, Any]) -> None:
            session.turn_step(message.id, kind, data)
            if not record or kind != "tool":
                return
            session.dialogue.append(
                DialogueMessage(
                    message.channel,
                    self.profile.name,
                    "tool",
                    str(data.get("content", "")),
                    visibility="internal",
                    agent=self.profile.name,
                    reply_to=message.id,
                    meta={
                        "tool_call_id": data.get("call_id"),
                        "tool": data.get("tool"),
                        "arguments": data.get("arguments"),
                        "ok": data.get("ok"),
                        "step": data.get("step"),
                        # what the model said before this step's calls (block #76)
                        **({"said": data["said"]} if data.get("said") else {}),
                    },
                    conversation=conversation,
                )
            )

        session.turn_begin(message, self.profile.name)
        outcome = "cancelled"
        try:
            async for event in session.loop.run(
                self.profile,
                self.system_prompt(message),
                context,
                tools,
                ctx,
                on_step,
            ):
                if event.kind == "text":
                    session.turn_text(message.id, event.text)
                elif event.kind == "error":
                    self.last_error = event.error
                    outcome = "error"
                elif event.kind in ("done", "no_reply"):
                    outcome = event.kind
                yield event
        finally:
            session.turn_end(message.id, outcome)


class AgentSession:
    """The swarm and its stores."""

    shared: ClassVar[AgentSession]

    def __init__(self, llm: LLMSession | None = None, home: Path | None = None) -> None:
        self.llm = llm if llm is not None else LLMSession.shared
        self.default_language = "zh"
        self.home = home
        self.registry = ToolRegistry()
        self.gate = ConfirmationGate()
        self.loop = ReActLoop(self.llm, self.gate)
        self.agents: dict[str, Agent] = {}
        self.agents_block = ""
        self.say: SayCallback | None = None
        self.contacts: Any = None
        self.can_speak: Callable[[], bool] = lambda: False
        self._background: dict[str, asyncio.Task[None]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._keep_warm: asyncio.Task[None] | None = None
        self.model_checks: dict[str, LLMResult] = {}  # the start's call per slot (`check()`)
        self._warmed_at = 0.0
        # The Live page (block #69): turns in flight by message id, the newest finished ones,
        # background delegations' details and today's counters — memory only.
        self.inflight: dict[str, dict[str, Any]] = {}
        self.recent_turns: collections.deque[dict[str, Any]] = collections.deque(maxlen=40)
        self._activity: collections.deque[dict[str, Any]] = collections.deque(maxlen=200)
        self._background_meta: dict[str, dict[str, Any]] = {}
        self._today: dict[str, Any] = {"day": "", "turns": 0, "tools": 0, "tool_errors": 0}
        self._counts: tuple[float, dict[str, Any]] | None = None
        self._newest: tuple[float, dict[str, Any] | None] | None = None
        # Memory (block #70): the writer, and each conversation's memory block, frozen for it.
        self.writer: MemoryWriter | None = None
        self.memory_block_chars = 1000
        self._blocks: collections.OrderedDict[tuple[str, str], str] = collections.OrderedDict()
        self.turns = 0
        self.last_error: str | None = None
        self._stores_ready = False
        if home is not None:
            self._open_stores(home)

    # ------------------------------------------------------------------- setup

    def _open_stores(self, home: Path) -> None:
        self.home = home
        self.dialogue = DialogueStore(home / "dialogue_v1.db")
        self.memory = MemoryStore(home / "memory_v1.db")
        self.skills = SkillStore(home / "skills_v1.db")
        self.mcp_registry = MCPRegistry(home / "mcp_v1.db")
        self.mcp = MCPClientPool(self.mcp_registry)
        self._stores_ready = True

    def setup(
        self,
        llm: LLMSession | None = None,
        home: Path | None = None,
        agents: Any = None,
        default_language: str | None = None,
        say: SayCallback | None = None,
        can_speak: Callable[[], bool] | None = None,
        contacts: Any = None,
    ) -> None:
        """Bind peers and stores, register the main agent, the subagents and the own tools."""
        self.contacts = contacts
        if llm is not None:
            self.llm = llm
            self.loop = ReActLoop(self.llm, self.gate)
        if home is not None:
            self._open_stores(home)
        if not self._stores_ready:
            raise RuntimeError("AgentSession needs a home directory for its stores")
        if default_language is not None:
            self.default_language = default_language
        self.say = say
        if can_speak is not None:
            self.can_speak = can_speak
        main_slot = str(getattr(agents, "main_llm_slot", "fast"))
        self.register_agent(
            AgentProfile(
                "main",
                MAIN_ROLE,
                main_slot,
                description="conversation and routing",
                max_steps=int(getattr(agents, "main_max_steps", 6)),
                max_tokens=int(getattr(agents, "main_max_tokens", 500)),
                context_chars=int(getattr(agents, "context_chars", 6000)),
                hedge_after_s=float(getattr(agents, "main_hedge_s", 0.0)),
                origin="core",
            )
        )
        for name, sub in (getattr(agents, "subagents", {}) or {}).items():
            self.set_subagent(name, sub)
        self.dialogue.voice_gap_s = float(getattr(agents, "memory_voice_gap_min", 5.0)) * 60.0
        self.dialogue.text_gap_s = float(getattr(agents, "memory_text_gap_min", 15.0)) * 60.0
        self.memory_block_chars = int(getattr(agents, "memory_block_chars", 1000))
        self.writer = MemoryWriter(
            self.memory,
            self.dialogue,
            self.llm,
            slot=str(getattr(agents, "memory_slot", "smart")),
            name=self._label,
            named=self._named,
            busy=lambda: bool(self.inflight),
            language=self.default_language,
            enabled=bool(getattr(agents, "memory_writer", True)),
            nightly_hour=int(getattr(agents, "memory_nightly_hour", 3)),
        )
        self.registry.register_many(time_tools())
        self.registry.register_many(
            memory_tools(
                self.memory,
                self.memory_speaker,
                members=self._members,
                episode_rows=self._episode_rows,
            )
        )
        self.registry.register_many(skill_tools(self.skills))
        self.registry.register_many(mcp_tools(self.mcp_registry, self.mcp, self.refresh_mcp))
        self.registry.register(self._delegate_tool())

    def register_agent(self, profile: AgentProfile) -> Agent:
        """Add or replace an agent."""
        agent = Agent(profile, self)
        previous = self.agents.get(profile.name)
        if previous is not None:
            agent.turns = previous.turns
        self.agents[profile.name] = agent
        self._refresh_agents_block()
        return agent

    def unregister_agent(self, name: str) -> None:
        """Remove a subagent."""
        if name != "main":
            self.agents.pop(name, None)
            self._refresh_agents_block()

    def _refresh_agents_block(self) -> None:
        """The main agent's list of subagents (its system prompt)."""
        subs = [a.profile for a in self.agents.values() if a.profile.name != "main"]
        self.agents_block = (
            "Subagents you can delegate to with delegate(agent, task, mode):\n"
            + "\n".join(f"- {p.name}: {p.description or p.role[:80]}" for p in subs)
            if subs
            else ""
        )

    def _warm_connections(self) -> int:
        """Two pooled connections when the main agent hedges: its second request needs one."""
        return 2 if self.main.profile.hedge_after_s > 0 else 1

    def configure_main(self, agents: Any) -> None:
        """Apply the main agent's own knobs (`ConfigAgents`) now: its card on the Swarm view."""
        main = self.agents.get("main")
        if main is None:
            return
        self.register_agent(
            dataclasses.replace(
                main.profile,
                llm_slot=str(agents.main_llm_slot),
                max_steps=int(agents.main_max_steps),
                max_tokens=int(agents.main_max_tokens),
                context_chars=int(agents.context_chars),
                hedge_after_s=float(agents.main_hedge_s),
            )
        )

    def set_subagent(self, name: str, spec: Any) -> Agent:
        """Add or replace a subagent defined in config (`ConfigSubagent`; the Subagents view)."""
        return self.register_agent(
            AgentProfile(
                name,
                str(spec.role) + SUBAGENT_ROLE_SUFFIX,
                str(spec.llm_slot),
                description=str(spec.description),
                tools=tuple(spec.tools),
                mcp_servers=tuple(spec.mcp_servers),
                skills=tuple(spec.skills),
                max_steps=int(spec.max_steps),
                timeout_s=float(spec.timeout_s),
                origin="user",
            )
        )

    def roster(self) -> list[dict[str, Any]]:
        """Every agent for the dashboard's Swarm view, the main agent first.

        Each with its profile, origin, turns and the tools it gets.
        """
        out = []
        for name, agent in sorted(self.agents.items(), key=lambda kv: (kv[0] != "main", kv[0])):
            p = agent.profile
            out.append(
                {
                    "name": name,
                    "main": name == "main",
                    "description": p.description,
                    "role": p.role.removesuffix(SUBAGENT_ROLE_SUFFIX),
                    "llm_slot": p.llm_slot,
                    "tools": list(p.tools),
                    "mcp_servers": list(p.mcp_servers),
                    "skills": list(p.skills),
                    "max_steps": p.max_steps,
                    "max_tokens": p.max_tokens,
                    "timeout_s": p.timeout_s,
                    "hedge_after_s": p.hedge_after_s,
                    "origin": p.origin,
                    "turns": agent.turns,
                    "resolved_tools": [t.name for t in self.tools_for(p)],
                }
            )
        return out

    def register_tools(self, tools: list[Tool]) -> None:
        """Add tools (extensions)."""
        self.registry.register_many(tools)

    def unregister_origin(self, origin: str) -> None:
        """Remove an extension's tools."""
        self.registry.unregister_origin(origin)

    def tools_for(self, profile: AgentProfile) -> list[Tool]:
        """Tools a profile may use (a subagent never gets a `main_only` tool)."""
        return self.registry.for_allowlist(
            profile.tools, profile.mcp_servers, main=profile.name == "main"
        )

    async def refresh_mcp(self) -> int:
        """(Re)register tools of every enabled MCP server."""
        for tool in self.registry.all():
            if tool.origin.startswith("mcp:"):
                self.registry.unregister(tool.name)
        tools = await self.mcp.all_tools()
        self.registry.register_many(tools)
        return len(tools)

    async def start(self) -> None:
        """Prove the model answers, keep its connection open, start the writer, connect MCP.

        One real call per slot the agents use (`fast` for the main agent, `smart` for
        subagents and the memory writer), concurrently; `check()` reports them (block #86).
        The call also opens the pooled connection the first turn will use.
        """
        slots = sorted({self.main.profile.llm_slot, "smart"} & set(self.llm.slots()))
        results = await asyncio.gather(*(self._ping(slot) for slot in slots))
        self.model_checks = dict(zip(slots, results, strict=True))
        self._keep_warm = asyncio.create_task(self._keep_warm_loop(), name="agent-keep-warm")
        if self.writer is not None:
            self.writer.start()
        try:
            count = await self.refresh_mcp()
            if count:
                Log.info(f"{count} MCP tool(s) registered")
        except Exception as exc:
            Log.warning(f"mcp refresh: {exc!r}")

    async def _ping(self, slot: str) -> LLMResult:
        return await self.llm.infer(
            slot,
            [LLMMessage("user", "Reply with the single word: pong")],
            LLMInferOptions(max_tokens=16),
            task="service.check",
        )

    def check(self) -> list[dict[str, Any]]:
        """Readiness items: the main agent's model answers (`bad` if not), the smart one too."""
        main = self.main.profile.llm_slot
        items: list[dict[str, Any]] = []
        if main not in self.llm.slots():
            return [{"id": "model", "title": f"LLM {main}", "level": "bad", "detail": "not bound"}]
        for slot, result in sorted(self.model_checks.items(), key=lambda kv: kv[0] != main):
            ok = result.success
            took = result.latency_ms
            items.append(
                {
                    "id": f"llm.{slot}",
                    "title": f"LLM {slot}",
                    "level": "ok" if ok else ("bad" if slot == main else "warn"),
                    "detail": (
                        f"{result.model} answered" + (f" in {took / 1000:.1f} s" if took else "")
                    )
                    if ok
                    else (result.error_message or f"HTTP {result.status_code}")[:200],
                }
            )
        return items

    async def stop(self) -> None:
        """Cancel background work (and wait for it to end), stop the writer, close MCP."""
        pending = [*self._background.values(), *self._tasks]
        if self._keep_warm is not None:
            pending.append(self._keep_warm)
            self._keep_warm = None
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending, timeout=5.0)
        if self.writer is not None:
            await self.writer.stop()
        if self._stores_ready:
            await self.mcp.close()

    async def _keep_warm_loop(self) -> None:
        while True:
            self._warmed_at = time.monotonic()
            try:
                await self.llm.warm(self.main.profile.llm_slot, self._warm_connections())
            except Exception as exc:  # a warm-up never matters enough to stop the loop
                Log.debug(f"keep warm: {exc!r}")
            await asyncio.sleep(KEEP_WARM_S)

    def warm(self) -> None:
        """Someone started talking to Banana: open the main agent's LLM connection now.

        Called by the voice front end at speech onset inside a session (duck-typed); at most
        once every `WARM_GAP_S`, and never waited for.
        """
        now = time.monotonic()
        if now - self._warmed_at < WARM_GAP_S or "main" not in self.agents:
            return
        self._warmed_at = now
        task = asyncio.get_running_loop().create_task(
            self.llm.warm(self.main.profile.llm_slot, self._warm_connections())
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ------------------------------------------------------------------- turns

    @property
    def main(self) -> Agent:
        """The main agent."""
        return self.agents["main"]

    async def respond(self, message: ChannelMessage) -> AsyncIterator[str]:
        """Stream reply text deltas (voice pipeline); nothing for `NO_REPLY`."""
        async for event in self.respond_events(message):
            if event.kind == "text":
                yield event.text

    async def respond_events(self, message: ChannelMessage) -> AsyncIterator[AgentReplyEvent]:
        """Typed streaming reply."""
        text: list[str] = []
        async for event in self.run_main(message):
            if event.kind == "text":
                text.append(event.text)
                yield AgentReplyEvent("text", event.text)
            elif event.kind == "error":
                yield AgentReplyEvent("error", error=event.error)
                return
            elif event.kind == "no_reply":
                yield AgentReplyEvent("no_reply")
                return
        yield AgentReplyEvent("done", "".join(text))

    async def handle(self, message: ChannelMessage) -> None:
        """Text-channel inbound: reply to the originating channel (invariant 14)."""
        parts: list[str] = []
        async for event in self.respond_events(message):
            if event.kind == "text":
                parts.append(event.text)
            elif event.kind == "error":
                parts = [f"(error: {event.error})"]
        text = "".join(parts).strip()
        if not text:
            return
        await ChannelSession.shared.send(
            ChannelReply(text, channel=message.channel, to=message.speaker, reply_to=message.id)
        )

    def memory_speaker(self, speaker: str) -> str:
        """The contact a speaker stands for right now (the memory tools' scope)."""
        if self.contacts is None or not getattr(self.contacts, "ready", False):
            return speaker
        return str(self.contacts.resolve_speaker(speaker))

    def _named(self, speaker: str) -> bool:
        """Whether a speaker is a named household member (only they keep facts, invariant 23)."""
        if not speaker or is_person(speaker) or speaker in (SELF_ID, OWNER_ALIAS, "household"):
            return False
        if self.contacts is None or not getattr(self.contacts, "ready", False):
            return ":" not in speaker  # no contact store (tests): remote ids are not people
        return self.contacts.get(speaker) is not None

    def _members(self) -> list[str]:
        """The named household members (whose open facts `recall` may share)."""
        if self.contacts is None or not getattr(self.contacts, "ready", False):
            return []
        return [c.id for c in self.contacts.contacts() if c.id != SELF_ID]

    def _episode_rows(self, conversation: str) -> list[str]:
        """An episode's conversation as transcript lines (the `recall` tool's L0)."""
        lines = []
        for row in self.dialogue.conversation_rows(conversation, limit=80):
            if row.role not in ("user", "assistant"):
                continue
            who = self._label(row.speaker) if row.role == "user" else "Banana"
            at = time.strftime("%H:%M", time.localtime(row.ts))
            lines.append(f"[{at}] {who}: {PERFORMANCE_TAG.sub('', row.content).strip()}")
        return lines

    def memory_block(self, message: ChannelMessage) -> str:
        """The memory block of a turn: built once per conversation and speaker, then frozen.

        No model and no search on the turn (block #68): a few SQLite reads when a conversation
        starts; a job or an internal turn without a conversation reads it fresh.
        """
        conversation = message.metadata.get("conversation")
        speaker = self.memory_speaker(message.speaker)
        key = (str(conversation), speaker)
        if conversation and key in self._blocks:
            self._blocks.move_to_end(key)
            return self._blocks[key]
        text = self.memory.block(
            speaker,
            private=bool(message.metadata.get("private")),
            name=self._label,
            budget=self.memory_block_chars,
        )
        if conversation:
            self._blocks[key] = text
            while len(self._blocks) > 32:
                self._blocks.popitem(last=False)
        return text

    def _adopt_owner_scope(self, speaker: str) -> None:
        """Facts kept under the dashboard's `owner` move to the owner contact once there is one."""
        contact = self.contacts.get(speaker)
        if contact is not None and contact.is_owner:
            self.memory.move_scope(OWNER_ALIAS, contact.id)

    def resolve_message(self, message: ChannelMessage) -> ChannelMessage:
        """Map remote ids (`tg:42`) and `owner` to contact ids: one memory scope per person."""
        if self.contacts is None or not getattr(self.contacts, "ready", False):
            return message
        resolved = self.contacts.resolve_speaker(message.speaker)
        self._adopt_owner_scope(resolved)
        if resolved == message.speaker:
            return message
        contact = self.contacts.get(resolved)
        language = message.language or (getattr(contact, "language", None) if contact else None)
        return ChannelMessage(
            message.channel,
            resolved,
            message.text,
            id=message.id,
            ts=message.ts,
            language=language,
            reply_to=message.reply_to,
            attachments=message.attachments,
            metadata={**message.metadata, "remote_id": message.speaker},
        )

    async def run_main(
        self, message: ChannelMessage, record_user: bool = True, record_reply: bool = True
    ) -> AsyncIterator[AgentEvent]:
        """Timeline bookkeeping + confirmation handling around a main-agent turn."""
        self.turns += 1
        message = self.resolve_message(message)
        meta = message.metadata
        if "conversation" not in meta and not meta.get("job") and not meta.get("internal"):
            chat = str(meta.get("remote_id") or message.speaker)
            opened = self.dialogue.conversation_for(
                conversation_key(message.channel, chat), message.ts
            )
            message = dataclasses.replace(message, metadata={**meta, "conversation": opened})
        conversation = message.metadata.get("conversation")
        visibility: Literal["public", "private"] = (
            "private" if message.metadata.get("private") else "public"
        )
        if record_user:
            self.dialogue.append(
                DialogueMessage(
                    message.channel,
                    message.speaker,
                    "user",
                    message.text,
                    id=message.id,
                    visibility=visibility,
                    attachments=tuple(message.attachments),
                    conversation=conversation,
                )
            )
        extra = ""
        key = f"{message.channel}:{message.speaker}"
        pending = self.gate.pending(key)
        if pending is not None:
            name, arguments = pending
            if is_affirmative(message.text):
                self.gate.clear(key)
                result = await self._execute_confirmed(name, arguments, message)
                extra = (
                    f"The user just confirmed the pending action. {name} was executed with "
                    f"{json.dumps(arguments, ensure_ascii=False)[:200]} and returned: {result.content[:300]}. "
                    "Tell them the outcome briefly."
                )
                self.dialogue.append(
                    DialogueMessage(
                        message.channel,
                        "main",
                        "internal",
                        f"confirmed {name}: {result.content}",
                        visibility="internal",
                        agent="main",
                        reply_to=message.id,
                        conversation=conversation,
                    )
                )
            elif is_negative(message.text):
                self.gate.clear(key)
                extra = (
                    f"The user declined the pending action ({name}); acknowledge and do not do it."
                )
        reply: list[str] = []  # everything said, the transcript
        answer: list[str] = []  # the model's words after its last tool step (block #76)
        stepped = False
        tool_calls: list[dict[str, Any]] = []
        ids = _SpeakerIdScrubber(
            message.language or self.default_language, spoken=message.channel == "voice"
        )
        async for event in self.main.run(message, extra_prompt=extra):
            if event.kind == "text" and not event.filler:
                clean = ids.feed(event.text)
                if clean:
                    reply.append(clean)
                    answer.append(clean)
                    yield AgentEvent("text", clean)
                continue
            held = ids.flush()
            if held:
                reply.append(held)
                answer.append(held)
                yield AgentEvent("text", held)
            if event.kind == "text":  # the platform's acknowledgement: spoken, not the model's
                reply.append(event.text)
                stepped = True
                yield event
                continue
            if event.kind == "tool_call":
                tool_calls.append({"name": event.tool, "arguments": event.arguments})
            elif event.kind == "tool_result":
                answer.clear()  # said before the calls: the tool rows keep it
                stepped = True
            elif event.kind == "error":
                self.last_error = event.error
            elif event.kind == "done":
                event = AgentEvent("done", ids.scrub(event.text))
            yield event
        held = ids.flush()
        if held:
            reply.append(held)
            answer.append(held)
            yield AgentEvent("text", held)
        text = "".join(reply).strip()
        if text and record_reply:
            row_meta: dict[str, Any] = {"tools": tool_calls} if tool_calls else {}
            final = "".join(answer).strip()
            if stepped and final != text:
                # The context view shows the model only its own last words here: an
                # acknowledgement it did not write, or words it said before its calls, would
                # teach it to open every reply with them (block #76).
                row_meta["reply"] = final
            self.dialogue.append(
                DialogueMessage(
                    message.channel,
                    "main",
                    "assistant",
                    text,
                    visibility=visibility,
                    agent="main",
                    reply_to=message.id,
                    meta=row_meta,
                    conversation=conversation,
                )
            )

    async def _execute_confirmed(
        self, name: str, arguments: dict[str, Any], message: ChannelMessage
    ) -> ToolResult:
        tool = self.registry.get(name)
        if tool is None:
            return ToolResult.error(f"unknown tool {name!r}")
        ctx = ToolContext(message, "main", True, self)
        try:
            result = await tool.handler(arguments, ctx)
        except Exception as exc:
            result = ToolResult.error(f"{name} failed: {exc!r}")
        Log.info(f"confirmed {name}: {'ok' if result.ok else 'failed'} {result.content[:80]!r}")
        return result

    # -------------------------------------------------------------- delegation

    def _delegate_tool(self) -> Tool:
        async def delegate(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
            name = str(arguments.get("agent", "")).strip()
            task = str(arguments.get("task", "")).strip()
            mode = str(arguments.get("mode", "sync"))
            agent = self.agents.get(name)
            if agent is None or name == "main":
                known = ", ".join(a for a in self.agents if a != "main") or "none"
                return ToolResult.error(f"unknown agent {name!r}; available: {known}")
            if not task:
                return ToolResult.error("task is required")
            if mode == "async":
                task_id = f"task-{int(time.time() * 1000) % 10_000_000:07d}"
                self._background[task_id] = asyncio.create_task(
                    self._run_delegation(agent, task, ctx.message, task_id), name=f"delegate-{name}"
                )
                self._background_meta[task_id] = {
                    "agent": name,
                    "task": task[:80],
                    "started": time.time(),
                }
                self._note("agent", f"{name} started in the background: {task[:60]}")
                return ToolResult(
                    True,
                    f"started {name} on it in the background ({task_id}); the result will arrive later",
                    {"task_id": task_id},
                )
            try:
                result = await asyncio.wait_for(
                    self._collect(agent, task, ctx.message), agent.profile.timeout_s
                )
            except TimeoutError:
                return ToolResult.error(f"{name} timed out")
            return ToolResult(True, result or "(no result)")

        return Tool(
            "delegate",
            "Hand a task to a subagent. mode=sync waits for the result; mode=async returns at once and the result is reported later.",
            {
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "task": {"type": "string"},
                    "mode": {"type": "string", "enum": ["sync", "async"]},
                },
                "required": ["agent", "task"],
            },
            delegate,
            main_only=True,
        )

    async def _collect(self, agent: Agent, task: str, origin: ChannelMessage) -> str:
        conversation = origin.metadata.get("conversation")
        message = ChannelMessage(
            origin.channel,
            origin.speaker,
            task,
            language=origin.language,
            metadata={"delegated": True, "internal": True},
        )
        context = [
            *self.dialogue.context_view(
                conversation, agent.profile.name, 2000, limit=8, name=self._label
            ),
            LLMMessage("user", f"Task from the main agent: {task}"),
        ]
        parts: list[str] = []
        async for event in agent.run(message, context=context):
            if event.kind == "text":
                parts.append(event.text)
            elif event.kind == "error":
                parts.append(f"(error: {event.error})")
        text = "".join(parts).strip()
        self.dialogue.append(
            DialogueMessage(
                origin.channel,
                agent.profile.name,
                "internal",
                f"{agent.profile.name} result for {task[:80]!r}: {text}",
                visibility="internal",
                agent="main",
                reply_to=origin.id,
                conversation=conversation,
            )
        )
        return text

    async def _run_delegation(
        self, agent: Agent, task: str, origin: ChannelMessage, task_id: str
    ) -> None:
        try:
            result = await asyncio.wait_for(
                self._collect(agent, task, origin), agent.profile.timeout_s
            )
        except Exception as exc:
            result = f"(failed: {exc!r})"
        finally:
            self._background.pop(task_id, None)
            self._background_meta.pop(task_id, None)
        Log.info(f"background delegation {task_id} ({agent.profile.name}) finished")
        self._note("agent", f"{agent.profile.name} finished in the background: {task[:60]}")
        follow = ChannelMessage(
            origin.channel,
            origin.speaker,
            f"[internal] Subagent {agent.profile.name} finished the task {task[:80]!r}: {result}. "
            "Relay the outcome to the person in one or two sentences.",
            language=origin.language,
            metadata={
                "internal": True,
                "task_id": task_id,
                "conversation": origin.metadata.get("conversation"),
                "private": origin.metadata.get("private", False),
            },
        )
        text = await self._reply_text(follow, record_user=False, record_reply=False)
        if text:  # `deliver` records the reply once, with where it went
            await self.deliver(text, "auto", origin.channel, origin.speaker)

    async def _reply_text(
        self, message: ChannelMessage, record_user: bool = True, record_reply: bool = True
    ) -> str:
        parts: list[str] = []
        async for event in self.run_main(
            message, record_user=record_user, record_reply=record_reply
        ):
            if event.kind == "text":
                parts.append(event.text)
        return "".join(parts).strip()

    # ------------------------------------------------------- unprompted turns

    async def run_job_turn(
        self, prompt: str, owner: str, channel: str, delivery: str, job_id: str
    ) -> str | None:
        """One main-agent turn on an automation's prompt, delivered by policy.

        Returns what was said, or None for `NO_REPLY` (nothing delivered, nothing recorded).
        """
        message = ChannelMessage(
            channel,
            owner,
            prompt,
            language=self.default_language,
            metadata={"job": job_id, "internal": True},
        )
        text = await self._reply_text(message, record_user=False, record_reply=False)
        if not text or text.strip().startswith(NO_REPLY):
            return None
        await self.deliver(text, delivery, channel, owner)
        return text

    def delivered_since(self, ts: float) -> list[tuple[float, str]]:
        """What Banana delivered on its own initiative since `ts`, oldest first, tags removed."""
        return [
            (row.ts, PERFORMANCE_TAG.sub("", row.content).strip())
            for row in self.dialogue.since(ts, role="assistant", limit=5000)
            if row.meta.get("delivery")
        ]

    async def deliver(self, text: str, delivery: str, channel: str, speaker: str) -> bool:
        """Delivery policy (AGENTS.md): in_person / remote / both / auto."""
        spoken = sent = False
        want_voice = delivery in ("in_person", "both") or (delivery == "auto" and self.can_speak())
        if want_voice and self.say is not None:
            try:
                spoken = await self.say(text, None) is not False
            except Exception as exc:
                Log.warning(f"deliver: say failed: {exc!r}")
        remote_channel = channel if channel != "voice" else None
        if delivery in ("remote", "both") or (delivery == "auto" and not spoken):
            if remote_channel is not None:
                sent = await ChannelSession.shared.send(
                    ChannelReply(text, channel=remote_channel, to=speaker)
                )
            elif not spoken and self.say is not None:
                try:
                    spoken = await self.say(text, None) is not False
                except Exception as exc:
                    Log.warning(f"deliver: say fallback failed: {exc!r}")
        where_key = conversation_key("voice", "") if spoken or remote_channel is None else None
        if where_key is None and sent and remote_channel is not None:
            where_key = conversation_key(remote_channel, speaker)
        self.dialogue.append(
            DialogueMessage(
                channel,
                "main",
                "assistant",
                text,
                agent="main",
                delivered_to=("voice" if spoken else "")
                + ("," if spoken and sent else "")
                + (remote_channel or "" if sent else ""),
                meta={"delivery": delivery},
                conversation=self.dialogue.conversation_for(where_key) if where_key else None,
            )
        )
        if not spoken and not sent:
            Log.warning(
                f"deliver: no channel for {delivery!r} ({channel}); message kept on the timeline"
            )
        where = ("voice" if spoken else "") + ("," if spoken and sent else "")
        where += remote_channel or "" if sent else ""
        self._note(
            "agent",
            f"delivered ({delivery}) → {where or 'nowhere'}: {PERFORMANCE_TAG.sub('', text)[:60]}",
            "info" if spoken or sent else "warn",
        )
        return spoken or sent

    # --------------------------------------------------------------- reporting

    def _label(self, speaker: str) -> str:
        if self.contacts is not None and getattr(self.contacts, "ready", False):
            try:
                return str(self.contacts.display_name(speaker))
            except Exception:
                return speaker
        return speaker

    def _note(self, module: str, text: str, level: str = "info") -> None:
        self._activity.append({"ts": time.time(), "module": module, "text": text, "level": level})

    def _count(self, key: str, by: int = 1) -> None:
        day = time.strftime("%Y-%m-%d")
        if self._today["day"] != day:
            self._today = {"day": day, "turns": 0, "tools": 0, "tool_errors": 0}
        self._today[key] += by

    def turn_begin(self, message: ChannelMessage, agent: str) -> None:
        """An agent starts a turn on `message` (the Live page follows it)."""
        meta = message.metadata
        self.inflight[message.id] = {
            "id": message.id,
            "agent": agent,
            "channel": message.channel,
            "speaker": self._label(message.speaker),
            "text": message.text[:120],
            "kind": "job" if meta.get("job") else "internal" if meta.get("internal") else "turn",
            "started": time.time(),
            "_t0": time.monotonic(),
            "step": 0,
            "state": "thinking",
            "tool": None,
            "first_token_ms": None,
            "tools": [],
            "said": "",
        }
        if agent == "main" and not meta.get("internal"):
            self._count("turns")

    def turn_step(self, message_id: str, kind: str, data: dict[str, Any]) -> None:
        """A model step, a tool about to run, or a tool result of a turn in flight."""
        turn = self.inflight.get(message_id)
        if turn is None:
            return
        if kind == "llm":
            turn["step"] = int(data.get("step", 0)) + 1
            turn["state"] = "thinking"
            turn["tool"] = None
        elif kind == "tool_start":
            turn["state"] = "tool"
            turn["tool"] = data.get("tool")
            turn["tools"].append(
                {"tool": data.get("tool"), "ok": None, "_t0": time.monotonic(), "ms": None}
            )
        elif kind == "tool":
            ok = bool(data.get("ok"))
            for call in reversed(turn["tools"]):
                if call["tool"] == data.get("tool") and call["ok"] is None:
                    call["ok"] = ok
                    call["ms"] = round((time.monotonic() - call["_t0"]) * 1000)
                    break
            self._count("tools")
            if not ok:
                self._count("tool_errors")
            self._note(
                "agent",
                f"{turn['agent']} · {data.get('tool')} {'ok' if ok else 'failed'}: "
                f"{str(data.get('content', ''))[:60]}",
                "info" if ok else "warn",
            )

    def turn_text(self, message_id: str, text: str) -> None:
        """Reply text of a turn in flight (the first one sets its first token)."""
        turn = self.inflight.get(message_id)
        if turn is None:
            return
        if turn["first_token_ms"] is None:
            turn["first_token_ms"] = round((time.monotonic() - turn["_t0"]) * 1000)
        turn["state"] = "speaking"
        turn["said"] = (turn["said"] + text)[-200:]

    def turn_end(self, message_id: str, outcome: str) -> None:
        """A turn finished (`done`, `no_reply`, `error` or `cancelled`)."""
        turn = self.inflight.pop(message_id, None)
        if turn is None:
            return
        total = round((time.monotonic() - turn["_t0"]) * 1000)
        record = {
            "ts": time.time(),
            "agent": turn["agent"],
            "channel": turn["channel"],
            "speaker": turn["speaker"],
            "kind": turn["kind"],
            "text": turn["text"][:80],
            "said": PERFORMANCE_TAG.sub("", turn["said"]).strip()[:120],
            "first_token_ms": turn["first_token_ms"],
            "total_ms": total,
            "steps": turn["step"],
            "tools": [{"tool": c["tool"], "ok": c["ok"], "ms": c["ms"]} for c in turn["tools"]],
            "outcome": outcome,
        }
        self.recent_turns.append(record)
        first = f"first token {turn['first_token_ms']} ms · " if turn["first_token_ms"] else ""
        self._note(
            "agent",
            f"{turn['agent']} {turn['kind']} ({turn['channel']}, {turn['speaker']}): "
            f"{outcome} · {first}{total} ms",
            "warn" if outcome in ("error", "cancelled") else "info",
        )

    def live(self) -> dict[str, Any]:
        """Vital signs for the Live page, from memory only (block #69)."""
        now = time.time()
        mono = time.monotonic()
        main_turns = [
            t for t in self.recent_turns if t["agent"] == "main" and t["first_token_ms"] is not None
        ]
        firsts = [t["first_token_ms"] for t in main_turns[-20:]]
        if self._today["day"] != time.strftime("%Y-%m-%d"):
            self._count("turns", 0)
        return {
            "inflight": [
                {
                    "id": t["id"],
                    "agent": t["agent"],
                    "channel": t["channel"],
                    "speaker": t["speaker"],
                    "kind": t["kind"],
                    "text": t["text"],
                    "state": t["state"],
                    "step": t["step"],
                    "tool": t["tool"],
                    "age_ms": round((mono - t["_t0"]) * 1000),
                    "first_token_ms": t["first_token_ms"],
                    "tools": [
                        {"tool": c["tool"], "ok": c["ok"], "ms": c["ms"]} for c in t["tools"]
                    ],
                    "said": t["said"][-120:],
                }
                for t in self.inflight.values()
            ],
            "last": self.recent_turns[-1] if self.recent_turns else None,
            "last_turn": next(  # the newest turn someone took (not a job or an internal relay)
                (t for t in reversed(self.recent_turns) if t["kind"] == "turn"), None
            ),
            "today": {k: v for k, v in self._today.items() if k != "day"},
            "first_token_median_ms": round(statistics.median(firsts)) if firsts else None,
            "background": [
                {**meta, "id": task_id, "age_s": round(now - meta["started"], 1)}
                for task_id, meta in self._background_meta.items()
            ],
            "parked": self.gate.parked(),
            "last_error": self.last_error,
            "agents": len(self.agents),
            "tools": len(self.registry.names()),
        }

    def memory_live(self) -> dict[str, Any]:
        """The memory card of the Live page (counts at most every 30 s, the newest items)."""
        counts = self._store_counts() if self._stores_ready else {}
        newest = self._newest_fact()
        return {
            "facts": counts.get("memory"),
            "episodes": counts.get("episodes"),
            "scopes": counts.get("scopes"),
            "digests": counts.get("digests"),
            "last_fact": newest,
            "last_episode": None
            if not counts.get("last_episode")
            else {
                **counts["last_episode"],
                "ago_s": round(time.time() - counts["last_episode"]["ts"]),
            },
            "writer": self.writer.live() if self.writer is not None else None,
        }

    def _last_episode(self) -> dict[str, Any] | None:
        episodes = self.memory.episodes(limit=1)
        if not episodes:
            return None
        return {"title": episodes[0].title, "ts": episodes[0].ts_end}

    def _newest_fact(self) -> dict[str, Any] | None:
        now = time.monotonic()
        if self._newest is None or now - self._newest[0] > 30.0:
            rows = self.memory.all(limit=1) if self._stores_ready else []
            fact = rows[0] if rows else None
            self._newest = (
                now,
                None
                if fact is None
                else {"text": fact.text[:80], "scope": fact.scope, "ts": fact.ts},
            )
        value = self._newest[1]
        return None if value is None else {**value, "ago_s": round(time.time() - value["ts"])}

    def activity(self, since: float = 0.0, limit: int = 50) -> list[dict[str, Any]]:
        """Newest agent activity (turns, tools, deliveries, background work, memory writes)."""
        rows = [row for row in reversed(self._activity) if row["ts"] > since][:limit]
        if self.writer is not None:
            rows += self.writer.activity(since, limit)
            rows.sort(key=lambda row: row["ts"], reverse=True)
        return rows[:limit]

    def snapshot(self) -> dict[str, Any]:
        """Dashboard state."""
        return {
            "agents": {
                name: {
                    "slot": a.profile.llm_slot,
                    "turns": a.turns,
                    "tools": len(self.tools_for(a.profile)),
                    "description": a.profile.description,
                    "origin": a.profile.origin,
                }
                for name, a in self.agents.items()
            },
            "tools": self.registry.names(),
            "llm_slots": self.llm.slots(),
            "turns": self.turns,
            "pending_async": sorted(self._background),
            "counts": self._store_counts() if self._stores_ready else {},
            "last_error": self.last_error,
        }

    def _store_counts(self) -> dict[str, Any]:
        """Row counts of the stores, queried at most every 30 s (the health poll is 1 Hz)."""
        now = time.monotonic()
        if self._counts is None or now - self._counts[0] > 30.0:
            self._counts = (
                now,
                {
                    "dialogue": self.dialogue.count(),
                    "memory": self.memory.count(),
                    "episodes": self.memory.episode_count(),
                    "scopes": len(self.memory.scopes()),
                    "digests": len(self.memory.digests()),
                    "last_episode": self._last_episode(),
                    "skills": len(self.skills.list()),
                    "mcp": len(self.mcp_registry.list()),
                },
            )
        return self._counts[1]
