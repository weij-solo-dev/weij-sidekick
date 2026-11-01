"""sidekick.agent.schemas — profiles, the tool protocol, timeline rows, memory, skills, MCP, events

Overview
    Every record type of the agent runtime in one place: `AgentProfile` (who an agent is and what
    it may use), `Tool` / `ToolContext` / `ToolResult` (the tool protocol other modules implement:
    `automation`, the extensions), `DialogueMessage` (one timeline row), `MemoryFact` and
    `MemoryEpisode` (the memory pyramid's L2 and L1), `Skill`,
    `MCPServer` and `AgentEvent` (what a streaming turn yields).
Design
    Frozen dataclasses with `slots`; stores serialise them to SQLite rows and back. `Tool.spec()`
    renders the OpenAI-style function schema the LLM backends expect. Tool handlers are async and
    receive a `ToolContext` carrying the inbound message, the calling agent and whether the user
    already confirmed a sensitive action (invariant 13). A `main_only` tool is never handed to a
    subagent, whatever its allowlist says (`delegate`, the scheduling tools).
Depends on
    sidekick.channel, sidekick.llm.

See Also
--------
    AGENTS.md "Agent swarm", "Dialogue and memory", "Automations, heartbeat, delivery".

"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from sidekick.channel import ChannelMessage
from sidekick.llm import LLMToolSpec

NO_REPLY = "NO_REPLY"
REFUSAL_TEXT = "呢個話題我唔方便講，講下其他嘢好唔好？"
HOUSEHOLD = "household"


def new_id() -> str:
    """Random row id."""
    return uuid.uuid4().hex


@dataclass(frozen=True, slots=True)
class AgentProfile:
    """One agent's identity and scope."""

    name: str
    role: str
    llm_slot: str = "fast"
    description: str = ""
    tools: tuple[str, ...] = ("*",)
    mcp_servers: tuple[str, ...] = ("*",)
    skills: tuple[str, ...] = ("*",)
    memory_scope: str = HOUSEHOLD
    max_steps: int = 6
    timeout_s: float = 60.0
    max_history: int = 12
    max_tokens: int = 500
    temperature: float = 0.7
    context_chars: int = 6000
    # Ask the model again when its answer has not started after this long, on turns someone is
    # waiting for (block #78); 0 = never.
    hedge_after_s: float = 0.0
    extra: dict[str, str] = field(default_factory=dict)
    # Who defined it: `core` (the main agent), `user` (config / the dashboard's Subagents view),
    # `extension:<name>` (an extension's subagent, gone when the extension is disabled).
    origin: str = "user"

    def allows(self, allowlist: tuple[str, ...], name: str) -> bool:
        """Allowlist semantics: `*` means everything."""
        return "*" in allowlist or name in allowlist


@dataclass(frozen=True, slots=True)
class AgentReplyEvent:
    """One event of a streaming reply (kept for the voice pipeline)."""

    kind: Literal["text", "done", "no_reply", "error"]
    text: str = ""
    error: str | None = None


@dataclass(slots=True)
class ToolContext:
    """What a tool handler may know about its caller."""

    message: ChannelMessage
    agent: str
    confirmed: bool = False
    session: Any = None

    @property
    def speaker(self) -> str:
        """Who is talking."""
        return self.message.speaker

    @property
    def channel(self) -> str:
        """Where the turn came from."""
        return self.message.channel

    @property
    def conversation_key(self) -> str:
        """Key for per-conversation state such as pending confirmations."""
        return f"{self.message.channel}:{self.message.speaker}"


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool returns."""

    ok: bool
    content: str
    data: dict[str, Any] | None = None
    needs_confirmation: bool = False
    expression: str | None = None

    @staticmethod
    def error(message: str) -> ToolResult:
        """A failed call."""
        return ToolResult(False, message)


ToolHandler = Callable[[dict[str, Any], ToolContext], Awaitable[ToolResult]]


@dataclass(frozen=True, slots=True)
class Tool:
    """A callable the LLM may invoke."""

    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: ToolHandler
    confirm: bool = False
    origin: str = "core"
    main_only: bool = False

    def spec(self) -> LLMToolSpec:
        """OpenAI-style function schema."""
        return LLMToolSpec(self.name, self.description, dict(self.parameters))


@dataclass(frozen=True, slots=True)
class DialogueMessage:
    """One row of the timeline (invariant 12)."""

    channel: str
    speaker: str
    role: Literal["user", "assistant", "tool", "internal"]
    content: str
    id: str = field(default_factory=new_id)
    ts: float = field(default_factory=time.time)
    visibility: Literal["public", "private", "internal"] = "public"
    agent: str | None = None
    reply_to: str | None = None
    attachments: tuple[str, ...] = ()
    delivered_to: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    conversation: str | None = None  # L0: the conversation this row belongs to (block #70)


@dataclass(frozen=True, slots=True)
class MemoryFact:
    """One L2 fact: a short sentence about a contact or the household, with its provenance.

    `scope` is whose profile it belongs to (a contact id or `household`), `subject` who it is
    about, `teller` who said it; `visibility` `private` means only the teller sees it;
    `origin` is `explicit` (the remember tool, the dashboard) or `inferred` (the memory
    writer). A superseded or expired fact keeps its row (`superseded_by`, `retired_ts`).
    """

    scope: str
    text: str
    id: str = field(default_factory=new_id)
    ts: float = field(default_factory=time.time)
    subject: str | None = None
    teller: str | None = None
    channel: str | None = None
    visibility: Literal["public", "private"] = "public"
    origin: Literal["explicit", "inferred"] = "explicit"
    category: str = "other"
    valid_until: str | None = None  # YYYY-MM-DD: no longer true after that day
    sources: tuple[str, ...] = ()  # timeline row ids
    episode: str | None = None
    updated_ts: float | None = None
    superseded_by: str | None = None  # a fact id, or `expired` / `merged`
    retired_ts: float | None = None

    @property
    def active(self) -> bool:
        """Not superseded, expired or merged."""
        return self.retired_ts is None

    @property
    def source_id(self) -> str | None:
        """The first source row (older callers)."""
        return self.sources[0] if self.sources else None


@dataclass(frozen=True, slots=True)
class MemoryEpisode:
    """One L1 episode: what one conversation was about, written by the memory writer."""

    conversation: str
    channel: str
    ts_start: float
    ts_end: float
    title: str
    summary: str
    participants: tuple[str, ...] = ()
    visibility: Literal["public", "private"] = "public"
    private_to: str | None = None
    followups: tuple[dict[str, str], ...] = ()  # {"who", "text", "due": YYYY-MM-DD}
    rows: int = 0
    user_turns: int = 0
    upto_ts: float = 0.0  # written up to this row (a long conversation is written as it goes)
    status: Literal["ok", "failed"] = "ok"
    attempts: int = 1
    error: str | None = None
    model: str | None = None
    id: str = field(default_factory=new_id)
    written_ts: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class Skill:
    """A Markdown skill document."""

    name: str
    description: str
    body: str
    origin: str = "user"
    enabled: bool = True
    updated_ts: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class MCPServer:
    """An MCP server configuration."""

    name: str
    transport: Literal["stdio", "http"]
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    origin: str = "user"
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """What a streaming turn yields."""

    kind: Literal["text", "tool_call", "tool_result", "done", "no_reply", "error"]
    text: str = ""
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    result: ToolResult | None = None
    error: str | None = None
    filler: bool = False  # text the platform said while tools ran, not the model (block #76)
