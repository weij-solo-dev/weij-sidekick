"""sidekick.automation.tools — the main agent's scheduling tools

Overview
    `schedule` turns a request ("八點提我食藥", "every morning at eight, the news", "when someone
    comes home, tell me") into a job; `jobs_list` and `job_cancel` show and remove the user's
    own jobs (built-in jobs are never listed or cancelled from a conversation).
Design
    The tools implement the agent's tool protocol (`Tool`, `ToolResult`, `ToolContext`) and are
    `main_only`: creating, cancelling and running jobs belongs to the main agent alone, which is
    in the conversation the request came from — subagents are experts for one domain and never
    see these tools, whatever their allowlist says (invariant 22). A job's owner and channel are
    the caller's speaker and channel, so its reminder goes back where it was asked for
    (invariant 14). The façade registers them into the agent in `setup` and withdraws them when
    `automation.enabled` is off.
Depends on
    sidekick.agent (the tool protocol).

See Also
--------
    AGENTS.md "Automations, heartbeat, delivery", "Agent swarm".

"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sidekick.agent import Tool, ToolContext, ToolResult

from .jobs import JobStore, compute_next, parse_at
from .schemas import Delivery, Job

ORIGIN = "automation"


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or []}


def automation_tools(store: JobStore) -> list[Tool]:
    """`schedule` / `jobs_list` / `job_cancel`, for the main agent only."""

    async def schedule(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        prompt = str(arguments.get("prompt", "")).strip()
        name = str(arguments.get("name", "")).strip() or prompt[:40]
        when = str(arguments.get("when", "")).strip()
        cron = str(arguments.get("cron", "")).strip()
        event = str(arguments.get("event", "")).strip()
        delivery = cast(
            Delivery,
            str(arguments.get("delivery", "auto"))
            if arguments.get("delivery") in ("in_person", "remote", "both", "auto")
            else "auto",
        )
        if not prompt:
            return ToolResult.error("prompt is required: what to say or do when it fires")
        try:
            if event:
                job = Job(
                    name,
                    "event",
                    event,
                    prompt,
                    delivery=delivery,
                    owner=ctx.speaker,
                    channel=ctx.channel,
                )
                saved = store.save(job)
                return ToolResult(
                    True, f"will run {saved.name!r} whenever {event} happens", {"id": saved.id}
                )
            if cron:
                job = Job(
                    name,
                    "cron",
                    cron,
                    prompt,
                    delivery=delivery,
                    owner=ctx.speaker,
                    channel=ctx.channel,
                )
                if compute_next(job) is None:
                    return ToolResult.error("cron expression never matches")
            elif when:
                target = parse_at(when)
                job = Job(
                    name,
                    "at",
                    target.isoformat(timespec="minutes"),
                    prompt,
                    delivery=delivery,
                    owner=ctx.speaker,
                    channel=ctx.channel,
                )
            else:
                return ToolResult.error("give either `when` (HH:MM or ISO time) or `cron`")
        except ValueError as exc:
            return ToolResult.error(f"bad schedule: {exc}")
        saved = store.save(job)
        when_text = (
            datetime.fromtimestamp(saved.next_run_ts).strftime("%Y-%m-%d %H:%M")
            if saved.next_run_ts
            else "never"
        )
        return ToolResult(
            True,
            f"scheduled {saved.name!r}, next run {when_text}",
            {"id": saved.id, "next": saved.next_run_ts},
        )

    async def jobs_list(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        jobs = [j for j in store.list_jobs() if not j.builtin]
        if not jobs:
            return ToolResult(True, "no scheduled jobs")
        lines = []
        for j in jobs:
            nxt = (
                datetime.fromtimestamp(j.next_run_ts).strftime("%m-%d %H:%M")
                if j.next_run_ts
                else "-"
            )
            lines.append(
                f"- {j.id[:8]} {j.name} [{j.trigger_kind} {j.trigger}] next {nxt} state {j.state}: {j.prompt[:60]}"
            )
        return ToolResult(True, "\n".join(lines))

    async def job_cancel(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        ref = str(arguments.get("id", "")).strip()
        target = None
        for j in store.list_jobs(include_done=True):
            if j.builtin:
                continue
            if j.id == ref or j.id.startswith(ref) or j.name == ref:
                target = j
                break
        if target is None:
            return ToolResult.error("no such job")
        store.delete(target.id)
        return ToolResult(True, f"cancelled {target.name!r}")

    return [
        Tool(
            "schedule",
            "Create a reminder or recurring task. Use `when` (HH:MM today/tomorrow, or ISO datetime) for one-shot, `cron` (5 fields) for recurring, or `event` (presence.enter, presence.leave, face.seen, audio.speech, feed.update, job.done) to react to something the robot notices. `prompt` is what to say or do when it fires.",
            _schema(
                {
                    "prompt": {"type": "string"},
                    "when": {"type": "string"},
                    "cron": {"type": "string"},
                    "event": {"type": "string"},
                    "name": {"type": "string"},
                    "delivery": {"type": "string", "enum": ["in_person", "remote", "both", "auto"]},
                },
                ["prompt"],
            ),
            schedule,
            origin=ORIGIN,
            main_only=True,
        ),
        Tool(
            "jobs_list",
            "List scheduled reminders and tasks.",
            _schema({}),
            jobs_list,
            origin=ORIGIN,
            main_only=True,
        ),
        Tool(
            "job_cancel",
            "Cancel a scheduled job by id prefix or name.",
            _schema({"id": {"type": "string"}}, ["id"]),
            job_cancel,
            origin=ORIGIN,
            main_only=True,
        ),
    ]
