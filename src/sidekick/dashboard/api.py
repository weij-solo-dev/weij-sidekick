"""sidekick.dashboard.api — JSON routes the dashboard page calls

Overview
    Read-mostly endpoints over the live sessions: health (with the readiness snapshot), masked
    config, body and daemon status, interaction state and decisions (with clip download),
    service traces, log tail, plus the operator actions (speak text, play an expression) and
    the Robot tab's controller under `/api/robot/*` (hold / release, pose, gestures, the
    capability tests and their files, see `robot.py`). Configuration is written per section:
    `POST /api/config/{section}` deep-merges `values` into one `ConfigSpec` section, validates,
    saves and applies live where a hook exists (`interaction`, `body.sway`, `contacts`,
    `automation`); `GET /api/config/schema` describes every field (type, bounds, choices,
    description) so the page renders its parameter cards from the pydantic models;
    `GET /api/config/providers` lists the catalog and the slot bindings for the service cards;
    credentials are write-only (`/config/credentials`), slots and languages have their own
    routes, `/config/probe` makes one real call per slot. `/api/doctor` returns the readiness
    report and `/api/doctor/run` runs its layers (block #44). Everything is loopback-only by
    construction (invariant 15) and secrets are masked before leaving.
Design
    A `DashboardContext` holds references to the sessions; routes are plain functions on a
    FastAPI `APIRouter`. No business logic here: each route calls one session method.
    `RobotControl` errors map to HTTP codes: `PermissionError` (not held) → 409,
    `BlockingIOError` (a test is running) → 409, `KeyError` → 404, `RuntimeError` (no body)
    → 409. The specific `/config/*` routes are declared before the generic section route so
    FastAPI matches them first.
    Banana's service (blocks #82–#87): `GET` / `POST /api/service`, the `service` block in
    `/api/health`; while it is stopped the runtime routes (say, test turns, the body and robot,
    frames, enrollment from the robot, the memory writer, the loopback check) answer 409
    "Banana is stopped" and writes only save (no MCP launch, no extension load, no backend
    rebind). WeChat's QR login (`/channels/wechat/login`) and the daemon's log
    (`/logs?source=daemon`) moved here from the CLI.
Depends on
    sidekick.log, sidekick.config, sidekick.body, sidekick.interaction, sidekick.agent, sidekick.llm,
    sidekick.asr, sidekick.tts, sidekick.channel, sidekick.doctor (through the context), fastapi,
    pydantic.

See Also
--------
    AGENTS.md "Dashboard and CLI".

"""

from __future__ import annotations

import asyncio
import math
import random
import re
import time
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from sidekick import __version__
from sidekick.agent import AgentSession, MCPServer
from sidekick.asr import ASRSession
from sidekick.automation import AutomationSession, Job
from sidekick.body import BodySession
from sidekick.config import LANGUAGES, SERVICES, SLOT_NAMES, ConfigSession, ConfigSpec, load_catalog
from sidekick.contact import Contact
from sidekick.interaction import InteractionSession
from sidekick.llm import LLMSession
from sidekick.log import Log
from sidekick.service import ServiceBusy
from sidekick.tts import TTSSession

from .live import MJPEG_BOUNDARY, LiveFeed, encode_jpeg, mjpeg_stream
from .replay import chunk_tracks
from .robot import RobotControl


@dataclass(slots=True)
class DashboardContext:
    """What the routes can reach."""

    config: ConfigSession
    spec: ConfigSpec
    body: BodySession | None = None
    interaction: InteractionSession | None = None
    agent: AgentSession | None = None
    automation: AutomationSession | None = None
    perception: Any = None
    channels: Any = None
    contacts: Any = None
    extensions: Any = None
    record: Any = None
    log_path: Path | None = None
    started_at: float = field(default_factory=time.time)
    extra_health: Callable[[], dict[str, Any]] | None = None
    doctor: Any = None  # DoctorSession (readiness), see sidekick.doctor
    service: Any = None  # ServiceSession (start / stop Banana), see sidekick.service


# The config sections the generic route may write; `languages` and the credentials / slots have
# their own routes because they re-apply the service backends.
CONFIG_SECTIONS = (
    "interaction",
    "body",
    "agents",
    "automation",
    "recording",
    "contacts",
    "perception",
    "robot",
    "dashboard",
)


def _merge(target: dict[str, Any], values: dict[str, Any]) -> None:
    """Deep-merge `values` into `target` (nested dicts field by field, everything else replaced)."""
    for key, value in values.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value


def _field_schema(name: str, info: FieldInfo) -> dict[str, Any] | None:
    """One field of a config section as the page's parameter-card renderer understands it."""
    annotation: Any = info.annotation
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    nullable = False
    if origin is types.UnionType or origin is typing.Union:
        inner = [a for a in args if a is not type(None)]
        nullable = len(inner) < len(args)
        annotation = inner[0]
        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)
    out: dict[str, Any] = {
        "name": name,
        "description": info.description or "",
        "nullable": nullable,
    }
    default: Any = None
    if info.default is not PydanticUndefined:
        default = info.default
    elif info.default_factory is not None:
        default = info.default_factory()  # type: ignore[call-arg]
    if origin is Literal:
        out["type"] = "enum"
        out["choices"] = list(args)
    elif annotation is bool:
        out["type"] = "boolean"
    elif annotation is int:
        out["type"] = "integer"
    elif annotation is float:
        out["type"] = "number"
    elif annotation is str:
        out["type"] = "string"
    elif origin is list:
        out["type"] = "list"
        out["items"] = "number" if args and args[0] in (float, int) else "string"
    elif origin is dict:
        if len(args) == 2 and args[1] is bool:
            out["type"] = "flags"
        else:
            return None  # subagent profiles and the like are not form fields
    elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
        out["type"] = "object"
        out["fields"] = _model_schema(annotation)
        default = None
    else:
        return None
    out["default"] = (
        default if isinstance(default, bool | int | float | str | list | dict) else None
    )
    for meta in info.metadata:
        for attr, key in (("ge", "min"), ("gt", "min"), ("le", "max"), ("lt", "max")):
            if hasattr(meta, attr):
                out[key] = getattr(meta, attr)
    return out


def _model_schema(model: type[BaseModel]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, info in model.model_fields.items():
        item = _field_schema(name, info)
        if item is not None:
            out.append(item)
    return out


class SayRequest(BaseModel):
    """Speak text through the robot."""

    text: str = Field(min_length=1, max_length=500)
    expression: str | None = None


class ExpressRequest(BaseModel):
    """Play an expression (or a gesture by name)."""

    name: str = Field(min_length=1, max_length=64)
    intensity: float = Field(default=1.0, ge=0.1, le=2.0)


class StateRequest(BaseModel):
    """Preview a state (thinking) for a few seconds."""

    name: str = Field(min_length=1, max_length=64)
    seconds: float = Field(default=6.0, ge=0.5, le=30.0)


class ControlRequest(BaseModel):
    """Take or release the body."""

    held: bool = True


class PoseRequest(BaseModel):
    """The controller's full target (radians / metres); clamped by the motion owner."""

    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    z: float = 0.0
    body_yaw: float | None = None
    antennas: tuple[float, float] | None = None
    duration_s: float = Field(default=0.4, ge=0.1, le=5.0)


class TestRequest(BaseModel):
    """Parameters of a capability test."""

    seconds: float = Field(default=3.0, ge=0.1, le=30.0)
    kind: str = Field(default="tone", max_length=16)
    freq: float = Field(default=440.0, ge=20.0, le=10000.0)


class SectionUpdate(BaseModel):
    """Partial update of one config section (nested dicts merge field by field)."""

    values: dict[str, Any]


class SkillUpdate(BaseModel):
    """Create or replace a skill from its Markdown document."""

    markdown: str = Field(min_length=1)


# The main agent's own knobs, applied at once (`AgentSession.configure_main`, block #78).
MAIN_AGENT_KNOBS = (
    "main_llm_slot",
    "main_max_steps",
    "main_max_tokens",
    "context_chars",
    "main_hedge_s",
)

# A subagent's name is what `delegate(agent=…)` takes (block #76).
SUBAGENT_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class SubagentUpdate(BaseModel):
    """Create or replace one of your subagents (`agents.subagents.<name>`, the Subagents view)."""

    description: str = ""
    role: str = Field(min_length=1)
    llm_slot: str = "smart"
    tools: list[str] = Field(default_factory=lambda: ["*"])
    mcp_servers: list[str] = Field(default_factory=lambda: ["*"])
    skills: list[str] = Field(default_factory=lambda: ["*"])
    max_steps: int = Field(default=8, ge=1, le=30)
    timeout_s: float = Field(default=120.0, ge=5.0, le=900.0)


class MCPAdd(BaseModel):
    """Add an MCP server."""

    name: str = Field(min_length=1, max_length=64)
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str = ""


class JobCreate(BaseModel):
    """Create a job from the dashboard."""

    name: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1)
    cron: str = ""
    when: str = ""
    delivery: str = "auto"


class ContactCreate(BaseModel):
    """Create or update a contact."""

    name: str = Field(min_length=1, max_length=64)
    id: str | None = None
    aliases: list[str] = Field(default_factory=list)
    language: str | None = None
    is_owner: bool = False
    notes: str = ""
    telegram: str | None = None
    wechat: str | None = None


class EnrollVoice(BaseModel):
    """Enroll a voice from listening-monitor clips."""

    contact_id: str
    clip_ids: list[str] = Field(min_length=1)


class PromoteRequest(BaseModel):
    """Befriend a person seen from the dashboard."""

    name: str = Field(min_length=1, max_length=64)
    language: str | None = None


class EnrollRecord(BaseModel):
    """Enroll a voice from a capture made right now (the Contacts flow)."""

    contact_id: str
    seconds: float = Field(default=4.0, ge=1.0, le=15.0)


class MemoryCreate(BaseModel):
    """A fact added by hand on the Memory page (an explicit fact)."""

    scope: str = Field(default="household", min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=1000)
    category: str = "other"
    private: bool = False


class ServiceAction(BaseModel):
    """Start, stop or restart Banana's service (the dashboard's power control)."""

    action: Literal["start", "stop", "restart"]


class ChatRequest(BaseModel):
    """Send a text turn to the main agent from the dashboard."""

    text: str = Field(min_length=1, max_length=2000)
    speaker: str = "owner"


class CredentialsUpdate(BaseModel):
    """Write-only credential values for one provider."""

    provider: str = Field(min_length=1, max_length=32)
    values: dict[str, str]


class SlotUpdate(BaseModel):
    """Bind one slot."""

    kind: str
    name: str
    provider: str
    model: str | None = None
    voice: str | None = None
    speed: float | None = None


class LanguagesUpdate(BaseModel):
    """Household language preferences."""

    default: str
    order: list[str] | None = None


def _tail_lines(path: Path, lines: int, chunk: int = 256_000) -> list[str]:
    """The last `lines` lines of a file that may be hundreds of MB (the daemon's log)."""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - chunk))
        data = handle.read()
    return data.decode("utf-8", errors="replace").splitlines()[-lines:]


def build_router(ctx: DashboardContext) -> APIRouter:
    """Routes bound to a context."""
    router = APIRouter(prefix="/api")

    slow: dict[str, tuple[float, Any]] = {}  # the health poll's expensive parts, kept a while

    def kept(key: str, ttl_s: float, read: Callable[[], Any]) -> Any:
        now = time.monotonic()
        hit = slow.get(key)
        if hit is None or now - hit[0] > ttl_s:
            hit = (now, read())
            slow[key] = hit
        return hit[1]

    def _running() -> None:
        """Refuse a call that needs Banana up while the service is stopped (409)."""
        if ctx.service is not None and not ctx.service.running:
            raise HTTPException(
                status_code=409, detail="Banana is stopped: start the service first"
            )

    @router.get("/service")
    def service_status() -> dict[str, Any]:
        if ctx.service is None:
            raise HTTPException(status_code=404, detail="no service in this context")
        return cast(dict[str, Any], ctx.service.status())

    @router.post("/service")
    async def service_action(
        request: ServiceAction,
    ) -> dict[str, Any]:  # on the loop: it starts a task
        if ctx.service is None:
            raise HTTPException(status_code=404, detail="no service in this context")
        try:
            return cast(dict[str, Any], ctx.service.request(request.action, by="dashboard"))
        except ServiceBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/health")
    def health() -> dict[str, Any]:
        # Polled every second by every open page: the daemon's HTTP status, the recording
        # totals (a walk over every chunk) and the contacts (SQL per contact) are kept a while.
        body = ctx.body.status() if ctx.body is not None else None
        daemon = (
            ctx.body.daemon.cached_status() if ctx.body is not None and ctx.body.daemon else None
        )
        out: dict[str, Any] = {
            "version": __version__,
            "uptime_s": round(time.time() - ctx.started_at, 1),
            "home": str(ctx.config.storage.layout.home),
            "doctor": ctx.doctor.snapshot() if ctx.doctor is not None else None,
            "slots": {
                f"{kind}.{name}": f"{slot.provider}" for kind, name, slot in ctx.spec.bound_slots()
            },
            "ready": {
                "llm": LLMSession.shared.slots(),
                "asr": ASRSession.shared.slots(),
                "tts": TTSSession.shared.slots(),
            },
            "body": None
            if body is None
            else {
                "state": body.state.value,
                "daemon_state": body.daemon_state,
                "motor_mode": body.motor_mode,
                "robot_name": body.robot_name,
                "version": body.version,
                "simulated": body.simulated,
                "error": body.error,
                "speaking": ctx.body.is_speaking() if ctx.body is not None else False,
                "input_level_dbfs": round(ctx.body.input_level_dbfs(), 1)
                if ctx.body is not None
                else None,
            },
            "daemon": None
            if daemon is None
            else {"line": daemon.line(), "running": daemon.running, "pid": daemon.pid},
            "interaction": ctx.interaction.snapshot() if ctx.interaction is not None else None,
            "agent": ctx.agent.snapshot() if ctx.agent is not None else None,
            "automation": ctx.automation.status() if ctx.automation is not None else None,
            "perception": ctx.perception.snapshot() if ctx.perception is not None else None,
            "contacts": kept("contacts", 10.0, ctx.contacts.snapshot)
            if ctx.contacts is not None and ctx.contacts.ready
            else None,
            "recording": ctx.record.cached_status().as_dict() if ctx.record is not None else None,
            "service": ctx.service.status() if ctx.service is not None else None,
        }
        if ctx.extra_health is not None:
            out.update(ctx.extra_health())
        return out

    @router.get("/config")
    def config() -> dict[str, Any]:
        return ctx.spec.masked()

    @router.get("/config/describe")
    def describe() -> list[str]:
        return ctx.config.describe(ctx.spec)

    @router.get("/config/schema")
    def config_schema() -> dict[str, Any]:
        out: dict[str, Any] = {}
        for section in (*CONFIG_SECTIONS, "languages"):
            model = ConfigSpec.model_fields[section].annotation
            assert isinstance(model, type) and issubclass(model, BaseModel)
            out[section] = _model_schema(model)
        return out

    @router.get("/config/providers")
    def config_providers() -> dict[str, Any]:
        spec = ctx.spec
        shared: dict[str, list[str]] = {}
        for kind, name, slot in spec.bound_slots():
            shared.setdefault(slot.provider, []).append(f"{kind}.{name}")
        providers = []
        for p in load_catalog().values():
            services = [k for k in SERVICES if p.service(k)]
            have = spec.credentials.get(p.id, {})
            providers.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "console_url": p.console_url,
                    "credentials": p.credential_fields(),
                    "configured": all(have.get(f) for f in p.credential_fields()),
                    "services": services,
                    "regions": p.regions,
                    "region": spec.region.get(p.id),
                    "models": {
                        k: {"default": svc.model, "slots": svc.models}
                        for k in services
                        if (svc := p.service(k)) is not None
                    },
                    "voices": {
                        lang: [{"id": v.id, "name": v.name} for v in p.voices_for(lang)]
                        for lang in LANGUAGES
                    },
                    "default_voice": p.default_voice,
                    "slots": shared.get(p.id, []),
                }
            )
        return {
            "providers": providers,
            "slots": {f"{k}.{n}": s.model_dump() for k, n, s in spec.bound_slots()},
            "slot_names": SLOT_NAMES,
            "languages": spec.languages.model_dump(),
        }

    @router.get("/interaction")
    def interaction() -> dict[str, Any]:
        if ctx.interaction is None:
            return {"state": "off"}
        return ctx.interaction.snapshot()

    @router.get("/interaction/decisions")
    def decisions(limit: int = 50) -> list[dict[str, Any]]:
        if ctx.interaction is None:
            return []
        return ctx.interaction.recent_decisions(min(max(limit, 1), 500))

    @router.get("/interaction/clip/{row_id}")
    async def clip(row_id: str) -> Response:
        if ctx.interaction is None or not row_id.isalnum():
            raise HTTPException(status_code=404, detail="no clip")
        audio = await asyncio.to_thread(ctx.interaction.clip_for, row_id)
        if audio is None:
            raise HTTPException(status_code=404, detail="no clip")
        return Response(
            audio.to_wav_bytes(), media_type="audio/wav", headers={"Cache-Control": "no-store"}
        )

    @router.post("/say")
    async def say(request: SayRequest) -> dict[str, Any]:
        _running()
        if ctx.interaction is None or not ctx.interaction.started:
            raise HTTPException(status_code=409, detail="interaction not running")
        result = await ctx.interaction.say(request.text, request.expression)
        return {"ok": result.ok, "error": result.error, "timing": result.timing.as_dict()}

    @router.post("/body/express")
    def express(request: ExpressRequest) -> dict[str, Any]:
        _running()
        if ctx.body is None:
            raise HTTPException(status_code=409, detail="no body")
        if ctx.body.controller is not None:  # the controller holds the body: play it by hand
            ok = ctx.body.express(request.name, manual=True, intensity=request.intensity)
        elif ctx.interaction is not None and ctx.interaction.expressions is not None:
            ok = ctx.interaction.expressions.express(request.name, request.intensity)
        else:
            ok = ctx.body.express(request.name, intensity=request.intensity)
        return {"ok": ok}

    @router.get("/body/expressions")
    def expressions() -> list[dict[str, Any]]:
        return ctx.body.expression_catalog() if ctx.body is not None else []

    @router.post("/body/state")
    async def body_state(request: StateRequest) -> dict[str, Any]:
        _running()
        body = ctx.body
        if body is None:
            raise HTTPException(status_code=409, detail="no body")
        ok = body.hold_state(request.name, mirror=random.random() < 0.5)
        if ok:
            asyncio.get_running_loop().call_later(request.seconds, body.end_state)
        return {"ok": ok}

    # ------------------------------------------------------------------- robot

    robot = RobotControl(ctx, ctx.config.storage.layout.cache_dir)

    def _robot(call: Callable[[], Any]) -> Any:
        _running()
        try:
            return call()
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except BlockingIOError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown {exc}") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    async def _robot_async(coro: Any) -> Any:
        if ctx.service is not None and not ctx.service.running:
            coro.close()  # never awaited: the robot is off
            _running()
        try:
            return await coro
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except BlockingIOError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/robot")
    def robot_status() -> dict[str, Any]:
        return robot.status()

    @router.post("/robot/control")
    async def robot_control(request: ControlRequest) -> dict[str, Any]:
        return cast(
            dict[str, Any], await _robot_async(robot.take() if request.held else robot.release())
        )

    @router.post("/robot/pose")
    def robot_pose(request: PoseRequest) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            _robot(
                lambda: robot.pose(
                    request.yaw,
                    request.pitch,
                    request.roll,
                    request.z,
                    request.body_yaw,
                    request.antennas,
                    request.duration_s,
                )
            ),
        )

    @router.post("/robot/gesture")
    def robot_gesture(request: ExpressRequest) -> dict[str, Any]:
        return cast(dict[str, Any], _robot(lambda: robot.gesture(request.name)))

    @router.post("/robot/express")
    def robot_express(request: ExpressRequest) -> dict[str, Any]:
        return cast(dict[str, Any], _robot(lambda: robot.express(request.name, request.intensity)))

    @router.post("/robot/test/mic")
    async def robot_test_mic(request: TestRequest) -> dict[str, Any]:
        return cast(dict[str, Any], await _robot_async(robot.mic_test(request.seconds)))

    @router.post("/robot/test/speaker")
    async def robot_test_speaker(request: TestRequest) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await _robot_async(robot.speaker_test(request.kind, request.seconds, request.freq)),
        )

    @router.post("/robot/test/snapshot")
    def robot_test_snapshot() -> dict[str, Any]:
        return cast(dict[str, Any], _robot(robot.snapshot))

    @router.post("/robot/test/video")
    async def robot_test_video(request: TestRequest) -> dict[str, Any]:
        return cast(dict[str, Any], await _robot_async(robot.video_test(request.seconds)))

    @router.get("/robot/file/{name}")
    def robot_file(name: str) -> FileResponse:
        path = robot.file_path(name)
        if path is None:
            raise HTTPException(status_code=404, detail="no such file")
        return FileResponse(
            path, media_type=RobotControl.media_type(name), headers={"Cache-Control": "no-store"}
        )

    @router.get("/traces/{service}")
    def traces(service: str, limit: int = 50) -> list[dict[str, Any]]:
        table = {
            "llm": LLMSession.shared.trace,
            "asr": ASRSession.shared.trace,
            "tts": TTSSession.shared.trace,
        }.get(service)
        if table is None:
            raise HTTPException(status_code=404, detail="unknown service")
        return table.recent(min(max(limit, 1), 500))

    # -------------------------------------------------------------- automation

    def _automation() -> AutomationSession:
        if ctx.automation is None or ctx.automation.jobs is None:
            raise HTTPException(status_code=409, detail="automation not running")
        return ctx.automation

    @router.get("/automation")
    def automation_state() -> dict[str, Any]:
        return _automation().status()

    @router.get("/automation/jobs")
    def jobs(include_done: bool = False) -> list[dict[str, Any]]:
        store = _automation().jobs
        assert store is not None
        return [
            {
                "id": j.id,
                "name": j.name,
                "trigger_kind": j.trigger_kind,
                "trigger": j.trigger,
                "prompt": j.prompt,
                "delivery": j.delivery,
                "owner": j.owner,
                "channel": j.channel,
                "state": j.state,
                "next_run_ts": j.next_run_ts,
                "last_run_ts": j.last_run_ts,
                "runs": j.runs,
                "builtin": j.builtin,
            }
            for j in store.list_jobs(include_done)
        ]

    @router.post("/automation/jobs")
    def create_job(request: JobCreate) -> dict[str, Any]:
        store = _automation().jobs
        assert store is not None
        delivery = cast(
            Literal["in_person", "remote", "both", "auto"],
            request.delivery
            if request.delivery in ("in_person", "remote", "both", "auto")
            else "auto",
        )
        if not request.cron and not request.when:
            raise HTTPException(status_code=422, detail="cron or when is required")
        job = Job(
            request.name,
            "cron" if request.cron else "at",
            request.cron or request.when,
            request.prompt,
            delivery=delivery,
            owner="owner",
            channel="voice",
        )
        try:
            saved = store.save(job)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"id": saved.id, "next_run_ts": saved.next_run_ts}

    @router.post("/automation/jobs/{job_id}/{action}")
    def job_action(job_id: str, action: str) -> dict[str, Any]:
        store = _automation().jobs
        assert store is not None
        if action == "delete":
            return {"ok": store.delete(job_id)}
        if action in ("pause", "resume"):
            job = store.set_state(job_id, "paused" if action == "pause" else "active")
            return {"ok": job is not None, "state": job.state if job else None}
        raise HTTPException(status_code=404, detail="unknown action")

    # ------------------------------------------------------------------- agent

    def _agent() -> AgentSession:
        if ctx.agent is None:
            raise HTTPException(status_code=409, detail="agent not running")
        return ctx.agent

    @router.get("/agent")
    def agent_state() -> dict[str, Any]:
        return _agent().snapshot()

    @router.get("/agent/timeline")
    def timeline(
        limit: int = 80,
        channel: str | None = None,
        before: float | None = None,
        conversation: bool = False,
    ) -> list[dict[str, Any]]:
        """Newest first; `before` pages back, `conversation` = what people saw (the Live card)."""
        rows = _agent().dialogue.recent(
            min(max(limit, 1), 500), channel, before=before, conversation=conversation
        )
        return [
            {
                "id": r.id,
                "ts": r.ts,
                "channel": r.channel,
                "speaker": r.speaker,
                "role": r.role,
                "content": r.content,
                "visibility": r.visibility,
                "agent": r.agent,
                "delivered_to": r.delivered_to,
                "meta": r.meta,
            }
            for r in rows
        ]

    @router.post("/agent/chat")
    async def chat(request: ChatRequest) -> dict[str, Any]:
        from sidekick.channel import ChannelMessage

        _running()
        agent = _agent()
        parts: list[str] = []
        error: str | None = None
        no_reply = False
        started = time.time()
        first_ms: float | None = None
        async for event in agent.respond_events(
            ChannelMessage(
                "dashboard", request.speaker, request.text, language=ctx.spec.languages.default
            )
        ):
            if event.kind == "text":
                if first_ms is None:
                    first_ms = (time.time() - started) * 1000
                parts.append(event.text)
            elif event.kind == "error":
                error = event.error
            elif event.kind == "no_reply":
                no_reply = True
        # the tools this turn called (the Agent page's test card shows them)
        tools = [
            {
                "agent": r.speaker,
                "name": r.meta.get("tool", ""),
                "arguments": r.meta.get("arguments"),
                "result": r.content,
            }
            for r in agent.dialogue.since(started, role="tool")
            if r.channel == "dashboard"
        ]
        return {
            "reply": "".join(parts),
            "no_reply": no_reply,
            "error": error,
            "ms": round((time.time() - started) * 1000),
            "first_ms": None if first_ms is None else round(first_ms),
            "tools": tools,
        }

    def _fact(f: Any) -> dict[str, Any]:
        return {
            "id": f.id,
            "ts": f.ts,
            "scope": f.scope,
            "subject": f.subject,
            "teller": f.teller,
            "channel": f.channel,
            "visibility": f.visibility,
            "origin": f.origin,
            "category": f.category,
            "text": f.text,
            "valid_until": f.valid_until,
            "sources": list(f.sources),
            "episode": f.episode,
            "superseded_by": f.superseded_by,
            "retired_ts": f.retired_ts,
        }

    def _episode(e: Any) -> dict[str, Any]:
        return {
            "id": e.id,
            "conversation": e.conversation,
            "channel": e.channel,
            "ts_start": e.ts_start,
            "ts_end": e.ts_end,
            "title": e.title,
            "summary": e.summary,
            "participants": list(e.participants),
            "visibility": e.visibility,
            "private_to": e.private_to,
            "followups": list(e.followups),
            "rows": e.rows,
            "user_turns": e.user_turns,
            "status": e.status,
            "attempts": e.attempts,
            "error": e.error,
            "written_ts": e.written_ts,
        }

    @router.get("/agent/memory")
    def memory(limit: int = 300, days: float = 14.0) -> dict[str, Any]:
        """The memory pyramid for the Memory view: facts (L2), episodes (L1), digests, writer."""
        agent = _agent()
        store = agent.memory
        since = time.time() - max(days, 0.5) * 86400.0
        return {
            "facts": [_fact(f) for f in store.all(min(max(limit, 1), 2000))],
            "episodes": [_episode(e) for e in store.episodes(since, 300, include_failed=True)],
            "digests": store.digests(),
            "writer": agent.writer.live() if agent.writer is not None else None,
        }

    @router.post("/agent/memory")
    def remember(request: MemoryCreate) -> dict[str, Any]:
        try:
            fact = _agent().memory.remember(
                request.scope,
                request.text,
                channel="dashboard",
                category=request.category,
                visibility="private" if request.private else "public",
            )
        except ValueError as exc:  # an unnamed person's scope (block #63)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _fact(fact)

    @router.delete("/agent/memory/{fact_id}")
    def forget(fact_id: str) -> dict[str, Any]:
        return {"removed": _agent().memory.forget(fact_id=fact_id)}

    @router.post("/agent/memory/write")
    async def write_memory() -> dict[str, Any]:
        """Write every conversation now, the open ones too (the owner testing the writer)."""
        _running()
        agent = _agent()
        if agent.writer is None:
            raise HTTPException(status_code=409, detail="no memory writer")
        written = await agent.writer.tick(include_open=True)
        return {"written": written, "writer": agent.writer.live()}

    @router.get("/agent/episodes/{episode_id}")
    def episode(episode_id: str) -> dict[str, Any]:
        """One episode with its conversation (L0) and the facts it produced."""
        agent = _agent()
        found = agent.memory.episode(episode_id)
        if found is None:
            raise HTTPException(status_code=404, detail="no such episode")
        rows = agent.dialogue.conversation_rows(found.conversation)
        return {
            **_episode(found),
            "rows": [
                {
                    "ts": r.ts,
                    "role": r.role,
                    "speaker": r.speaker,
                    "content": r.content,
                    "tool": r.meta.get("tool"),
                    "ok": r.meta.get("ok"),
                }
                for r in rows
                if r.role in ("user", "assistant", "tool")
            ],
            "facts": [_fact(f) for f in agent.memory.all(2000) if f.episode == episode_id],
        }

    @router.delete("/agent/episodes/{episode_id}")
    def delete_episode(episode_id: str) -> dict[str, Any]:
        return {"removed": _agent().memory.delete_episode(episode_id)}

    @router.get("/agent/tools")
    def tools() -> list[dict[str, Any]]:
        """Every registered tool with who may call it (the Tools board)."""
        agent = _agent()
        users: dict[str, list[str]] = {}
        for name, member in agent.agents.items():
            for tool in agent.tools_for(member.profile):
                users.setdefault(tool.name, []).append(name)

        def rank(origin: str) -> int:
            for i, prefix in enumerate(("core", "automation", "extension:", "mcp:")):
                if origin.startswith(prefix):
                    return i
            return 4

        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": dict(t.parameters),
                "confirm": t.confirm,
                "main_only": t.main_only,
                "origin": t.origin,
                "agents": users.get(t.name, []),
            }
            for t in sorted(agent.registry.all(), key=lambda t: (rank(t.origin), t.origin, t.name))
        ]

    @router.get("/agent/skills")
    def skills() -> list[dict[str, Any]]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "body": s.body,
                "origin": s.origin,
                "enabled": s.enabled,
                "updated_ts": s.updated_ts,
            }
            for s in _agent().skills.list()
        ]

    @router.put("/agent/skills")
    def put_skill(update: SkillUpdate) -> dict[str, Any]:
        try:
            skill = _agent().skills.upsert_markdown(update.markdown, origin="user")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"name": skill.name}

    @router.delete("/agent/skills/{name}")
    def delete_skill(name: str) -> dict[str, Any]:
        return {"ok": _agent().skills.delete(name)}

    @router.get("/agent/agents")
    def agents_roster() -> list[dict[str, Any]]:
        """Every agent, the main agent first: the Swarm view's cards (block #78)."""
        return _agent().roster()

    @router.put("/agent/subagents/{name}")
    def put_subagent(name: str, update: SubagentUpdate) -> dict[str, Any]:
        """Create or replace one of your subagents: saved in `agents.subagents`, live at once."""
        agent = _agent()
        if name == "main" or not SUBAGENT_NAME.match(name):
            raise HTTPException(
                status_code=422,
                detail="a name is lowercase letters, digits, - or _ (up to 32), and not main",
            )
        existing = agent.agents.get(name)
        if existing is not None and existing.profile.origin != "user":
            raise HTTPException(
                status_code=409, detail=f"{name} comes from {existing.profile.origin}"
            )
        if update.llm_slot not in agent.llm.slots():
            raise HTTPException(
                status_code=422,
                detail=f"no LLM slot {update.llm_slot!r}; bound: {', '.join(agent.llm.slots())}",
            )
        data = ctx.spec.model_dump(mode="json")
        data["agents"]["subagents"][name] = update.model_dump()
        try:
            new_spec = ConfigSpec.model_validate(data)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _save_spec(new_spec)
        agent.set_subagent(name, new_spec.agents.subagents[name])
        return next(s for s in agent.roster() if s["name"] == name)

    @router.delete("/agent/subagents/{name}")
    def delete_subagent(name: str) -> dict[str, Any]:
        """Delete one of your subagents; an extension's goes with its extension."""
        agent = _agent()
        existing = agent.agents.get(name)
        if existing is not None and existing.profile.origin != "user":
            raise HTTPException(
                status_code=409,
                detail=f"{name} comes from {existing.profile.origin}: disable it there",
            )
        if name not in ctx.spec.agents.subagents:
            raise HTTPException(status_code=404, detail=f"no subagent {name}")
        data = ctx.spec.model_dump(mode="json")
        data["agents"]["subagents"].pop(name, None)
        _save_spec(ConfigSpec.model_validate(data))
        agent.unregister_agent(name)
        return {"ok": True}

    @router.get("/agent/mcp")
    def mcp_servers() -> list[dict[str, Any]]:
        agent = _agent()
        return [
            {
                "name": s.name,
                "transport": s.transport,
                "command": s.command,
                "args": list(s.args),
                "url": s.url,
                "origin": s.origin,
                "enabled": s.enabled,
                "env_keys": sorted(s.env),  # names only: values may be secrets
                "header_keys": sorted(s.headers),
                "error": agent.mcp.errors.get(s.name),
                "tools": [t.name for t in agent.registry.all() if t.origin == f"mcp:{s.name}"],
            }
            for s in agent.mcp_registry.list()
        ]

    @router.post("/agent/mcp")
    async def add_mcp(request: MCPAdd) -> dict[str, Any]:
        agent = _agent()
        try:
            server = MCPServer(
                request.name,
                "http" if request.url else "stdio",
                command=request.command,
                args=tuple(request.args),
                url=request.url,
            )
            agent.mcp_registry.upsert(server)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if ctx.service is not None and not ctx.service.running:
            return {"ok": True, "tools": 0, "error": None, "note": "connects at the next start"}
        count = await agent.refresh_mcp()
        return {"ok": True, "tools": count, "error": agent.mcp.errors.get(server.name)}

    @router.delete("/agent/mcp/{name}")
    async def remove_mcp(name: str) -> dict[str, Any]:
        agent = _agent()
        await agent.mcp.disconnect(name)
        ok = agent.mcp_registry.delete(name)
        if ctx.service is None or ctx.service.running:
            await agent.refresh_mcp()
        return {"ok": ok}

    # -------------------------------------------------------- perception / channels

    @router.get("/perception")
    def perception() -> dict[str, Any]:
        if ctx.perception is None:
            return {"started": False}
        return dict(ctx.perception.snapshot())

    @router.get("/perception/events")
    def events(limit: int = 100, stored: bool = False) -> list[dict[str, Any]]:
        if ctx.perception is None:
            return []
        limit = min(max(limit, 1), 500)
        rows = ctx.perception.stored(limit) if stored else ctx.perception.recent(limit)
        return list(rows)

    @router.get("/channels")
    def channels() -> dict[str, Any]:
        spec = ctx.spec
        out: dict[str, Any] = {
            "telegram": {
                "enabled": spec.channels.telegram.enabled,
                "token": bool(spec.credentials.get("telegram", {}).get("bot_token")),
                "paired": list(spec.channels.telegram.allow_chat_ids),
                "owner": spec.channels.telegram.owner_chat_id,
                "pairing_code": spec.channels.telegram.pairing_code,
            },
            "wechat": {
                "enabled": spec.channels.wechat.enabled,
                "token": bool(spec.credentials.get("wechat", {}).get("bot_token")),
                "bot_id": spec.channels.wechat.bot_id,
                "user_id": spec.channels.wechat.user_id,
                "allow": list(spec.channels.wechat.allow_user_ids),
                "base_url": spec.channels.wechat.base_url,
            },
            "running": [],
        }
        if ctx.channels is not None:
            for name in ctx.channels.adapters():
                adapter = ctx.channels.get(name)
                out["running"].append(
                    {
                        "name": name,
                        "received": getattr(adapter, "received", None),
                        "sent": getattr(adapter, "sent", None),
                        "last_update_at": getattr(adapter, "last_update_at", None),
                        "last_error": getattr(adapter, "last_error", None),
                    }
                )
        return out

    @router.post("/channels/telegram/pair")
    def telegram_pair() -> dict[str, Any]:
        import secrets

        code = f"{secrets.randbelow(900000) + 100000}"
        ctx.spec.channels.telegram.pairing_code = code
        ctx.config.save(ctx.spec)
        adapter = ctx.channels.get("telegram") if ctx.channels is not None else None
        if adapter is not None and hasattr(adapter, "pairing_code"):
            adapter.pairing_code = code
        return {"code": code}

    wx: dict[str, Any] = {}  # the WeChat QR login in progress (one at a time)

    async def _wx_close() -> None:
        client = wx.pop("client", None)
        wx.clear()
        if client is not None:
            try:
                await client.aclose()
            except Exception as exc:  # pragma: no cover - teardown best effort
                Log.warning(f"wechat login client: {exc!r}")

    @router.post("/channels/wechat/login")
    async def wechat_login_start() -> dict[str, Any]:
        """Start the iLink QR login (the old `sidekick wechat login`, block #87)."""
        from sidekick.channel import WeChatClient, WeChatLogin

        await _wx_close()
        wechat = ctx.spec.channels.wechat
        client = WeChatClient(None, wechat.base_url, wechat.bot_agent)
        flow = WeChatLogin(client)
        try:
            url = await flow.start()
        except Exception as exc:
            await client.aclose()
            raise HTTPException(status_code=502, detail=f"could not start: {exc!r}"[:300]) from exc
        wx.update(client=client, flow=flow, started=time.time())
        return {"status": "wait", "qr": url}

    @router.get("/channels/wechat/login")
    async def wechat_login_poll() -> dict[str, Any]:
        """One status poll; a confirmed login saves the bot token (it runs from the next start)."""
        flow = wx.get("flow")
        if flow is None:
            return {"status": "idle"}
        if time.time() - float(wx.get("started", 0.0)) > 480.0:
            await _wx_close()
            return {"status": "timeout"}
        try:
            status = await flow.poll()
        except Exception as exc:
            return {"status": "error", "error": repr(exc)[:200]}
        out: dict[str, Any] = {"status": status, "qr": flow.qrcode_url}
        if status == "confirmed" and flow.result:
            result = flow.result
            spec = ctx.spec.model_copy(deep=True)
            spec.credentials.setdefault("wechat", {})["bot_token"] = str(
                result.get("bot_token") or ""
            )
            wechat = spec.channels.wechat
            wechat.bot_id = result.get("bot_id")
            wechat.base_url = str(result.get("base_url") or wechat.base_url)
            if result.get("user_id"):
                wechat.user_id = str(result["user_id"])
                if wechat.user_id not in wechat.allow_user_ids:
                    wechat.allow_user_ids.append(wechat.user_id)
            _save_spec(spec)
            await _wx_close()
            out["note"] = "logged in · WeChat runs from Banana's next start"
            Log.info(f"wechat login saved: bot_id={result.get('bot_id')}")
        elif status in ("verify_code_blocked", "binded_redirect"):
            await _wx_close()
        return out

    @router.post("/channels/wechat/login/code")
    def wechat_login_code(update: SectionUpdate) -> dict[str, Any]:
        """The digits WeChat shows when it asks for a verification code."""
        flow = wx.get("flow")
        if flow is None:
            raise HTTPException(status_code=409, detail="no login in progress")
        flow.verify_code = str(update.values.get("code", "")).strip()
        return {"ok": True}

    @router.delete("/channels/wechat/login")
    async def wechat_login_cancel() -> dict[str, Any]:
        await _wx_close()
        return {"ok": True}

    @router.get("/channels/wechat/qr.png")
    def wechat_qr(url: str) -> Response:
        import io

        import segno

        buffer = io.BytesIO()
        segno.make(url, error="m").save(buffer, kind="png", scale=6, border=2)
        return Response(buffer.getvalue(), media_type="image/png")

    # ---------------------------------------------------------------- contacts

    def _contacts() -> Any:
        if ctx.contacts is None or not ctx.contacts.ready:
            raise HTTPException(status_code=409, detail="contacts not running")
        return ctx.contacts

    @router.get("/contacts")
    def contacts_list() -> dict[str, Any]:
        return dict(_contacts().snapshot())

    @router.post("/contacts")
    def contacts_create(request: ContactCreate) -> dict[str, Any]:
        contacts = _contacts()
        contact = contacts.create(
            request.name,
            aliases=request.aliases,
            language=request.language,
            is_owner=request.is_owner,
            notes=request.notes,
            contact_id=request.id,
        )
        if request.telegram:
            contacts.bind_remote(contact.id, "telegram", request.telegram)
        if request.wechat:
            contacts.bind_remote(contact.id, "wechat", request.wechat)
        return {"id": contact.id}

    @router.put("/contacts/{contact_id}")
    def contacts_update(contact_id: str, request: ContactCreate) -> dict[str, Any]:
        """Edit in place: the id, the voice / face prints, the facts and the created time stay."""
        contacts = _contacts()
        current = contacts.get(contact_id)
        if current is None:
            raise HTTPException(status_code=404, detail="no such contact")
        remote = {
            channel: value.removeprefix("tg:").removeprefix("wx:")
            for channel, value in (("telegram", request.telegram), ("wechat", request.wechat))
            if value
        }
        contacts.update(
            Contact(
                current.id,
                request.name,
                tuple(request.aliases),
                request.notes or current.notes,
                request.language,
                request.is_owner,
                remote,
                current.created_ts,
                current.last_seen_ts,
            )
        )
        return {"id": current.id}

    @router.delete("/contacts/{contact_id}")
    def contacts_delete(contact_id: str) -> dict[str, Any]:
        """The contact, their prints and their facts (a later contact with the id gets none)."""
        ok = bool(_contacts().delete(contact_id))
        if ok and ctx.agent is not None:
            ctx.agent.memory.drop_scope(contact_id)
        return {"ok": ok}

    @router.post("/contacts/enroll/voice")
    async def enroll_voice(request: EnrollVoice) -> dict[str, Any]:
        contacts = _contacts()
        if ctx.interaction is None or ctx.interaction.trace is None:
            raise HTTPException(status_code=409, detail="no listening clips available")
        clips = []
        for clip_id in request.clip_ids:
            audio = await asyncio.to_thread(ctx.interaction.clip_for, clip_id)
            if audio is not None:
                clips.append(audio)
        if not clips:
            raise HTTPException(status_code=404, detail="no such clips")
        used = await asyncio.to_thread(contacts.enroll_voice, request.contact_id, clips)
        return {"used": int(used)}

    @router.get("/contacts/people")
    def people_seen() -> list[dict[str, Any]]:
        contacts = _contacts()
        return [p.as_dict() for p in contacts.people()]

    @router.post("/contacts/people/{person_id}/promote")
    def promote_person(person_id: str, request: PromoteRequest) -> dict[str, Any]:
        contacts = _contacts()
        contact = contacts.promote_person(person_id, request.name, request.language)
        if contact is None:
            raise HTTPException(status_code=404, detail="no such person")
        if ctx.interaction is not None:
            ctx.interaction.rename_speaker(person_id, contact.id)
        return {"id": contact.id, "name": contact.name}

    @router.delete("/contacts/people/{person_id}")
    def forget_person(person_id: str) -> dict[str, Any]:
        return {"ok": bool(_contacts().forget_person(person_id))}

    @router.post("/contacts/enroll/voice/record")
    async def enroll_voice_record(request: EnrollRecord) -> dict[str, Any]:
        _running()
        contacts = _contacts()
        if ctx.body is None:
            raise HTTPException(status_code=409, detail="no body")
        try:
            audio = await robot.capture(request.seconds)
        except BlockingIOError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if audio is None:
            raise HTTPException(status_code=409, detail="microphone gave no audio")
        peak = float(np.max(np.abs(audio.samples))) if len(audio.samples) else 0.0
        used = await asyncio.to_thread(contacts.enroll_voice, request.contact_id, [audio])
        return {
            "used": int(used),
            "seconds": round(audio.duration_s, 2),
            "peak_dbfs": round(20.0 * math.log10(peak), 1) if peak > 1e-6 else -100.0,
        }

    @router.post("/contacts/enroll/face/{contact_id}")
    async def enroll_face(contact_id: str, frames: int = 5) -> dict[str, Any]:
        _running()
        contacts = _contacts()
        if ctx.body is None:
            raise HTTPException(status_code=409, detail="no body")
        captured = []
        for _ in range(min(max(frames, 1), 10)):
            frame = ctx.body.frame()
            if frame is not None:
                captured.append(frame)
            await asyncio.sleep(0.3)
        if not captured:
            raise HTTPException(status_code=409, detail="camera gave no frames")
        used = await asyncio.to_thread(contacts.enroll_face, contact_id, captured)
        return {"used": int(used), "frames": len(captured)}

    @router.delete("/contacts/{contact_id}/embeddings/{kind}")
    def clear_embeddings(contact_id: str, kind: str) -> dict[str, Any]:
        contacts = _contacts()
        if kind not in ("voice", "face"):
            raise HTTPException(status_code=404, detail="kind must be voice or face")
        return {"removed": int(contacts.store.clear_embeddings(contact_id, kind))}

    @router.get("/body/frame.jpg")
    def frame_jpeg() -> Response:
        _running()
        if ctx.body is None:
            raise HTTPException(status_code=409, detail="no body")
        frame = ctx.body.frame(0.5)
        if frame is None:
            raise HTTPException(status_code=404, detail="no frame")
        data = encode_jpeg(frame, 1920, 80)
        if data is None:
            raise HTTPException(status_code=500, detail="encode failed")
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @router.get("/body/stream.mjpg")
    def stream_mjpeg(width: int = 640, fps: float = 8.0, quality: int = 70) -> StreamingResponse:
        _running()
        if ctx.body is None:
            raise HTTPException(status_code=409, detail="no body")
        return StreamingResponse(
            mjpeg_stream(ctx.body, min(max(width, 160), 1920), fps, min(max(quality, 30), 95)),
            media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY.decode()}",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/body/model")
    def body_model() -> dict[str, Any]:
        return BodySession.display_model()

    @router.get("/body/mesh/{name}")
    def body_mesh(name: str) -> FileResponse:
        path = BodySession.mesh_path(name)
        if path is None:
            raise HTTPException(status_code=404, detail="unknown mesh")
        return FileResponse(
            path, media_type="model/stl", headers={"Cache-Control": "public, max-age=86400"}
        )

    @router.get("/live/frame")
    def live_frame() -> dict[str, Any]:
        return LiveFeed(ctx).frame()

    @router.websocket("/live")
    async def live(ws: WebSocket, hz: float = 10.0) -> None:
        await ws.accept()
        feed = LiveFeed(ctx)
        period = 1.0 / min(max(hz, 1.0), 20.0)
        try:
            while True:
                await ws.send_json(feed.frame())
                await asyncio.sleep(period)
        except (WebSocketDisconnect, RuntimeError):
            pass

    # ------------------------------------------------------------------ replay

    def _record() -> Any:
        if ctx.record is None:
            raise HTTPException(status_code=409, detail="recording not configured")
        return ctx.record

    def _chunk(day: str, moment: str) -> Any:
        chunk = _record().chunk(f"{day}/{moment}")
        if chunk is None:
            raise HTTPException(status_code=404, detail="no such chunk")
        return chunk

    @router.get("/record")
    def record_overview() -> dict[str, Any]:
        record = _record()
        return {"status": record.status().as_dict(), "days": record.days()}

    @router.get("/record/chunks")
    def record_chunks(day: str | None = None) -> list[dict[str, Any]]:
        return [c.as_dict() for c in _record().chunks(day)]

    @router.get("/record/{day}/{moment}")
    def record_chunk(day: str, moment: str) -> dict[str, Any]:
        return dict(_chunk(day, moment).as_dict())

    @router.get("/record/{day}/{moment}/telemetry")
    def record_telemetry(day: str, moment: str) -> list[dict[str, Any]]:
        chunk = _chunk(day, moment)
        return list(_record().telemetry(chunk.id))

    @router.get("/record/{day}/{moment}/tracks")
    def record_tracks(day: str, moment: str, bin_s: float = 0.25) -> dict[str, Any]:
        chunk = _chunk(day, moment)
        return chunk_tracks(chunk, ctx, bin_s)

    @router.get("/record/{day}/{moment}/file/{name}")
    def record_file(day: str, moment: str, name: str) -> FileResponse:
        chunk = _chunk(day, moment)
        path = _record().chunk_file(chunk.id, name)
        if path is None:
            raise HTTPException(status_code=404, detail="no such file")
        media = {"mp4": "video/mp4", "wav": "audio/wav", "flac": "audio/flac"}[path.suffix[1:]]
        return FileResponse(path, media_type=media, headers={"Accept-Ranges": "bytes"})

    # -------------------------------------------------------------- extensions

    def _extensions() -> Any:
        if ctx.extensions is None:
            raise HTTPException(status_code=409, detail="extensions not running")
        return ctx.extensions

    @router.get("/extensions")
    def extensions_list() -> list[dict[str, Any]]:
        return list(_extensions().snapshot())

    @router.post("/extensions/{name}/{action}")
    async def extensions_action(name: str, action: str) -> dict[str, Any]:
        extensions = _extensions()
        stopped = ctx.service is not None and not ctx.service.running
        if action == "enable" and stopped:  # saved; it loads at the next start
            if extensions.registry is None or extensions.registry.get(name) is None:
                raise HTTPException(status_code=404, detail="unknown extension")
            extensions.registry.set_enabled(name, True, None)
            record = extensions.registry.get(name)
        elif action == "enable":
            record = await extensions.enable(name)
        elif action == "disable":
            record = await extensions.disable(name)
        elif action == "update":
            record = await extensions.update(name)
        elif action == "remove":
            return {"ok": bool(await extensions.remove(name))}
        else:
            raise HTTPException(status_code=404, detail="unknown action")
        if record is None:
            raise HTTPException(status_code=404, detail="unknown extension")
        return {
            "ok": record.enabled if action != "disable" else not record.enabled,
            "error": record.error,
        }

    @router.put("/extensions/{name}/settings")
    async def extensions_settings(name: str, update: SectionUpdate) -> dict[str, Any]:
        try:
            record = await _extensions().set_settings(name, update.values)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if record is None:
            raise HTTPException(status_code=404, detail="unknown extension")
        return {"ok": True}

    @router.post("/extensions/install")
    async def extensions_install(update: SectionUpdate) -> dict[str, Any]:
        source = str(update.values.get("source", "")).strip()
        if not source:
            raise HTTPException(status_code=422, detail="source is required")
        try:
            record = await _extensions().install(source)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"name": record.name, "version": record.version}

    # -------------------------------------------------------------- config writes

    def _save_spec(new_spec: ConfigSpec, reapply: bool = False) -> None:
        ctx.config.save(new_spec)
        ctx.spec = new_spec
        if reapply and (ctx.service is None or ctx.service.running):
            # Rebind the service backends so a test turn works without a restart; a slot
            # whose credentials are still missing is logged, not raised.
            try:
                ctx.config.apply(new_spec)
            except Exception as exc:
                Log.warning(f"apply after a config change failed: {exc!r}")

    @router.post("/config/credentials")
    def set_credentials(update: CredentialsUpdate) -> dict[str, Any]:
        data = ctx.spec.model_dump(mode="json")
        data.setdefault("credentials", {}).setdefault(update.provider, {}).update(
            {k: v for k, v in update.values.items() if v}
        )
        data.setdefault("region", {}).pop(
            update.provider, None
        )  # a new key may live in another region
        try:
            new_spec = ConfigSpec.model_validate(data)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _save_spec(new_spec, reapply=True)
        return {"ok": True, "fields": sorted(update.values)}

    @router.post("/config/slot")
    def set_slot(update: SlotUpdate) -> dict[str, Any]:
        data = ctx.spec.model_dump(mode="json")
        slots = data.setdefault("slots", {}).setdefault(update.kind, {})
        slots[update.name] = {
            **slots.get(update.name, {}),
            "provider": update.provider,
            "model": update.model,
            "voice": update.voice,
            "speed": update.speed,
        }
        try:
            new_spec = ConfigSpec.model_validate(data)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _save_spec(new_spec, reapply=True)
        return {"ok": True}

    @router.post("/config/languages")
    def set_languages(update: LanguagesUpdate) -> dict[str, Any]:
        if update.default not in LANGUAGES or any(x not in LANGUAGES for x in update.order or []):
            raise HTTPException(status_code=422, detail=f"language must be one of {LANGUAGES}")
        # the voices follow the language: one pinned for another language is dropped (#94)
        _save_spec(ctx.config.with_language(ctx.spec, update.default, update.order), reapply=True)
        return {"ok": True}

    @router.post("/config/probe")
    async def probe(slot: str | None = None) -> list[dict[str, Any]]:
        outcomes = await ctx.config.probe(ctx.spec, [slot] if slot else None)
        ctx.config.save(ctx.spec)
        return [
            {
                "slot": key,
                "ok": o.ok,
                "kind": o.kind,
                "provider": o.provider,
                "api": o.api,
                "model": o.model,
                "region": o.region,
                "latency_ms": o.latency_ms,
                "message": o.message[:200],
            }
            for key, o in outcomes.items()
        ]

    @router.post("/config/tv")
    def set_tv(update: SectionUpdate) -> dict[str, Any]:
        """The TV zone (camera rectangle, Contacts page) and the TV sound sector (Voice page)."""
        data = ctx.spec.model_dump(mode="json")
        if "tv_zone" in update.values:
            data["contacts"]["tv_zone"] = update.values["tv_zone"] or None
        if "tv_sector" in update.values:
            data["interaction"]["tv_sector"] = update.values["tv_sector"] or None
        try:
            new_spec = ConfigSpec.model_validate(data)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _save_spec(new_spec)
        if ctx.interaction is not None:
            ctx.interaction.set_config(new_spec.interaction)
        if ctx.contacts is not None and hasattr(ctx.contacts, "set_config"):
            ctx.contacts.set_config(new_spec.contacts)
        return {
            "ok": True,
            "tv_zone": new_spec.contacts.tv_zone,
            "tv_sector": new_spec.interaction.tv_sector,
        }

    async def _apply_section(
        section: str, spec: ConfigSpec, changed: list[str]
    ) -> tuple[bool, str]:
        """Apply a saved section live where a hook exists; say so when a restart is needed."""
        if section == "interaction":
            if ctx.interaction is not None:
                ctx.interaction.set_config(spec.interaction)
            return True, "applied"
        if section == "agents":
            if ctx.agent is None:
                return False, "takes effect at the next start"
            ctx.agent.configure_main(spec.agents)  # the main agent's card on Swarm
            rest = [k for k in changed if k not in MAIN_AGENT_KNOBS]
            if rest:
                return False, f"{', '.join(rest)}: takes effect at the next start"
            return True, "applied"
        if section == "body":
            if ctx.body is not None:
                ctx.body.configure_sway(spec.body.sway)
                ctx.body.set_expressiveness(spec.body.expressiveness)
            rest = [k for k in changed if k not in ("sway", "expressiveness")]
            if rest:
                return False, f"{', '.join(rest)}: takes effect at the next start"
            return True, "applied"
        if section == "contacts":
            if ctx.contacts is not None and hasattr(ctx.contacts, "set_config"):
                ctx.contacts.set_config(spec.contacts)
                return True, "applied"
            return False, "takes effect at the next start"
        if section == "automation":
            if ctx.automation is not None and ctx.automation.jobs is not None:
                await ctx.automation.apply(spec.automation)
            if ctx.interaction is not None and hasattr(ctx.interaction, "set_quiet_hours"):
                ctx.interaction.set_quiet_hours(spec.automation.quiet_hours)
            return True, "applied"
        return False, "takes effect at the next start"

    @router.post("/config/{section}")
    async def update_section(section: str, update: SectionUpdate) -> dict[str, Any]:
        if section not in CONFIG_SECTIONS:
            raise HTTPException(status_code=404, detail=f"no such config section: {section}")
        data = ctx.spec.model_dump(mode="json")
        _merge(data[section], update.values)
        try:
            new_spec = ConfigSpec.model_validate(data)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _save_spec(new_spec)
        applied, note = await _apply_section(section, new_spec, sorted(update.values))
        Log.info(f"{section} config updated: {sorted(update.values)} ({note})")
        out: dict[str, Any] = getattr(new_spec, section).model_dump(mode="json")
        out["applied"] = applied
        out["note"] = note
        return out

    # -------------------------------------------------------------- readiness, system

    @router.get("/doctor")
    def doctor_report() -> dict[str, Any]:
        if ctx.doctor is None:
            return {"ready": None, "summary": "no readiness checks in this context", "items": []}
        return cast(dict[str, Any], ctx.doctor.local().as_dict())

    @router.post("/doctor/run")
    async def doctor_run(layers: str = "local,probe,loopback") -> dict[str, Any]:
        if ctx.doctor is None:
            raise HTTPException(status_code=409, detail="no readiness checks in this context")
        wanted = [x.strip() for x in layers.split(",") if x.strip()]
        if ctx.service is not None and not ctx.service.running:
            wanted = [layer for layer in wanted if layer != "loopback"]  # the robot is off
        report = await ctx.doctor.run(wanted)
        return cast(dict[str, Any], report.as_dict())

    @router.post("/system/backup")
    def system_backup() -> dict[str, Any]:
        layout = ctx.config.storage.layout
        dest = (
            layout.home / "cache" / "backups" / f"sidekick-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
        )
        path = ctx.config.storage.backup(dest)
        return {"path": str(path), "size_mb": round(path.stat().st_size / 1e6, 2)}

    @router.get("/logs")
    def logs(lines: int = 200, source: str = "sidekick") -> list[str]:
        """The tail of sidekick's log or (`source=daemon`) the robot daemon's."""
        path = ctx.log_path
        if source == "daemon" and path is not None:
            path = path.with_name("reachy-daemon.log")
        if path is None or not path.exists():
            return []
        return _tail_lines(path, min(max(lines, 1), 2000))

    return router
