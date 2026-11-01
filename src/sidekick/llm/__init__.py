"""sidekick.llm — LLM service: slots, backend protocol, OpenAI-compatible backend, trace."""

from .llm import LLMSession
from .schemas import (
    LLMBackend,
    LLMInferOptions,
    LLMMessage,
    LLMResult,
    LLMStreamEvent,
    LLMToolCall,
    LLMToolSpec,
    LLMUsage,
)
from .v1_chat_completion import LLMV1ChatCompletionBackend, LLMV1ChatCompletionConfiguration

__all__ = [
    "LLMBackend",
    "LLMInferOptions",
    "LLMMessage",
    "LLMResult",
    "LLMSession",
    "LLMStreamEvent",
    "LLMToolCall",
    "LLMToolSpec",
    "LLMUsage",
    "LLMV1ChatCompletionBackend",
    "LLMV1ChatCompletionConfiguration",
]
