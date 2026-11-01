"""sidekick.agent.mcp — registry of MCP servers and a client pool using the official SDK as transport

Overview
    Users and extensions register MCP servers (`stdio` command or `http` URL) in `mcp_v1.db`.
    `MCPClientPool` connects lazily with the official `mcp` SDK, lists each server's tools once,
    and exposes them to the agent as `Tool`s named `mcp.<server>.<tool>`; calls are forwarded and
    their text content returned. Everything else (which agent may use which server, confirm
    gating, tracing) stays in sidekick (AGENTS.md principle 2: the SDK is only a transport).
Design
    One `AsyncExitStack` per connected server keeps the session alive for the process; a failed
    call drops the session so the next call reconnects. Tool schemas from the server are passed
    through as the function parameters. Disabled servers are kept but not connected.
Depends on
    sidekick.log, sidekick.storage, mcp (lazy).

See Also
--------
    AGENTS.md "Agent swarm" (MCP).

"""

from __future__ import annotations

import json
import re
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from sidekick.log import Log
from sidekick.storage import Database

from .schemas import MCPServer, Tool, ToolContext, ToolResult

MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS mcp_servers (
        name TEXT PRIMARY KEY, transport TEXT NOT NULL, command TEXT, args TEXT, env TEXT,
        url TEXT, headers TEXT, origin TEXT NOT NULL, enabled INTEGER NOT NULL
    );
    """
]

_SAFE = re.compile(r"[^a-zA-Z0-9_\-]")


def tool_name(server: str, tool: str) -> str:
    """Namespaced tool name the LLM sees."""
    return f"mcp.{_SAFE.sub('_', server)}.{_SAFE.sub('_', tool)}"


class MCPRegistry:
    """CRUD over server configs."""

    def __init__(self, path: Path) -> None:
        self.db = Database(path, MIGRATIONS)

    @staticmethod
    def _row(row: Any) -> MCPServer:
        return MCPServer(
            name=row["name"],
            transport=row["transport"],
            command=row["command"] or "",
            args=tuple(json.loads(row["args"] or "[]")),
            env=json.loads(row["env"] or "{}"),
            url=row["url"] or "",
            headers=json.loads(row["headers"] or "{}"),
            origin=row["origin"],
            enabled=bool(row["enabled"]),
        )

    def upsert(self, server: MCPServer) -> MCPServer:
        """Create or replace."""
        if not server.name.strip():
            raise ValueError("server needs a name")
        if server.transport == "stdio" and not server.command:
            raise ValueError("stdio server needs a command")
        if server.transport == "http" and not server.url:
            raise ValueError("http server needs a url")
        self.db.execute(
            "INSERT INTO mcp_servers (name, transport, command, args, env, url, headers, origin, enabled)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET transport = excluded.transport,"
            " command = excluded.command, args = excluded.args, env = excluded.env, url = excluded.url,"
            " headers = excluded.headers, origin = excluded.origin, enabled = excluded.enabled",
            (
                server.name,
                server.transport,
                server.command,
                json.dumps(list(server.args)),
                json.dumps(server.env),
                server.url,
                json.dumps(server.headers),
                server.origin,
                int(server.enabled),
            ),
        )
        Log.info(f"mcp server saved: {server.name} ({server.transport}, {server.origin})")
        return server

    def get(self, name: str) -> MCPServer | None:
        """One server."""
        rows = self.db.query("SELECT * FROM mcp_servers WHERE name = ?", (name,))
        return self._row(rows[0]) if rows else None

    def delete(self, name: str) -> bool:
        """Remove."""
        return self.db.execute("DELETE FROM mcp_servers WHERE name = ?", (name,)) > 0

    def delete_origin(self, origin: str) -> int:
        """Remove every server an extension contributed."""
        return self.db.execute("DELETE FROM mcp_servers WHERE origin = ?", (origin,))

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """Toggle."""
        return (
            self.db.execute(
                "UPDATE mcp_servers SET enabled = ? WHERE name = ?", (int(enabled), name)
            )
            > 0
        )

    def list(self, enabled_only: bool = False) -> list[MCPServer]:
        """All servers by name."""
        sql = (
            "SELECT * FROM mcp_servers"
            + (" WHERE enabled = 1" if enabled_only else "")
            + " ORDER BY name"
        )
        return [self._row(r) for r in self.db.query(sql)]


class MCPClientPool:
    """Live connections and tool surfacing."""

    def __init__(self, registry: MCPRegistry) -> None:
        self.registry = registry
        self._sessions: dict[str, Any] = {}
        self._stacks: dict[str, AsyncExitStack] = {}
        self._tools: dict[str, list[Tool]] = {}
        self.errors: dict[str, str] = {}

    async def connect(self, server: MCPServer) -> Any:
        """Open (or reuse) a session."""
        if server.name in self._sessions:
            return self._sessions[server.name]
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        stack = AsyncExitStack()
        try:
            if server.transport == "stdio":
                params = StdioServerParameters(
                    command=server.command, args=list(server.args), env=server.env or None
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            else:
                from mcp.client.streamable_http import streamablehttp_client

                read, write, _ = await stack.enter_async_context(
                    streamablehttp_client(server.url, headers=server.headers or None)
                )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except Exception as exc:
            await stack.aclose()
            self.errors[server.name] = repr(exc)
            Log.warning(f"mcp {server.name}: connect failed: {exc!r}")
            raise
        self._sessions[server.name] = session
        self._stacks[server.name] = stack
        self.errors.pop(server.name, None)
        Log.info(f"mcp {server.name}: connected ({server.transport})")
        return session

    async def disconnect(self, name: str) -> None:
        """Close one session."""
        self._sessions.pop(name, None)
        self._tools.pop(name, None)
        stack = self._stacks.pop(name, None)
        if stack is not None:
            try:
                await stack.aclose()
            except Exception as exc:
                Log.debug(f"mcp {name}: close: {exc!r}")

    async def close(self) -> None:
        """Close everything."""
        for name in list(self._stacks):
            await self.disconnect(name)

    async def tools(self, server: MCPServer, refresh: bool = False) -> list[Tool]:
        """The server's tools as sidekick tools (cached)."""
        if not refresh and server.name in self._tools:
            return self._tools[server.name]
        session = await self.connect(server)
        listed = await session.list_tools()
        tools: list[Tool] = []
        for item in listed.tools:
            schema = dict(
                getattr(item, "inputSchema", None) or {"type": "object", "properties": {}}
            )
            tools.append(
                Tool(
                    tool_name(server.name, item.name),
                    (item.description or item.name)[:1000],
                    schema,
                    self._handler(server.name, item.name),
                    confirm=False,
                    origin=f"mcp:{server.name}",
                )
            )
        self._tools[server.name] = tools
        Log.info(f"mcp {server.name}: {len(tools)} tool(s)")
        return tools

    def _handler(self, server_name: str, name: str) -> Any:
        async def call(arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
            return await self.call(server_name, name, arguments)

        return call

    async def call(self, server_name: str, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Forward a tool call."""
        server = self.registry.get(server_name)
        if server is None or not server.enabled:
            return ToolResult.error(f"mcp server {server_name!r} is not available")
        try:
            session = await self.connect(server)
            result = await session.call_tool(name, arguments)
        except Exception as exc:
            await self.disconnect(server_name)
            Log.warning(f"mcp {server_name}.{name}: {exc!r}")
            return ToolResult.error(f"mcp call failed: {exc!r}")
        parts: list[str] = []
        for content in getattr(result, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                parts.append(str(text))
            else:
                parts.append(f"[{getattr(content, 'type', 'content')}]")
        is_error = bool(getattr(result, "isError", False))
        return ToolResult(not is_error, "\n".join(parts) or "(no content)")

    async def all_tools(self) -> list[Tool]:
        """Tools of every enabled server (servers that fail are skipped)."""
        out: list[Tool] = []
        for server in self.registry.list(enabled_only=True):
            try:
                out.extend(await self.tools(server))
            except Exception:
                continue
        return out
