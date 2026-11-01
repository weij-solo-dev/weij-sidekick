"""sidekick.llm.schemas — messages, tools, results and the backend protocol

Overview
    The vendor-neutral shapes the agent speaks: chat messages with tool calls, tool specs as JSON
    schema, a fully populated `LLMResult` (invariant 4) and the streaming event type.
Design
    Frozen dataclasses with `to_openai()` helpers, because every vendor sidekick targets first
    speaks the OpenAI chat-completions dialect. `LLMResult.api_code` carries the vendor's own
    in-body code (MiniMax `base_resp.status_code`) separately from the HTTP status, and content
    refusals are detected from codes/tokens rather than prose, exactly as in Scoop.
Depends on
    stdlib only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class LLMToolSpec:
    """A function tool offered to the model."""

    name: str
    description: str
    parameters: Mapping[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    def to_openai(self) -> dict[str, Any]:
        """OpenAI `tools[]` entry."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.parameters),
            },
        }


@dataclass(frozen=True, slots=True)
class LLMToolCall:
    """A tool invocation requested by the model; `arguments` is the raw JSON string."""

    id: str
    name: str
    arguments: str

    def to_openai(self) -> dict[str, Any]:
        """OpenAI `tool_calls[]` entry."""
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass(frozen=True, slots=True)
class LLMMessage:
    """One chat message."""

    role: Role
    content: str | None = None
    tool_calls: tuple[LLMToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None

    def to_openai(self) -> dict[str, Any]:
        """OpenAI `messages[]` entry."""
        message: dict[str, Any] = {
            "role": self.role,
            "content": self.content if self.content is not None else "",
        }
        if self.tool_calls:
            message["tool_calls"] = [call.to_openai() for call in self.tool_calls]
        if self.tool_call_id is not None:
            message["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            message["name"] = self.name
        return message


@dataclass(frozen=True, slots=True)
class LLMUsage:
    """Token accounting as reported by the vendor."""

    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cached_tokens: int | None = None  # of the prompt, read from the vendor's prefix cache


@dataclass(frozen=True, slots=True)
class LLMInferOptions:
    """Per-call overrides; the preset carries the fixed part."""

    max_tokens: int | None = None
    temperature: float | None = None
    tools: tuple[LLMToolSpec, ...] = ()
    tool_choice: str | None = None
    extra_body: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LLMResult:
    """Everything a caller or a trace row needs about one inference."""

    success: bool
    output: str | None
    provider: str
    api: str
    model: str
    api_key_hint: str
    tool_calls: tuple[LLMToolCall, ...] = ()
    finish_reason: str | None = None
    reasoning: str | None = None
    usage: LLMUsage | None = None
    status_code: int | None = None
    api_code: int | None = None
    error_message: str | None = None
    latency_ms: float | None = None
    first_token_ms: float | None = None  # streaming: request sent → first text delta

    _content_rejection_codes = frozenset({1026, 1027})
    _content_rejection_tokens = (
        "data_inspection_failed",
        "content_policy_violation",
        "sensitivecontentdetected",
        "prohibited_content",
        "new_sensitive",
    )

    @property
    def is_content_rejected(self) -> bool:
        """The vendor refused the input or its own output on policy grounds."""
        if self.api_code is not None and self.api_code in self._content_rejection_codes:
            return True
        if self.finish_reason == "content_filter":
            return True
        message = (self.error_message or "").lower()
        return any(token in message for token in self._content_rejection_tokens)


@dataclass(frozen=True, slots=True)
class LLMStreamEvent:
    """One streaming event of a completion.

    `start` (once, with the first delta of any kind: what a hedged call races on), a text or
    reasoning delta, a completed tool call, or the final result.
    """

    kind: Literal["start", "text", "reasoning", "tool_call", "done"]
    text: str = ""
    tool_call: LLMToolCall | None = None
    result: LLMResult | None = None


class LLMBackend(Protocol):
    """What every LLM backend implements."""

    async def infer(self, messages: list[LLMMessage], options: LLMInferOptions) -> LLMResult:
        """One blocking completion."""
        ...

    def stream(
        self, messages: list[LLMMessage], options: LLMInferOptions
    ) -> AsyncIterator[LLMStreamEvent]:
        """Streaming completion; the last event is `done` with the full `LLMResult`."""
        ...
