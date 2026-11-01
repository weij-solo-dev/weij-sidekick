"""sidekick.agent — self-built agent runtime: swarm, tool protocol, timeline, memory, skills, MCP."""

from .agent import MAIN_ROLE, Agent, AgentSession
from .dialogue import DialogueStore
from .loop import ReActLoop
from .mcp import MCPClientPool, MCPRegistry
from .memory import MemoryStore
from .schemas import (
    HOUSEHOLD,
    NO_REPLY,
    AgentEvent,
    AgentProfile,
    AgentReplyEvent,
    DialogueMessage,
    MCPServer,
    MemoryEpisode,
    MemoryFact,
    Skill,
    Tool,
    ToolContext,
    ToolResult,
)
from .skills import SkillStore, parse_markdown, render_markdown
from .tools import ConfirmationGate, ToolRegistry, is_affirmative, is_negative

__all__ = [
    "HOUSEHOLD",
    "MAIN_ROLE",
    "NO_REPLY",
    "Agent",
    "AgentEvent",
    "AgentProfile",
    "AgentReplyEvent",
    "AgentSession",
    "ConfirmationGate",
    "DialogueMessage",
    "DialogueStore",
    "MCPClientPool",
    "MCPRegistry",
    "MCPServer",
    "MemoryEpisode",
    "MemoryFact",
    "MemoryStore",
    "ReActLoop",
    "Skill",
    "SkillStore",
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "is_affirmative",
    "is_negative",
    "parse_markdown",
    "render_markdown",
]
