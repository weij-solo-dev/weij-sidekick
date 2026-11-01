"""sidekick.extension.schemas — manifests, the context handed to an extension, and registry rows

Overview
    `ExtensionManifest` validates `extension.json`; `ExtensionContext` is the one object an
    extension's `TOOLS(ctx)` / `WATCHERS(ctx)` factories receive (its settings plus the core
    sessions it may use); `ExtensionRecord` is what the registry stores (installed path,
    enabled flag, settings values).
Design
    Pydantic for the manifest (user-editable JSON), dataclasses for the rest. The context exposes
    exactly the modules `extensions/*` may import per AGENTS.md: body, contacts, perception,
    interaction, agent, llm; everything is optional so an extension degrades when a peer is off.
Depends on
    pydantic.

See Also
--------
    AGENTS.md "Extensions", PLAN.md block "[2026-10-26 #20]".

"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ExtensionSubagent(BaseModel):
    """A subagent profile contributed by an extension."""

    model_config = ConfigDict(extra="forbid")

    name: str
    role: str
    description: str = ""
    llm_slot: str = "smart"
    tools: list[str] = Field(default_factory=lambda: ["*"])
    skills: list[str] = Field(default_factory=lambda: ["*"])
    mcp_servers: list[str] = Field(default_factory=lambda: ["*"])
    max_steps: int = 8
    timeout_s: float = 120.0


class ExtensionMCPServer(BaseModel):
    """An MCP server contributed by an extension."""

    model_config = ConfigDict(extra="forbid")

    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)


class ExtensionAutomation(BaseModel):
    """A built-in event job an extension contributes (static, no code)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_\-]{0,31}$")
    event: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    delivery: Literal["in_person", "remote", "both", "auto"] = "auto"
    filter: dict[str, Any] = Field(default_factory=dict)


class ExtensionManifest(BaseModel):
    """`extension.json`."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_\-]{0,31}$")
    version: str = "0.1.0"
    description: str = ""
    tools: str | None = None
    watchers: str | None = None
    skills: list[str] = Field(default_factory=list)
    mcp: list[ExtensionMCPServer] = Field(default_factory=list)
    subagent: ExtensionSubagent | None = None
    automations: list[ExtensionAutomation] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)
    default_enabled: bool = True
    requires: list[str] = Field(default_factory=list)

    def setting_defaults(self) -> dict[str, Any]:
        """Default values from the JSON schema's `properties`."""
        out: dict[str, Any] = {}
        for key, schema in (self.settings.get("properties") or {}).items():
            if isinstance(schema, dict) and "default" in schema:
                out[key] = schema["default"]
        return out

    def secret_keys(self) -> set[str]:
        """Settings flagged `"secret": true` (masked on the dashboard)."""
        return {
            k
            for k, s in (self.settings.get("properties") or {}).items()
            if isinstance(s, dict) and s.get("secret")
        }


@dataclass(slots=True)
class ExtensionContext:
    """What an extension may use."""

    name: str
    settings: dict[str, Any]
    state_dir: Path
    spec: Any = None
    body: Any = None
    contacts: Any = None
    perception: Any = None
    interaction: Any = None
    agent: Any = None
    llm: Any = None
    vision: bool = False

    def setting(self, key: str, default: Any = None) -> Any:
        """A setting value with a default."""
        value = self.settings.get(key)
        return default if value in (None, "") else value


@dataclass(frozen=True, slots=True)
class ExtensionRecord:
    """Registry row."""

    name: str
    path: str
    version: str
    enabled: bool
    settings: dict[str, Any] = field(default_factory=dict)
    source: str = "bundled"
    installed_ts: float = field(default_factory=time.time)
    error: str | None = None
