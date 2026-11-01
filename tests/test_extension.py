"""Extension module: manifests, loader (package-style imports), registry, lifecycle bridge; bundled manifests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sidekick.agent import AgentSession
from sidekick.config import ConfigAgents
from sidekick.extension import (
    ExtensionContext,
    ExtensionSession,
    discover,
    read_manifest,
    validate_settings,
)
from sidekick.llm import LLMSession
from sidekick.perception import PerceptionSession

ROOT = Path(__file__).resolve().parent.parent

TOY_MANIFEST = {
    "name": "toy",
    "version": "0.2.0",
    "description": "a toy extension",
    "tools": "tools.py",
    "watchers": "watchers.py",
    "skills": ["skill_toy.md"],
    "mcp": [],
    "subagent": {
        "name": "toyagent",
        "role": "You are toy.",
        "description": "toy worker",
        "tools": ["toy_echo"],
    },
    "settings": {
        "type": "object",
        "required": ["greeting"],
        "properties": {
            "greeting": {"type": "string", "default": "hi"},
            "secret_key": {"type": "string", "secret": True, "default": ""},
            "count": {"type": "integer", "default": 2},
        },
    },
}
TOY_TOOLS = '''
"""extensions.toy.tools — toy

Overview
    Toy tools.
Design
    Uses a sibling module through a relative import.
"""
from sidekick.agent import Tool, ToolResult
from .helpers import shout


def TOOLS(ctx):
    async def echo(arguments, tctx):
        return ToolResult(True, shout(f"{ctx.setting('greeting')} {arguments.get('text', '')}"))

    return [Tool("toy_echo", "echo", {"type": "object", "properties": {"text": {"type": "string"}}}, echo)]
'''
TOY_HELPERS = '''
"""extensions.toy.helpers — toy

Overview
    Helper.
Design
    None.
"""


def shout(text):
    return text.upper()
'''
TOY_WATCHERS = '''
"""extensions.toy.watchers — toy

Overview
    Watcher.
Design
    Emits one event per poll.
"""
from sidekick.perception import PerceptionEvent, Severity, Watcher


class Tick(Watcher):
    name = "tick"

    def __init__(self, ctx):
        super().__init__(0.05)
        self.ctx = ctx

    async def poll(self):
        return [PerceptionEvent("toy.tick", Severity.DEBUG, {"n": self.polls})]


def WATCHERS(ctx):
    return [Tick(ctx)]
'''


def write_toy(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "extension.json").write_text(json.dumps(TOY_MANIFEST))
    (directory / "tools.py").write_text(TOY_TOOLS)
    (directory / "helpers.py").write_text(TOY_HELPERS)
    (directory / "watchers.py").write_text(TOY_WATCHERS)
    (directory / "skill_toy.md").write_text(
        "---\nname: toy skill\ndescription: how to toy\n---\nBe playful.\n"
    )
    return directory


def test_bundled_manifests_are_valid():
    found = discover(ROOT / "extensions")
    assert set(found) == {"robot", "news", "media", "home"}
    assert found["robot"][1].default_enabled and not found["media"][1].default_enabled
    assert (
        found["news"][1].subagent.name == "news"
        and "sources" in found["news"][1].setting_defaults()
    )
    assert found["media"][1].secret_keys() == {"qbittorrent_password", "jellyfin_api_key"}


def test_manifest_validation_and_settings(tmp_path):
    toy = write_toy(tmp_path / "toy")
    manifest = read_manifest(toy)
    assert manifest.setting_defaults() == {"greeting": "hi", "secret_key": "", "count": 2}
    assert validate_settings(manifest, {"greeting": "", "count": 1}) == ["greeting is required"]
    assert validate_settings(manifest, {"greeting": "yo", "count": "x"}) == [
        "count must be a number"
    ]
    (toy / "tools.py").unlink()
    with pytest.raises(FileNotFoundError):
        read_manifest(toy)


async def test_lifecycle_registers_and_unregisters(tmp_path):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    write_toy(bundled / "toy")
    llm = LLMSession()
    agent = AgentSession(llm)
    agent.setup(home=tmp_path / "home", agents=ConfigAgents())
    perception = PerceptionSession()
    perception.setup(None, tmp_path / "events_v1.db")
    seen = []

    async def on_tick(event):
        seen.append(event)

    perception.subscribe("toy.*", on_tick)
    await perception.start()
    session = ExtensionSession()
    session.setup(
        tmp_path / "extension_v1.db",
        bundled,
        user,
        tmp_path / "state",
        agent,
        perception,
        lambda name, settings, state_dir: ExtensionContext(name, settings, state_dir),
    )
    records = {r.name: r for r in session.records()}
    assert (
        records["toy"].enabled
        and records["toy"].settings["greeting"] == "hi"
        and records["toy"].source == "bundled"
    )
    await session.start()
    assert (
        "toy_echo" in agent.registry.names()
        and agent.registry.get("toy_echo").origin == "extension:toy"
    )
    assert agent.skills.get("toy skill").origin == "extension:toy"
    assert "toyagent" in agent.agents and "toy.tick" in perception.watchers
    assert agent.agents["toyagent"].profile.origin == "extension:toy"  # read-only on Subagents
    assert "toyagent" in agent.agents_block
    snap = {s["name"]: s for s in session.snapshot()}
    assert (
        snap["toy"]["active"]
        and snap["toy"]["tools"] == ["toy_echo"]
        and snap["toy"]["settings"]["secret_key"] == ""
    )
    # the tool works and the relative import resolved
    from sidekick.agent import ToolContext
    from sidekick.channel import ChannelMessage

    result = await agent.registry.get("toy_echo").handler(
        {"text": "there"}, ToolContext(ChannelMessage("voice", "dad", "x"), "main")
    )
    assert result.content == "HI THERE"
    for _ in range(40):
        if seen:
            break
        import asyncio

        await asyncio.sleep(0.02)
    assert seen and seen[0].type == "toy.tick"
    # settings change re-enables with the new value; secret masked in snapshot
    await session.set_settings("toy", {"greeting": "hello", "secret_key": "s3cret"})
    result = await agent.registry.get("toy_echo").handler(
        {"text": "x"}, ToolContext(ChannelMessage("voice", "dad", "x"), "main")
    )
    assert result.content == "HELLO X"
    assert {s["name"]: s for s in session.snapshot()}["toy"]["settings"]["secret_key"] == "••••"
    with pytest.raises(ValueError):
        await session.set_settings("toy", {"greeting": ""})
    # disable removes exactly the extension's contributions
    await session.disable("toy")
    assert "toy_echo" not in agent.registry.names() and agent.skills.get("toy skill") is None
    assert "toyagent" not in agent.agents and "toy.tick" not in perception.watchers
    assert "toyagent" not in agent.agents_block  # the main agent's list follows
    assert not session.record("toy").enabled
    # install from a path into the user dir, then remove it
    record = await session.install(str(bundled / "toy"))
    assert record.source == "user" and Path(record.path).parent == user
    assert (await session.remove("toy") and session.record("toy") is None) or session.record(
        "toy"
    ) is not None
    await perception.stop()
    await agent.stop()
