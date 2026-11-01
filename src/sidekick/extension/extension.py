"""sidekick.extension.extension — ExtensionSession: discovery, lifecycle and the registration bridge

Overview
    Extensions bring integrations and the robot's body / perception capabilities to the agent
    (invariant 19). This façade discovers bundled extensions (`extensions/`) and user-installed
    ones (`.derived_data/extensions/`), keeps their state in `extension_v1.db`, and on
    `enable()` routes each contribution to the module that owns it — tools, skills, MCP servers
    and the subagent into `agent`, built-in event jobs into `automation`, watchers into
    `perception` — all tagged `extension:<name>` so `disable()` removes exactly those.
    `install()` copies a directory or clones a git URL; `update()` pulls; `remove()` deletes.
Design
    `setup` receives the peers an extension may use (untyped beyond `agent`, `automation` and
    `perception`, so the façade imports nothing else) and builds each extension's context from
    them; a test or the CLI may pass its own context factory instead. Unlike a core module it
    wires and unwires while sidekick runs, because extensions are enabled, disabled, installed
    and removed from the dashboard. Failures inside an extension are
    recorded on its row and never take the process down. Settings are validated against the
    manifest's JSON schema in the simple way that matters (required keys, types for string /
    number / boolean) — no schema library.
    `check()` reports each enabled extension active and its watchers' last errors (block #87).
Depends on
    sidekick.log, sidekick.storage, sidekick.agent, sidekick.automation, sidekick.perception.

See Also
--------
    AGENTS.md "Extensions", PLAN.md block "[2026-10-26 #20]".

"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

from sidekick.agent import AgentProfile, AgentSession, MCPServer, Tool
from sidekick.automation import AutomationSession
from sidekick.log import Log
from sidekick.perception import PerceptionSession, Watcher

from .loader import discover, load_factory, read_manifest, read_skill
from .registry import ExtensionRegistry
from .schemas import ExtensionContext, ExtensionManifest, ExtensionRecord

ContextFactory = Callable[[str, dict[str, Any], Path], ExtensionContext]


class ExtensionSession:
    """Lifecycle + bridge."""

    shared: ClassVar[ExtensionSession]

    def __init__(self) -> None:
        self.registry: ExtensionRegistry | None = None
        self.bundled_dir: Path | None = None
        self.user_dir: Path | None = None
        self.state_root: Path | None = None
        self.agent: AgentSession | None = None
        self.perception: PerceptionSession | None = None
        self.automation: AutomationSession | None = None
        self.context_factory: ContextFactory | None = None
        self._peers: dict[str, Any] = {}
        self.manifests: dict[str, tuple[Path, ExtensionManifest]] = {}
        self._active: dict[str, dict[str, Any]] = {}

    def setup(
        self,
        db_path: Path,
        bundled_dir: Path,
        user_dir: Path,
        state_root: Path,
        agent: AgentSession | None,
        perception: PerceptionSession | None,
        context_factory: ContextFactory | None = None,
        *,
        automation: AutomationSession | None = None,
        spec: Any = None,
        body: Any = None,
        contacts: Any = None,
        interaction: Any = None,
        llm: Any = None,
        vision: bool = False,
    ) -> None:
        """Bind stores, directories and the peers an extension's context hands out."""
        self.registry = ExtensionRegistry(db_path)
        self.bundled_dir, self.user_dir, self.state_root = bundled_dir, user_dir, state_root
        self.agent, self.perception, self.automation = agent, perception, automation
        self._peers = {
            "spec": spec,
            "body": body,
            "contacts": contacts,
            "perception": perception,
            "interaction": interaction,
            "agent": agent,
            "llm": llm,
            "vision": vision,
        }
        self.context_factory = context_factory or self._context
        self.refresh()

    def _context(self, name: str, settings: dict[str, Any], state_dir: Path) -> ExtensionContext:
        """What one extension may use: its settings and state dir plus the bound peers."""
        return ExtensionContext(name, settings, state_dir, **self._peers)

    # ------------------------------------------------------------- discovery

    def refresh(self) -> None:
        """Rescan directories and make sure every extension has a record."""
        assert (
            self.registry is not None and self.bundled_dir is not None and self.user_dir is not None
        )
        found = {**discover(self.bundled_dir), **discover(self.user_dir)}
        self.manifests = found
        for name, (path, manifest) in found.items():
            record = self.registry.get(name)
            source = (
                "user"
                if self.user_dir in path.parents or path.parent == self.user_dir
                else "bundled"
            )
            if record is None:
                self.registry.save(
                    ExtensionRecord(
                        name,
                        str(path),
                        manifest.version,
                        manifest.default_enabled,
                        manifest.setting_defaults(),
                        source,
                    )
                )
            elif record.path != str(path) or record.version != manifest.version:
                self.registry.save(
                    ExtensionRecord(
                        name,
                        str(path),
                        manifest.version,
                        record.enabled,
                        {**manifest.setting_defaults(), **record.settings},
                        source,
                        record.installed_ts,
                        record.error,
                    )
                )

    def records(self) -> list[ExtensionRecord]:
        """Known extensions."""
        return self.registry.list_records() if self.registry is not None else []

    def record(self, name: str) -> ExtensionRecord | None:
        """One record."""
        return self.registry.get(name) if self.registry is not None else None

    def manifest(self, name: str) -> ExtensionManifest | None:
        """One manifest."""
        found = self.manifests.get(name)
        return found[1] if found else None

    # -------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Enable every extension whose record says so."""
        for record in self.records():
            if record.enabled:
                await self.enable(record.name, persist=False)

    async def stop(self) -> None:
        """Deactivate everything (records untouched)."""
        for name in list(self._active):
            await self._deactivate(name)

    async def enable(self, name: str, persist: bool = True) -> ExtensionRecord | None:
        """Load and register an extension."""
        assert (
            self.registry is not None
            and self.context_factory is not None
            and self.state_root is not None
        )
        found = self.manifests.get(name)
        record = self.registry.get(name)
        if found is None or record is None:
            Log.warning(f"extension {name!r} unknown")
            return None
        path, manifest = found
        if name in self._active:
            await self._deactivate(name)
        for required in manifest.requires:
            if required not in self._active and required not in {
                r.name for r in self.records() if r.enabled
            }:
                Log.warning(f"extension {name}: requires {required}")
        settings = {**manifest.setting_defaults(), **record.settings}
        state_dir = self.state_root / name
        state_dir.mkdir(parents=True, exist_ok=True)
        context = self.context_factory(name, settings, state_dir)
        active: dict[str, Any] = {
            "tools": [],
            "watchers": [],
            "skills": [],
            "mcp": [],
            "subagent": None,
            "automations": [],
        }
        origin = f"extension:{name}"
        try:
            if manifest.tools:
                tools: list[Tool] = load_factory(path, manifest.tools, name, "TOOLS")(context)
                tools = [replace(t, origin=origin) for t in tools]
                if self.agent is not None:
                    self.agent.register_tools(tools)
                active["tools"] = [t.name for t in tools]
            if manifest.watchers:
                watchers: list[Watcher] = load_factory(path, manifest.watchers, name, "WATCHERS")(
                    context
                )
                for watcher in watchers:
                    watcher.name = f"{name}.{watcher.name}"
                    if self.perception is not None:
                        self.perception.register_watcher(watcher)
                        if self.perception.started:
                            await watcher.start(self.perception.publish)
                active["watchers"] = watchers
            if self.agent is not None:
                for skill_file in manifest.skills:
                    skill = self.agent.skills.upsert_markdown(
                        read_skill(path, skill_file), origin=origin
                    )
                    active["skills"].append(skill.name)
                for server in manifest.mcp:
                    self.agent.mcp_registry.upsert(
                        MCPServer(
                            server.name,
                            "http" if server.transport == "http" else "stdio",
                            server.command,
                            tuple(server.args),
                            dict(server.env),
                            server.url,
                            dict(server.headers),
                            origin,
                        )
                    )
                    active["mcp"].append(server.name)
                if manifest.mcp:
                    await self.agent.refresh_mcp()
                jobs = self.automation.jobs if self.automation is not None else None
                for automation in manifest.automations:
                    if jobs is None:
                        break
                    job = jobs.ensure_builtin(
                        f"{name}.{automation.name}",
                        automation.event,
                        automation.prompt,
                        delivery=automation.delivery,
                        event_filter=dict(automation.filter),
                        origin=origin,
                    )
                    active["automations"].append(job.name)
                if manifest.subagent is not None:
                    sub = manifest.subagent
                    self.agent.register_agent(
                        AgentProfile(
                            sub.name,
                            sub.role,
                            sub.llm_slot,
                            description=sub.description,
                            tools=tuple(sub.tools),
                            mcp_servers=tuple(sub.mcp_servers),
                            skills=tuple(sub.skills),
                            max_steps=sub.max_steps,
                            timeout_s=sub.timeout_s,
                            origin=origin,
                        )
                    )
                    active["subagent"] = sub.name
        except Exception as exc:
            Log.error(f"extension {name}: enable failed: {exc!r}")
            self.registry.set_enabled(name, False, repr(exc))
            if self.agent is not None:
                self.agent.unregister_origin(origin)
            return self.registry.get(name)
        self._active[name] = active
        if persist:
            self.registry.set_enabled(name, True, None)
        else:
            self.registry.set_enabled(name, True, None)
        Log.info(
            f"extension {name} enabled: tools={active['tools']} watchers={len(active['watchers'])} skills={active['skills']} subagent={active['subagent']}"
        )
        return self.registry.get(name)

    async def _deactivate(self, name: str) -> None:
        active = self._active.pop(name, None)
        if active is None:
            return
        origin = f"extension:{name}"
        if self.agent is not None:
            self.agent.unregister_origin(origin)
            self.agent.skills.delete_origin(origin)
            if self.automation is not None and self.automation.jobs is not None:
                for job_name in active.get("automations", []):
                    self.automation.jobs.delete_builtin(job_name)
            if self.agent.mcp_registry.delete_origin(origin):
                for server in active.get("mcp", []):
                    await self.agent.mcp.disconnect(server)
                await self.agent.refresh_mcp()
            if active.get("subagent"):
                self.agent.unregister_agent(active["subagent"])
        for watcher in active.get("watchers", []):
            await watcher.stop()
            if self.perception is not None:
                self.perception.unregister_watcher(watcher.name)

    async def disable(self, name: str) -> ExtensionRecord | None:
        """Unregister and mark disabled."""
        assert self.registry is not None
        await self._deactivate(name)
        self.registry.set_enabled(name, False, None)
        Log.info(f"extension {name} disabled")
        return self.registry.get(name)

    async def set_settings(self, name: str, values: dict[str, Any]) -> ExtensionRecord | None:
        """Validate, save and re-enable when active."""
        assert self.registry is not None
        manifest = self.manifest(name)
        record = self.registry.get(name)
        if manifest is None or record is None:
            return None
        merged = {**record.settings, **values}
        problems = validate_settings(manifest, merged)
        if problems:
            raise ValueError("; ".join(problems))
        self.registry.set_settings(name, merged)
        if name in self._active:
            await self.enable(name)
        return self.registry.get(name)

    async def install(self, source: str, name_hint: str | None = None) -> ExtensionRecord:
        """Copy a directory or clone a git URL into the user extensions directory."""
        assert self.user_dir is not None and self.registry is not None
        self.user_dir.mkdir(parents=True, exist_ok=True)
        src = Path(source).expanduser()
        if src.exists():
            manifest = read_manifest(src)
            target = self.user_dir / manifest.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target)
        else:
            name = name_hint or source.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
            target = self.user_dir / name
            if target.exists():
                shutil.rmtree(target)
            result = subprocess.run(
                ["git", "clone", "--depth", "1", source, str(target)],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                raise RuntimeError(f"git clone failed: {result.stderr.strip()[:300]}")
            manifest = read_manifest(target)
            if manifest.name != name:
                final = self.user_dir / manifest.name
                if final.exists():
                    shutil.rmtree(final)
                target.rename(final)
                target = final
        self.refresh()
        record = self.registry.get(manifest.name)
        assert record is not None
        Log.info(f"extension installed: {manifest.name} from {source}")
        return record

    async def update(self, name: str) -> ExtensionRecord | None:
        """`git pull` a user-installed extension and re-enable it."""
        assert self.registry is not None
        record = self.registry.get(name)
        if record is None or record.source != "user":
            return record
        path = Path(record.path)
        if (path / ".git").exists():
            result = subprocess.run(
                ["git", "-C", str(path), "pull", "--ff-only"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                raise RuntimeError(f"git pull failed: {result.stderr.strip()[:300]}")
        self.refresh()
        self.registry.touch(name)
        if record.enabled:
            await self.enable(name)
        return self.registry.get(name)

    async def remove(self, name: str) -> bool:
        """Disable and delete a user-installed extension (bundled ones are only disabled)."""
        assert self.registry is not None
        record = self.registry.get(name)
        if record is None:
            return False
        await self.disable(name)
        if record.source == "user":
            shutil.rmtree(record.path, ignore_errors=True)
            self.registry.delete(name)
            self.manifests.pop(name, None)
        return True

    # --------------------------------------------------------------- reporting

    def check(self) -> list[dict[str, Any]]:
        """Readiness items: every enabled extension active, its watchers polling (advice only)."""
        items: list[dict[str, Any]] = []
        for record in self.records():
            if not record.enabled:
                continue
            active = self._active.get(record.name)
            if active is None:
                items.append(
                    {
                        "id": record.name,
                        "title": record.name,
                        "level": "warn",
                        "detail": record.error or "not active",
                    }
                )
                continue
            watchers = active.get("watchers", [])
            failing = [w for w in watchers if getattr(w, "last_error", None)]
            detail = f"{len(active.get('tools', []))} tool(s)"
            if watchers:
                detail += f" · {len(watchers)} watcher(s)"
            if failing:
                detail += f" · {getattr(failing[0], 'name', '?')}: {failing[0].last_error}"[:200]
            items.append(
                {
                    "id": record.name,
                    "title": record.name,
                    "level": "warn" if failing else "ok",
                    "detail": detail,
                }
            )
        if not items:
            items.append({"id": "none", "title": "extensions", "level": "off", "detail": "none on"})
        return items

    def live(self) -> dict[str, Any]:
        """Enabled extensions and their watchers' last poll, for the Live page (memory only)."""
        now = time.time()
        watchers = []
        for name, active in sorted(self._active.items()):
            for watcher in active.get("watchers", []):
                polled = getattr(watcher, "last_poll_ts", None)
                watchers.append(
                    {
                        "extension": name,
                        "name": getattr(watcher, "name", "?"),
                        "polls": getattr(watcher, "polls", 0),
                        "errors": getattr(watcher, "errors", 0),
                        "last_error": getattr(watcher, "last_error", None),
                        "ago_s": round(now - polled, 1) if polled else None,
                    }
                )
        return {
            "active": sorted(self._active),
            "installed": len(self.manifests),
            "tools": sum(len(a.get("tools", [])) for a in self._active.values()),
            "watchers": watchers,
        }

    def snapshot(self) -> list[dict[str, Any]]:
        """Dashboard rows (secrets masked)."""
        out: list[dict[str, Any]] = []
        for record in self.records():
            manifest = self.manifest(record.name)
            secrets = manifest.secret_keys() if manifest else set()
            settings = {
                k: ("••••" if k in secrets and v else v) for k, v in record.settings.items()
            }
            active = self._active.get(record.name, {})
            out.append(
                {
                    "name": record.name,
                    "version": record.version,
                    "description": manifest.description if manifest else "",
                    "source": record.source,
                    "path": record.path,
                    "enabled": record.enabled,
                    "active": record.name in self._active,
                    "error": record.error,
                    "settings": settings,
                    "settings_schema": manifest.settings if manifest else {},
                    "tools": active.get("tools", []),
                    "skills": active.get("skills", []),
                    "mcp": active.get("mcp", []),
                    "subagent": active.get("subagent"),
                    "watchers": [w.name for w in active.get("watchers", [])],
                }
            )
        return out


def validate_settings(manifest: ExtensionManifest, values: dict[str, Any]) -> list[str]:
    """Minimal JSON-schema checks: required keys and primitive types."""
    problems: list[str] = []
    schema = manifest.settings or {}
    properties = schema.get("properties") or {}
    for key in schema.get("required") or []:
        if values.get(key) in (None, ""):
            problems.append(f"{key} is required")
    for key, value in values.items():
        prop = properties.get(key)
        if not isinstance(prop, dict) or value is None:
            continue
        expected = prop.get("type")
        if expected == "string" and not isinstance(value, str):
            problems.append(f"{key} must be a string")
        elif expected == "boolean" and not isinstance(value, bool):
            problems.append(f"{key} must be true or false")
        elif expected in ("number", "integer") and not isinstance(value, int | float):
            problems.append(f"{key} must be a number")
        elif expected == "array" and not isinstance(value, list):
            problems.append(f"{key} must be a list")
    return problems
