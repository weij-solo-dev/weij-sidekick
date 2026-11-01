"""MCP registry + client pool against a tiny stdio server written with the official SDK."""

from __future__ import annotations

import sys
import textwrap

import pytest

from sidekick.agent import MCPClientPool, MCPRegistry, MCPServer

SERVER = textwrap.dedent(
    '''
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("toy")

    @mcp.tool()
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    @mcp.tool()
    def shout(text: str) -> str:
        """Upper-case the text."""
        return text.upper()

    if __name__ == "__main__":
        mcp.run()
    '''
)


@pytest.mark.slow
async def test_registry_and_pool_with_toy_server(tmp_path):
    script = tmp_path / "toy_server.py"
    script.write_text(SERVER)
    registry = MCPRegistry(tmp_path / "mcp_v1.db")
    server = registry.upsert(MCPServer("toy", "stdio", command=sys.executable, args=(str(script),)))
    assert registry.get("toy") == server and registry.list(enabled_only=True) == [server]
    with pytest.raises(ValueError):
        registry.upsert(MCPServer("bad", "http"))
    pool = MCPClientPool(registry)
    try:
        tools = await pool.tools(server)
        names = sorted(t.name for t in tools)
        assert names == ["mcp.toy.add", "mcp.toy.shout"]
        add = next(t for t in tools if t.name == "mcp.toy.add")
        assert add.parameters["properties"]["a"]["type"] == "integer"
        result = await pool.call("toy", "add", {"a": 2, "b": 3})
        assert result.ok and result.content.strip() == "5"
        result = await pool.call("toy", "shout", {"text": "hi"})
        assert result.ok and "HI" in result.content
        result = await pool.call("toy", "nope", {})
        assert not result.ok
        all_tools = await pool.all_tools()
        assert len(all_tools) == 2
        assert registry.set_enabled("toy", False) and await pool.all_tools() == []
    finally:
        await pool.close()
