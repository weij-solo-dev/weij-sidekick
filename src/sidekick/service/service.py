"""sidekick.service.service — ServiceSession: start and stop Banana inside the process

Overview
    The process — started and closed by the CLI (`sidekick startup` / `sidekick close`) — hosts
    the console for its whole life: the dashboard, every data page (contacts, memory, jobs,
    Replay, traces, logs) and readiness. The **service** is everything Banana does, and the
    dashboard's power control starts and stops it here (blocks #82–#87). A start re-reads the
    config, checks the prerequisites (the readiness list's configuration rows; any `bad` row and
    nothing starts), makes sure the on-host models are on disk, binds every module to the fresh
    spec and then brings the modules up one by one, each proving it works: the module's own
    `check()` items become the dialog's sub-lines. A stop takes them down in reverse and unbinds
    the service backends, so a stopped Banana holds little memory (the robot is turned off by the
    body's own `stop`). The owner's last choice is remembered in `service.json`, so restarting the
    process (or the Mac) does not undo a Stop.
Design
    One state machine — `stopped → starting → running → stopping → stopped` — and one transition
    at a time: a request while one runs raises `ServiceBusy` (the route answers 409). The
    transition is a background task, so the dashboard follows its steps from `status()` instead
    of holding a request open. A module whose check has a `bad` item (or whose `start()` raises)
    aborts the start: everything started so far is stopped again and the service ends stopped
    with the failure kept for the dialog; `warn` items run marked. The order of the modules and
    every `setup` argument come from `app.py` (invariant 21): this session receives the ordered
    modules, the `prepare` composition (every runtime `setup` with the current spec), the
    prerequisite and model functions, and only calls them. The singletons live as long as the
    process (block #83): `start()` / `stop()` may run again and again on the same objects. A
    process exit stops a running service without touching the remembered choice; a start still
    in flight is cancelled and rolled back, a stop in flight is waited for (cancelling it ran a
    second stop over the first — the daemon stopped twice — and lost the Stop, block #89). A
    Stop is remembered when it begins, the way the owner pressed it.
Depends on
    sidekick.log, sidekick.storage, sidekick.config.

See Also
--------
    AGENTS.md "Service", PLAN.md blocks "[2026-10-30 #82]" … "[2026-10-30 #87]".

"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, ClassVar

from sidekick.config import ConfigSession
from sidekick.log import Log
from sidekick.storage import StorageSession

from .schemas import (
    MODULE_TABS,
    STEP_TITLES,
    ServiceBusy,
    ServiceStep,
    ServiceTransition,
    worst_level,
)

Prerequisites = Callable[[], list[Any]]
Models = Callable[[Callable[[str], None]], Awaitable[list[Any]]]
STOP_TIMEOUT_S = 30.0  # one module's stop; the daemon's own stop waits up to 30 s with the sleep


def _item(raw: Any, tab: str) -> dict[str, Any]:
    """A check item as a dict with its tab (modules give dicts, the doctor `DoctorItem`s)."""
    data = raw.as_dict() if hasattr(raw, "as_dict") else dict(raw)
    data.setdefault("tab", tab)
    return data


async def _call(method: Callable[[], Any]) -> Any:
    """Await a coroutine method, run a plain one on a thread (the recorder's start / stop)."""
    if inspect.iscoroutinefunction(method):
        return await method()
    return await asyncio.to_thread(method)


class ServiceSession:
    """Starts, stops and reports Banana inside the process."""

    shared: ClassVar[ServiceSession]

    def __init__(self) -> None:
        self.state = "stopped"
        self.since = time.time()
        self.transition: ServiceTransition | None = None  # the current or the last one
        self.wanted = "running"  # the owner's last choice (Start / Stop), remembered
        self.changed_at: float | None = None
        self.changed_by = ""
        self.config: ConfigSession | None = None
        self.state_path: Path | None = None
        self.prepare: Callable[[], None] | None = None
        self.prerequisites: Prerequisites | None = None
        self.models: Models | None = None
        self.modules: list[tuple[str, Any]] = []
        self.autostart: bool | None = None
        self.prepared = False
        self._task: asyncio.Task[None] | None = None
        self._exiting = False

    def setup(
        self,
        *,
        config: ConfigSession,
        state_path: Path,
        prepare: Callable[[], None],
        modules: list[tuple[str, Any]],
        prerequisites: Prerequisites | None = None,
        models: Models | None = None,
        autostart: bool | None = None,
    ) -> None:
        """Bind the config, where the choice is kept, the composition and the ordered modules.

        `autostart` overrides the remembered choice for this process (None follows it).
        """
        self.config = config
        self.state_path = state_path
        self.prepare = prepare
        self.modules = list(modules)
        self.prerequisites = prerequisites
        self.models = models
        self.autostart = autostart

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """The console's start: bind the modules, then start Banana when it was left running.

        The bound modules' stores serve the dashboard while Banana is stopped.
        """
        self._read_choice()
        try:
            self._prepare()
        except Exception as exc:  # a broken config stops Banana, never the dashboard
            Log.error(f"service: the modules could not be set up: {exc!r}")
        wanted = self.autostart if self.autostart is not None else self.wanted == "running"
        Log.info(f"service: {'starting' if wanted else 'left stopped'} (choice: {self.wanted})")
        if wanted:
            self.request("start", by="boot")

    async def stop(self) -> None:
        """The process is exiting: cancel a start in flight, finish a stop, stop what runs."""
        self._exiting = True  # a restart's stop does not go on to start
        task = self._task
        if task is not None and not task.done():
            if self.state != "stopping":
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if self.state != "stopped":  # whatever it was doing, the modules stop with the process
            await self._stop("exit", remember=False)

    # ------------------------------------------------------------------ requests

    def request(self, action: str, by: str = "dashboard") -> dict[str, Any]:
        """Start, stop or restart in the background; the current status comes back at once.

        Raises `ServiceBusy` while a transition runs and `ValueError` for an unknown action.
        A start of a running service or a stop of a stopped one only records the choice.
        """
        if action not in ("start", "stop", "restart"):
            raise ValueError(f"unknown action: {action}")
        if self._task is not None and not self._task.done():
            raise ServiceBusy(
                f"a {self.transition.action if self.transition else 'transition'} is running"
            )
        if action == "start" and self.state == "running":
            self._remember("running", by)
            return self.status()
        if action == "stop" and self.state == "stopped":
            self._remember("stopped", by)
            return self.status()
        # The task first (it needs the running loop and only runs once this returns), the
        # state after, so a failed request leaves the service as it was.
        self._task = asyncio.create_task(self._run(action, by), name=f"service-{action}")
        if action == "start":  # the reply already shows the steps, all pending
            self.transition = ServiceTransition("start", by, self._steps())
            self._set_state("starting")
        else:
            self._set_state("stopping")
        return self.status()

    async def wait(self) -> None:
        """Until the transition in flight (if any) is over (tests, the CLI's close)."""
        if self._task is not None:
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _run(self, action: str, by: str) -> None:
        if action in ("stop", "restart"):
            await self._stop(by, remember=action == "stop")
        if action in ("start", "restart") and not self._exiting:
            await self._start(by)

    # ------------------------------------------------------------------ start

    def _steps(self) -> list[ServiceStep]:
        ids = ["config", "models"] + [name for name, _ in self.modules]
        return [ServiceStep(step_id, STEP_TITLES.get(step_id, step_id)) for step_id in ids]

    async def _start(self, by: str) -> None:
        Log.info0(by)
        transition = self.transition
        if transition is None or transition.action != "start" or transition.finished_at:
            transition = ServiceTransition("start", by, self._steps())
            self.transition = transition
        self._set_state("starting")
        started: list[tuple[str, Any]] = []
        try:
            if not await self._check_config(transition) or not await self._check_models(transition):
                raise _Abort
            for name, session in self.modules:
                step = transition.step(name)
                step.begin()
                started.append((name, session))  # a failed or cancelled start is stopped too
                try:
                    await _call(session.start)
                except Exception as exc:
                    Log.error(f"service: {name} failed to start: {exc!r}")
                    step.items = [
                        {"id": name, "title": step.title, "level": "bad", "detail": repr(exc)[:300]}
                    ]
                    step.finish("bad", "failed to start")
                    raise _Abort from exc
                step.items = self._check(name, session)
                level = worst_level(step.items)
                step.finish({"off": "skipped"}.get(level, level))
                if level == "bad":
                    raise _Abort
        except (_Abort, asyncio.CancelledError) as exc:
            failed = next((s for s in transition.steps if s.state == "bad"), None)
            transition.error = self._failure(failed) if failed else "cancelled"
            for step in transition.steps:
                if step.state == "pending":
                    step.state = "skipped"
            Log.warning(f"service: start aborted: {transition.error}")
            await self._take_down(started)
            transition.ok = False
            transition.finished_at = time.time()
            self._set_state("stopped")
            if isinstance(exc, asyncio.CancelledError):
                raise
            return
        transition.ok = True
        transition.finished_at = time.time()
        self._remember("running", by)
        self._set_state("running")
        warned = [s.title for s in transition.steps if s.state == "warn"]
        Log.info(
            f"service: running after {transition.finished_at - transition.started_at:.1f} s"
            + (f" (warnings: {', '.join(warned)})" if warned else "")
        )

    async def _check_config(self, transition: ServiceTransition) -> bool:
        """Re-read the config, check the prerequisites, bind backends and modules to it."""
        step = transition.step("config")
        step.begin("reading the configuration")
        try:
            assert self.config is not None
            spec = self.config.load()
            items = [_item(i, MODULE_TABS["config"]) for i in self._prerequisites()]
            if spec is None:
                items.append(
                    {
                        "id": "config",
                        "title": "config.json",
                        "level": "bad",
                        "detail": "missing",
                        "tab": "system",
                    }
                )
            step.items = items
            if worst_level(items) == "bad":
                step.finish("bad", "fix these first")
                return False
            self.config.apply(spec)
            self._prepare()
        except Exception as exc:
            Log.error(f"service: configuration: {exc!r}")
            step.items.append(
                {
                    "id": "config",
                    "title": "configuration",
                    "level": "bad",
                    "detail": repr(exc)[:300],
                    "tab": "system",
                }
            )
            step.finish("bad", "the configuration could not be applied")
            return False
        level = worst_level(step.items)
        step.finish(level if level != "off" else "ok", "")
        return True

    async def _check_models(self, transition: ServiceTransition) -> bool:
        """Download the on-host models that are missing (with progress in the step's detail)."""
        step = transition.step("models")
        if self.models is None:
            step.finish("skipped", "")
            return True
        step.begin("checking")

        def progress(detail: str) -> None:
            step.detail = detail

        try:
            step.items = [_item(i, MODULE_TABS["models"]) for i in await self.models(progress)]
        except Exception as exc:
            Log.error(f"service: models: {exc!r}")
            step.items = [
                {
                    "id": "models",
                    "title": "models",
                    "level": "bad",
                    "detail": repr(exc)[:300],
                    "tab": "voice",
                }
            ]
        level = worst_level(step.items)
        step.finish("bad" if level == "bad" else "ok", "" if level != "bad" else "missing")
        return level != "bad"

    # ------------------------------------------------------------------ stop

    async def _stop(self, by: str, remember: bool) -> None:
        Log.info0(by)
        steps = [ServiceStep(name, STEP_TITLES.get(name, name)) for name, _ in self.modules]
        transition = ServiceTransition("stop", by, list(reversed(steps)))
        self.transition = transition
        self._set_state("stopping")
        if remember:  # the owner's choice, whatever happens to the process from here
            self._remember("stopped", by)
        await self._take_down(self.modules, transition)
        transition.ok = True
        transition.finished_at = time.time()
        self._set_state("stopped")
        Log.info(f"service: stopped in {transition.finished_at - transition.started_at:.1f} s")

    async def _take_down(
        self, modules: list[tuple[str, Any]], transition: ServiceTransition | None = None
    ) -> None:
        """Stop modules in reverse order (each bounded, failures logged), then unbind backends."""
        for name, session in reversed(modules):
            step = transition.step(name) if transition is not None else None
            if step is not None:
                step.begin()
            try:
                await asyncio.wait_for(_call(session.stop), STOP_TIMEOUT_S)
                if step is not None:
                    step.finish("ok")
            except Exception as exc:  # one module's failure never keeps the others running
                Log.error(f"service: {name} did not stop cleanly: {exc!r}")
                if step is not None:
                    step.finish("warn", repr(exc)[:200])
        if self.config is not None:
            try:
                self.config.release()
            except Exception as exc:
                Log.warning(f"service: releasing the backends: {exc!r}")

    # ------------------------------------------------------------------ reports

    def _check(self, name: str, session: Any) -> list[dict[str, Any]]:
        check = getattr(session, "check", None)
        if not callable(check):
            return []
        tab = MODULE_TABS.get(name, "system")
        try:
            items = [_item(item, tab) for item in check()]
        except Exception as exc:
            Log.warning(f"service: {name} check: {exc!r}")
            items = [
                {
                    "id": "check",
                    "title": STEP_TITLES.get(name, name),
                    "level": "warn",
                    "detail": f"check failed: {exc!r}"[:300],
                    "tab": tab,
                }
            ]
        for item in items:  # unique across modules in the readiness list
            item["id"] = f"{name}.{item.get('id', name)}"
        return items

    def checks(self) -> list[dict[str, Any]]:
        """Every running module's check items now (readiness while running; memory only)."""
        if self.state != "running":
            return []
        out: list[dict[str, Any]] = []
        for name, session in self.modules:
            out.extend(self._check(name, session))
        return out

    @property
    def running(self) -> bool:
        """Whether Banana is up."""
        return self.state == "running"

    def status(self) -> dict[str, Any]:
        """The state, the remembered choice and the current or last transition."""
        transition = self.transition
        return {
            "state": self.state,
            "since": self.since,
            "wanted": self.wanted,
            "changed_at": self.changed_at,
            "changed_by": self.changed_by,
            "busy": self._task is not None and not self._task.done(),
            "transition": transition.as_dict() if transition is not None else None,
        }

    def live(self) -> dict[str, Any]:
        """For the Live page's System card (memory only)."""
        transition = self.transition
        return {
            "state": self.state,
            "since": self.since,
            "wanted": self.wanted,
            "last": None
            if transition is None
            else {
                "action": transition.action,
                "ok": transition.ok,
                "error": transition.error,
                "took_s": None
                if transition.finished_at is None
                else round(transition.finished_at - transition.started_at, 1),
            },
        }

    # ------------------------------------------------------------------ helpers

    def _prepare(self) -> None:
        if self.prepare is not None:
            self.prepare()
            self.prepared = True

    def _prerequisites(self) -> list[Any]:
        return list(self.prerequisites()) if self.prerequisites is not None else []

    @staticmethod
    def _failure(step: ServiceStep) -> str:
        bad = next((i for i in step.items if i.get("level") == "bad"), None)
        if bad is None:
            return f"{step.title}: {step.detail}"
        return f"{step.title}: {bad.get('title', '')} — {bad.get('detail', '')}".rstrip(" —")

    def _set_state(self, state: str) -> None:
        self.state = state
        self.since = time.time()

    def _read_choice(self) -> None:
        if self.state_path is None:
            return
        try:
            data = StorageSession.shared.read_json(self.state_path)
        except Exception as exc:
            Log.warning(f"service: {self.state_path.name}: {exc!r}")
            data = None
        if isinstance(data, dict) and data.get("wanted") in ("running", "stopped"):
            self.wanted = str(data["wanted"])
            self.changed_at = data.get("changed_at")
            self.changed_by = str(data.get("by", ""))

    def _remember(self, wanted: str, by: str) -> None:
        if by in ("boot", "exit"):
            return  # only the owner's own Start / Stop is a choice
        self.wanted, self.changed_at, self.changed_by = wanted, time.time(), by
        if self.state_path is None:
            return
        try:
            StorageSession.shared.write_json(
                self.state_path, {"wanted": wanted, "changed_at": self.changed_at, "by": by}
            )
        except Exception as exc:
            Log.warning(f"service: could not remember the choice: {exc!r}")


class _Abort(Exception):
    """A step failed; the start is rolled back."""
