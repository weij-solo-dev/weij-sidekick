"""extensions.news.watchers — periodic feed fetching with a small on-disk cache

Overview
    `WATCHERS(ctx)` returns the `feeds` watcher: every `interval_minutes` it fetches the
    configured sources, stores items in `news.json` under the extension's state directory, and
    emits `feed.update` events with the number of new items per source (severity notice when
    there is something new) so automations such as a morning briefing can react.
Design
    Items are keyed by link; the cache keeps the newest 300. The watcher shares its cache with
    `tools.py` through the state directory so tools never fetch during a turn unless asked.
Depends on
    sidekick.log, sidekick.perception, sidekick.extension, httpx.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from sidekick.extension import ExtensionContext
from sidekick.log import Log
from sidekick.perception import PerceptionEvent, Severity, Watcher

from .feeds import FeedItem, fetch_source  # type: ignore[import-not-found]

CACHE_NAME = "news.json"
MAX_ITEMS = 300


def load_cache(state_dir: Path) -> list[dict[str, Any]]:
    """Cached items, newest first."""
    try:
        data = json.loads((state_dir / CACHE_NAME).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_cache(state_dir: Path, items: list[dict[str, Any]]) -> None:
    """Persist items."""
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / CACHE_NAME).write_text(
        json.dumps(items[:MAX_ITEMS], ensure_ascii=False), encoding="utf-8"
    )


def item_dict(item: FeedItem, fetched_ts: float) -> dict[str, Any]:
    """Serialisable form."""
    return {
        "source": item.source,
        "title": item.title,
        "link": item.link,
        "published_ts": item.published_ts,
        "summary": item.summary,
        "author": item.author,
        "fetched_ts": fetched_ts,
        "extra": item.extra,
    }


class FeedWatcher(Watcher):
    """Fetch all sources on an interval."""

    name = "feeds"

    def __init__(self, ctx: ExtensionContext) -> None:
        super().__init__(float(ctx.setting("interval_minutes", 30) or 30) * 60.0)
        self.ctx = ctx
        self.first = True

    async def poll(self) -> list[PerceptionEvent]:
        """Fetch and diff."""
        sources = list(self.ctx.setting("sources", []) or [])
        if not sources:
            return []
        cached = load_cache(self.ctx.state_dir)
        known = {item["link"] for item in cached}
        fetched_ts = time.time()
        new_items: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        async with httpx.AsyncClient(timeout=20.0) as client:
            for url in sources:
                try:
                    items = await fetch_source(
                        url, client, int(self.ctx.setting("hn_min_score", 100) or 100)
                    )
                except Exception as exc:
                    Log.warning(f"news: {url}: {exc!r}")
                    continue
                fresh = [item_dict(i, fetched_ts) for i in items if i.link not in known]
                counts[items[0].source if items else url] = len(fresh)
                new_items.extend(fresh)
        if new_items:
            merged = sorted(
                new_items + cached,
                key=lambda i: -(i.get("published_ts") or i.get("fetched_ts") or 0),
            )
            save_cache(self.ctx.state_dir, merged)
        total = len(new_items)
        if total == 0 and not self.first:
            return []
        self.first = False
        return [
            PerceptionEvent(
                "feed.update",
                Severity.NOTICE if total else Severity.DEBUG,
                {"new": total, "per_source": counts},
                source="extension:news",
            )
        ]


def WATCHERS(ctx: ExtensionContext) -> list[Watcher]:
    """The feed watcher."""
    return [FeedWatcher(ctx)]
