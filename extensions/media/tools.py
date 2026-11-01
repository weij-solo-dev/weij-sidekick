"""extensions.media.tools — qBittorrent Web API and Jellyfin REST as agent tools

Overview
    `TOOLS(ctx)` builds `qbt_list`, `qbt_add` (confirm-gated), `jellyfin_search` and
    `jellyfin_now_playing` over the URLs and credentials in the extension settings. Unconfigured
    services return a clear "not configured" result instead of failing.
Design
    qBittorrent: cookie login at `/api/v2/auth/login`, then `/api/v2/torrents/info` and
    `/api/v2/torrents/add`. Jellyfin: `X-Emby-Token` header, `/Items?searchTerm=…&Recursive=true`
    and `/Sessions` for what is playing. One `httpx.AsyncClient` per call keeps the tools
    stateless; errors become `ToolResult(ok=False)`.
Depends on
    sidekick.agent, sidekick.extension, httpx.
"""

from __future__ import annotations

from typing import Any

import httpx

from sidekick.agent import Tool, ToolContext, ToolResult
from sidekick.extension import ExtensionContext


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or []}


async def qbt_client(ctx: ExtensionContext) -> httpx.AsyncClient | None:
    """Logged-in client or None when not configured."""
    url = str(ctx.setting("qbittorrent_url", "") or "").rstrip("/")
    if not url:
        return None
    client = httpx.AsyncClient(base_url=url, timeout=15.0)
    response = await client.post(
        "/api/v2/auth/login",
        data={
            "username": ctx.setting("qbittorrent_username", ""),
            "password": ctx.setting("qbittorrent_password", ""),
        },
    )
    if response.status_code != 200 or response.text.strip() != "Ok.":
        await client.aclose()
        raise RuntimeError(f"qBittorrent login failed ({response.status_code})")
    return client


def jellyfin_client(ctx: ExtensionContext) -> httpx.AsyncClient | None:
    """Client with the API key or None when not configured."""
    url = str(ctx.setting("jellyfin_url", "") or "").rstrip("/")
    key = str(ctx.setting("jellyfin_api_key", "") or "")
    if not url or not key:
        return None
    return httpx.AsyncClient(base_url=url, timeout=15.0, headers={"X-Emby-Token": key})


def _fmt_size(value: Any) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"


def TOOLS(ctx: ExtensionContext) -> list[Tool]:
    """Build the media tools."""

    async def qbt_list(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        try:
            client = await qbt_client(ctx)
        except Exception as exc:
            return ToolResult.error(str(exc))
        if client is None:
            return ToolResult.error("qBittorrent is not configured (settings: qbittorrent_url)")
        try:
            response = await client.get(
                "/api/v2/torrents/info", params={"filter": str(arguments.get("filter", "all"))}
            )
            response.raise_for_status()
            torrents = response.json()
        except Exception as exc:
            return ToolResult.error(f"qBittorrent: {exc!r}")
        finally:
            await client.aclose()
        if not torrents:
            return ToolResult(True, "no torrents")
        lines = [
            f"- {t.get('name')} [{t.get('state')}] {float(t.get('progress', 0)) * 100:.0f}% {_fmt_size(t.get('size'))} ↓{_fmt_size(t.get('dlspeed'))}/s"
            for t in torrents[:15]
        ]
        return ToolResult(True, "\n".join(lines), {"count": len(torrents)})

    async def qbt_add(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        link = str(arguments.get("url", "")).strip()
        if not link:
            return ToolResult.error("url (magnet or torrent link) is required")
        try:
            client = await qbt_client(ctx)
        except Exception as exc:
            return ToolResult.error(str(exc))
        if client is None:
            return ToolResult.error("qBittorrent is not configured")
        try:
            data: dict[str, Any] = {"urls": link}
            if arguments.get("category"):
                data["category"] = str(arguments["category"])
            response = await client.post("/api/v2/torrents/add", data=data)
            ok = response.status_code == 200 and response.text.strip() == "Ok."
        except Exception as exc:
            return ToolResult.error(f"qBittorrent: {exc!r}")
        finally:
            await client.aclose()
        return ToolResult(ok, "download added" if ok else "qBittorrent refused the link")

    async def jellyfin_search(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        query = str(arguments.get("query", "")).strip()
        client = jellyfin_client(ctx)
        if client is None:
            return ToolResult.error(
                "Jellyfin is not configured (settings: jellyfin_url, jellyfin_api_key)"
            )
        try:
            response = await client.get(
                "/Items",
                params={
                    "searchTerm": query,
                    "Recursive": "true",
                    "Limit": 10,
                    "IncludeItemTypes": "Movie,Series,Episode,Audio,MusicAlbum",
                },
            )
            response.raise_for_status()
            items = response.json().get("Items", [])
        except Exception as exc:
            return ToolResult.error(f"Jellyfin: {exc!r}")
        finally:
            await client.aclose()
        if not items:
            return ToolResult(True, f"nothing in the library for {query!r}")
        lines = [
            f"- {i.get('Name')} ({i.get('Type')}{', ' + str(i.get('ProductionYear')) if i.get('ProductionYear') else ''})"
            for i in items
        ]
        return ToolResult(
            True,
            "\n".join(lines),
            {
                "items": [
                    {"id": i.get("Id"), "name": i.get("Name"), "type": i.get("Type")} for i in items
                ]
            },
        )

    async def jellyfin_now_playing(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        client = jellyfin_client(ctx)
        if client is None:
            return ToolResult.error("Jellyfin is not configured")
        try:
            response = await client.get("/Sessions")
            response.raise_for_status()
            sessions = [s for s in response.json() if s.get("NowPlayingItem")]
        except Exception as exc:
            return ToolResult.error(f"Jellyfin: {exc!r}")
        finally:
            await client.aclose()
        if not sessions:
            return ToolResult(True, "nothing is playing")
        lines = [
            f"- {s.get('UserName', '?')} on {s.get('DeviceName', '?')}: {s['NowPlayingItem'].get('Name')}"
            for s in sessions
        ]
        return ToolResult(True, "\n".join(lines))

    return [
        Tool(
            "qbt_list",
            "List torrents in qBittorrent (filter: all, downloading, completed).",
            _schema({"filter": {"type": "string"}}),
            qbt_list,
        ),
        Tool(
            "qbt_add",
            "Add a magnet or torrent URL to qBittorrent.",
            _schema({"url": {"type": "string"}, "category": {"type": "string"}}, ["url"]),
            qbt_add,
            confirm=True,
        ),
        Tool(
            "jellyfin_search",
            "Search the Jellyfin library.",
            _schema({"query": {"type": "string"}}, ["query"]),
            jellyfin_search,
        ),
        Tool(
            "jellyfin_now_playing",
            "What is playing on Jellyfin right now.",
            _schema({}),
            jellyfin_now_playing,
        ),
    ]
