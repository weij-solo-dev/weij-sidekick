"""extensions.media.watchers — download-completion events from qBittorrent

Overview
    Polls `torrents/info` and emits `media.download_done` (notice) when a torrent reaches 100 %,
    remembering completed hashes in the extension state so each completion fires once.
Design
    Skips silently when qBittorrent is not configured; login per poll keeps it stateless.
Depends on
    sidekick.log, sidekick.perception, sidekick.extension, httpx.
"""

from __future__ import annotations

import json
from typing import Any

from sidekick.extension import ExtensionContext
from sidekick.log import Log
from sidekick.perception import PerceptionEvent, Severity, Watcher

from .tools import qbt_client  # type: ignore[import-not-found]


class DownloadWatcher(Watcher):
    """Completion events."""

    name = "downloads"

    def __init__(self, ctx: ExtensionContext) -> None:
        super().__init__(float(ctx.setting("poll_minutes", 2) or 2) * 60.0)
        self.ctx = ctx
        self._seen_path = ctx.state_dir / "completed.json"
        try:
            self.seen: set[str] = set(json.loads(self._seen_path.read_text()))
        except (OSError, ValueError):
            self.seen = set()
        self.primed = False

    async def poll(self) -> list[PerceptionEvent]:
        """Diff completed torrents."""
        if not self.ctx.setting("qbittorrent_url", ""):
            return []
        try:
            client = await qbt_client(self.ctx)
        except Exception as exc:
            Log.debug(f"media watcher: {exc!r}")
            return []
        if client is None:
            return []
        try:
            response = await client.get("/api/v2/torrents/info", params={"filter": "completed"})
            response.raise_for_status()
            torrents: list[dict[str, Any]] = response.json()
        finally:
            await client.aclose()
        events: list[PerceptionEvent] = []
        for torrent in torrents:
            key = str(torrent.get("hash") or torrent.get("name"))
            if key in self.seen:
                continue
            self.seen.add(key)
            if self.primed:
                events.append(
                    PerceptionEvent(
                        "media.download_done",
                        Severity.NOTICE,
                        {"name": torrent.get("name"), "size": torrent.get("size")},
                        source="extension:media",
                    )
                )
        self.primed = True
        self.ctx.state_dir.mkdir(parents=True, exist_ok=True)
        self._seen_path.write_text(json.dumps(sorted(self.seen)))
        return events


def WATCHERS(ctx: ExtensionContext) -> list[Watcher]:
    """The download watcher."""
    return [DownloadWatcher(ctx)]
