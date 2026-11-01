"""sidekick.agent.loop — the ReAct loop: stream the model, run tools, repeat

Overview
    `ReActLoop.run()` drives one agent turn: call the LLM with the agent's tool schemas and
    stream text deltas out as they arrive; when the step ends with tool calls, execute them
    (confirm-gated, concurrently), append the assistant call and tool results to the working
    context (and to the timeline as `internal` rows), and re-prompt; stop on a plain reply,
    `NO_REPLY`, an error, or `max_steps`.
Design
    The loop is agnostic of who the agent is: profile, system prompt, context and tools are
    passed in; `on_step` hears each model step (`llm`), each tool about to run (`tool_start`)
    and each result (`tool`, with the step and the words the model said before its calls),
    which the agent uses for the timeline and the Live page. When nothing has been said yet on a
    voice turn of the main agent and a step's tools are still running after `ACK_AFTER_S`, a
    short spoken acknowledgement (「好，等我睇下。」) goes out (block #76): only a slow tool —
    the camera, a subagent, the network — earns one, because before every quick tool it was
    heard on nearly every reply (block #71 said it before every tool-only step). It is a
    `filler` event: spoken and kept in the transcript, never shown back to the model, which
    otherwise learned to open its own replies with it. Jobs and internal relays never get one.
    Streaming matters for the voice pipeline, so text deltas are yielded immediately even on
    steps that also carry tool calls. Tool
    arguments are JSON; a malformed payload becomes a tool error the model can recover from. A
    step that opens with `NO_REPLY` is still read to its end (its text and tool calls dropped) so
    the call reaches the trace like any other (invariant 5); breaking out early lost it.
Depends on
    sidekick.log, sidekick.llm.

See Also
--------
    AGENTS.md "Agent swarm" (ReAct loop), invariant 13.

"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from sidekick.llm import LLMInferOptions, LLMMessage, LLMSession, LLMToolCall
from sidekick.log import Log

from .schemas import NO_REPLY, REFUSAL_TEXT, AgentEvent, AgentProfile, Tool, ToolContext, ToolResult
from .tools import ConfirmationGate

StepHook = Callable[[str, dict[str, Any]], None]
# Said when a voice turn's tools are still running this long and nothing was said yet (block
# #76): local tools answer within ~0.1 s, the camera and subagents take 4-6 s; rotated.
ACK_AFTER_S = 0.4
ACKNOWLEDGEMENTS = {
    "yue": ("好，等我睇下。", "稍等吓。", "等我諗諗。"),
    "zh": ("好，我看看。", "稍等一下。", "让我想想。"),
    "en": ("Let me check.", "One moment.", "Let me think."),
}


class ReActLoop:
    """One turn of one agent."""

    def __init__(self, llm: LLMSession, gate: ConfirmationGate | None = None) -> None:
        self.llm = llm
        self.gate = gate or ConfirmationGate()

    async def run(
        self,
        profile: AgentProfile,
        system_prompt: str,
        context: list[LLMMessage],
        tools: list[Tool],
        ctx: ToolContext,
        on_step: StepHook | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Yield text deltas, tool events and a final `done` / `no_reply` / `error`."""
        by_name = {tool.name: tool for tool in tools}
        messages = [LLMMessage("system", system_prompt), *context]
        options = LLMInferOptions(
            max_tokens=profile.max_tokens,
            temperature=profile.temperature,
            tools=tuple(tool.spec() for tool in tools),
        )
        final_text: list[str] = []  # the model's own words this turn (never the filler)
        acked = False
        started = time.monotonic()
        for step in range(profile.max_steps):
            if time.monotonic() - started > profile.timeout_s:
                yield AgentEvent("error", error="agent timeout")
                return
            step_text = ""
            said = ""  # this step's words, before its tool calls
            tool_calls: list[LLMToolCall] = []
            failure: str | None = None
            refused = False
            no_reply_watch = True
            silenced = False  # NO_REPLY seen: drain the stream so the call is traced, drop the rest
            if on_step is not None:
                on_step("llm", {"step": step})
            async for event in self.llm.stream(
                profile.llm_slot,
                messages,
                options,
                task=f"agent.{profile.name}.step{step}",
                hedge_after_s=self._hedge(profile, ctx),
            ):
                if silenced:
                    continue
                if event.kind == "text":
                    step_text += event.text
                    if no_reply_watch:
                        stripped = step_text.strip()
                        if len(stripped) < len(NO_REPLY) and NO_REPLY.startswith(stripped):
                            continue
                        no_reply_watch = False
                        if stripped.startswith(NO_REPLY):
                            step_text = ""
                            silenced = True
                            continue
                        final_text.append(step_text)
                        said += step_text
                        yield AgentEvent("text", step_text)
                        step_text = ""
                        continue
                    final_text.append(event.text)
                    said += event.text
                    yield AgentEvent("text", event.text)
                elif event.kind == "tool_call" and event.tool_call is not None:
                    tool_calls.append(event.tool_call)
                elif event.kind == "done" and event.result is not None:
                    if not event.result.success:
                        failure = event.result.error_message or "llm failed"
                        refused = event.result.is_content_rejected
                    if not tool_calls and event.result.tool_calls:
                        tool_calls = list(event.result.tool_calls)
            if failure:
                if refused:
                    # The provider's content policy refused the input: answer politely instead
                    # of surfacing the error (news items about politics trip MiniMax).
                    Log.warning(f"content refused by provider: {failure[:120]}")
                    yield AgentEvent("text", REFUSAL_TEXT)
                    yield AgentEvent("done", REFUSAL_TEXT)
                    return
                yield AgentEvent("error", error=failure)
                return
            if no_reply_watch and step_text.strip().startswith(NO_REPLY):
                yield AgentEvent("no_reply")
                return
            if no_reply_watch and step_text.strip():
                final_text.append(step_text)
                said += step_text
                yield AgentEvent("text", step_text)
            if not tool_calls:
                if not "".join(final_text).strip():
                    yield AgentEvent("no_reply")
                else:
                    yield AgentEvent("done", "".join(final_text))
                return
            # Execute the tool calls, then continue the loop with their results.
            messages.append(LLMMessage("assistant", said or None, tuple(tool_calls)))
            if on_step is not None:
                for call in tool_calls:
                    on_step("tool_start", {"call_id": call.id, "tool": call.name})
            running = asyncio.ensure_future(
                asyncio.gather(*(self._execute(call, by_name, ctx) for call in tool_calls))
            )
            try:
                if not acked and not "".join(final_text).strip() and self._waiting(ctx):
                    done, _ = await asyncio.wait({running}, timeout=ACK_AFTER_S)
                    if not done:
                        acked = True
                        yield AgentEvent("text", self._acknowledgement(ctx), filler=True)
                results = await running
            finally:
                if not running.done():
                    running.cancel()
            for call, result in zip(tool_calls, results, strict=True):
                yield AgentEvent("tool_call", tool=call.name, arguments=_parse_args(call.arguments))
                yield AgentEvent("tool_result", tool=call.name, result=result)
                messages.append(
                    LLMMessage("tool", result.content, tool_call_id=call.id, name=call.name)
                )
                if on_step is not None:
                    on_step(
                        "tool",
                        {
                            "call_id": call.id,
                            "tool": call.name,
                            "arguments": call.arguments,
                            "ok": result.ok,
                            "content": result.content,
                            "needs_confirmation": result.needs_confirmation,
                            "step": step,
                            "said": said,
                        },
                    )
        yield AgentEvent("error", error=f"stopped after {profile.max_steps} steps")

    @staticmethod
    def _hedge(profile: AgentProfile, ctx: ToolContext) -> float | None:
        """A turn someone is waiting for is hedged (block #78); a job or a relay is not."""
        meta = ctx.message.metadata
        if profile.hedge_after_s <= 0 or meta.get("job") or meta.get("internal"):
            return None
        return profile.hedge_after_s

    @staticmethod
    def _waiting(ctx: ToolContext) -> bool:
        """Someone is in the room waiting for the main agent (not a job, relay or subagent)."""
        meta = ctx.message.metadata
        return (
            ctx.agent == "main"
            and ctx.message.channel == "voice"
            and not meta.get("job")
            and not meta.get("internal")
        )

    def _acknowledgement(self, ctx: ToolContext) -> str:
        language = ctx.message.language or getattr(ctx.session, "default_language", "yue")
        options = ACKNOWLEDGEMENTS.get(str(language), ACKNOWLEDGEMENTS["yue"])
        self._acks = getattr(self, "_acks", 0) + 1
        return options[self._acks % len(options)]

    async def _execute(
        self, call: LLMToolCall, by_name: dict[str, Tool], ctx: ToolContext
    ) -> ToolResult:
        tool = by_name.get(call.name)
        if tool is None:
            return ToolResult.error(f"unknown tool {call.name!r}")
        arguments = _parse_args(call.arguments)
        if arguments is None:
            return ToolResult.error("arguments must be a JSON object")
        if tool.confirm and not (ctx.confirmed or arguments.get("confirmed") is True):
            return self.gate.request(ctx, tool, arguments)
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(tool.handler(arguments, ctx), timeout=60.0)
        except TimeoutError:
            result = ToolResult.error(f"{tool.name} timed out")
        except Exception as exc:
            Log.error(f"tool {tool.name} raised: {exc!r}")
            result = ToolResult.error(f"{tool.name} failed: {exc!r}")
        Log.info(
            f"tool {tool.name} by {ctx.agent}: {'ok' if result.ok else 'failed'} in {(time.monotonic() - started) * 1000:.0f} ms: {result.content[:80]!r}"
        )
        return result


def _parse_args(raw: str) -> dict[str, Any] | None:
    if not raw or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None
