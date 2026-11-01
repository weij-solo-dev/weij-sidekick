"""extensions.news.tools — news_latest, news_search and news_sources for the news subagent

Overview
    Tools read the watcher's cache (`news.json`) and fall back to a live fetch when the cache is
    empty or stale, so a briefing works right after enabling the extension.
Design
    Results are compact text lines (`source · age · title — summary`) sized for a prompt; URLs
    are kept in the result data, never in the spoken text.
Depends on
    sidekick.agent, sidekick.extension, httpx.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from sidekick.agent import Tool, ToolContext, ToolResult
from sidekick.extension import ExtensionContext

from .feeds import fetch_source, source_name  # type: ignore[import-not-found]
from .watchers import item_dict, load_cache, save_cache  # type: ignore[import-not-found]


def _age(ts: float | None) -> str:
    if not ts:
        return "?"
    hours = (time.time() - ts) / 3600.0
    return (
        f"{hours * 60:.0f}m"
        if hours < 1
        else f"{hours:.0f}h"
        if hours < 48
        else f"{hours / 24:.0f}d"
    )


def _lines(items: list[dict[str, Any]], limit: int) -> str:
    out = []
    for item in items[:limit]:
        summary = (item.get("summary") or "")[:140]
        out.append(
            f"- [{item['source']} · {_age(item.get('published_ts') or item.get('fetched_ts'))}] {item['title']}"
            + (f" — {summary}" if summary else "")
        )
    return "\n".join(out) if out else "no items"


async def _refresh(ctx: ExtensionContext) -> list[dict[str, Any]]:
    cached = load_cache(ctx.state_dir)
    newest = max((i.get("fetched_ts") or 0 for i in cached), default=0)
    if cached and time.time() - newest < 3600:
        return cached
    fetched_ts = time.time()
    known = {i["link"] for i in cached}
    fresh: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        for url in ctx.setting("sources", []) or []:
            try:
                items = await fetch_source(
                    url, client, int(ctx.setting("hn_min_score", 100) or 100)
                )
            except Exception:
                continue
            fresh.extend(item_dict(i, fetched_ts) for i in items if i.link not in known)
    merged = sorted(
        fresh + cached, key=lambda i: -(i.get("published_ts") or i.get("fetched_ts") or 0)
    )
    if fresh:
        save_cache(ctx.state_dir, merged)
    return merged


def TOOLS(ctx: ExtensionContext) -> list[Tool]:
    """Build the news tools."""

    async def news_latest(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        items = await _refresh(ctx)
        source = str(arguments.get("source", "")).strip().lower()
        if source:
            items = [i for i in items if source in i["source"].lower()]
        limit = int(arguments.get("limit", 8) or 8)
        return ToolResult(True, _lines(items, limit), {"items": items[:limit]})

    async def news_search(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        query = str(arguments.get("query", "")).strip().lower()
        if not query:
            return ToolResult.error("query is required")
        items = [
            i
            for i in await _refresh(ctx)
            if query in (i["title"] + " " + (i.get("summary") or "")).lower()
        ]
        return ToolResult(True, _lines(items, 8), {"items": items[:8]})

    async def news_sources(arguments: dict[str, Any], tctx: ToolContext) -> ToolResult:
        sources = ctx.setting("sources", []) or []
        return ToolResult(
            True, "\n".join(f"- {source_name(u)}: {u}" for u in sources) or "no sources configured"
        )

    return [
        Tool(
            "news_latest",
            "Latest news items across the configured feeds (optionally filtered by source name).",
            {
                "type": "object",
                "properties": {"source": {"type": "string"}, "limit": {"type": "integer"}},
            },
            news_latest,
        ),
        Tool(
            "news_search",
            "Search cached news items by keyword.",
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            news_search,
        ),
        Tool(
            "news_sources",
            "List the configured news sources.",
            {"type": "object", "properties": {}},
            news_sources,
        ),
    ]
