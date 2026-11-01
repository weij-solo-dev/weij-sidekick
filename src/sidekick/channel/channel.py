"""sidekick.channel.channel — ChannelSession: the registry that connects adapters to the agent

Overview
    `ChannelSession.shared` holds every adapter (`voice`, `telegram`, `wechat`), one inbound
    handler (the agent's `handle`, given to `setup`), and `send()` which routes a reply to the
    channel it names — by default the one the message came from (invariant 14).
Design
    `setup` builds the remote adapters itself from `ConfigChannels` and the credentials: Telegram
    and WeChat each only when enabled and holding a bot token (the pairing callback persists a
    paired chat). Other modules register theirs (interaction its `voice` adapter); `start()`
    passes the session's `dispatch` as their handler so a late-registered adapter still reaches
    the agent. Dispatch is awaited inline: channels are responsible for their own concurrency
    (the voice channel runs one turn at a time by design).
    `setup` runs again before each start of the service and rebuilds the remote adapters it
    built (a stopped adapter's client is closed; the voice adapter stays); `check()` reports
    each one polling — advice, never a reason not to start (block #87).
Depends on
    sidekick.log.

See Also
--------
    AGENTS.md "Architecture" (channel layer), PLAN.md block "[2026-10-26 #12]".

"""

from __future__ import annotations

import collections
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

from sidekick.log import Log

from .schemas import ChannelAdapter, ChannelMessage, ChannelReply, InboundHandler
from .telegram import PairingSaver, TelegramAdapter
from .wechat import WeChatAdapter, WeChatClient, WeChatState

REMOTE = ("telegram", "wechat")  # the adapters `setup` builds from the config


class ChannelSession:
    """Adapter registry and reply router."""

    shared: ClassVar[ChannelSession]

    def __init__(self) -> None:
        self._adapters: dict[str, ChannelAdapter] = {}
        self._handler: InboundHandler | None = None
        self._started: set[str] = set()
        self._built: set[str] = set()  # remote adapters `setup` built from the config
        # The Live page (block #69): when each channel last carried a message, the newest ones.
        self.last_in: dict[str, float] = {}
        self.last_out: dict[str, float] = {}
        self._traffic: collections.deque[dict[str, Any]] = collections.deque(maxlen=100)

    def setup(
        self,
        handler: InboundHandler | None,
        config: Any = None,
        credentials: Mapping[str, Mapping[str, str]] | None = None,
        home: Path | None = None,
        on_telegram_paired: PairingSaver | None = None,
    ) -> None:
        """Set the inbound handler (the agent) and build the remote adapters that can run.

        Called again before each start of the service: the remote adapters are rebuilt from
        the current config (a stopped adapter's HTTP client is closed), the voice adapter that
        `interaction` registers stays.
        """
        self._handler = handler
        keys = credentials or {}
        for name in self._built - self._started:  # the adapters an earlier setup built
            self._adapters.pop(name, None)
        self._built.clear()
        telegram = getattr(config, "telegram", None)
        token = keys.get("telegram", {}).get("bot_token", "")
        if telegram is not None and telegram.enabled and token:
            self.register(
                TelegramAdapter(
                    token,
                    list(telegram.allow_chat_ids),
                    telegram.pairing_code,
                    on_telegram_paired,
                    telegram.poll_timeout_s,
                )
            )
            self._built.add("telegram")
        wechat = getattr(config, "wechat", None)
        token = keys.get("wechat", {}).get("bot_token", "")
        if wechat is not None and wechat.enabled and token and home is not None:
            client = WeChatClient(token, wechat.base_url, wechat.bot_agent)
            state = WeChatState(home / f"wechat_{wechat.bot_id or 'default'}_state.json")
            self.register(WeChatAdapter(client, state, list(wechat.allow_user_ids)))
            self._built.add("wechat")

    def register(self, adapter: ChannelAdapter) -> None:
        """Add an adapter under its name."""
        self._adapters[adapter.name] = adapter
        Log.info(f"channel registered: {adapter.name}")

    def adapters(self) -> list[str]:
        """Registered names."""
        return sorted(self._adapters)

    def get(self, name: str) -> ChannelAdapter | None:
        """An adapter by name."""
        return self._adapters.get(name)

    async def dispatch(self, message: ChannelMessage) -> None:
        """Hand an inbound message to the handler."""
        if self._handler is None:
            Log.warning(f"no inbound handler; dropping message from {message.channel}")
            return
        self._note(message.channel, "in", message.speaker, message.text)
        await self._handler(message)

    def _note(self, channel: str, direction: str, who: str | None, text: str) -> None:
        now = time.time()
        (self.last_in if direction == "in" else self.last_out)[channel] = now
        self._traffic.append(
            {"ts": now, "channel": channel, "direction": direction, "who": who, "text": text[:60]}
        )

    async def send(self, reply: ChannelReply, default_channel: str | None = None) -> bool:
        """Route a reply to `reply.channel` (or the default)."""
        name = reply.channel or default_channel
        adapter = self._adapters.get(name or "")
        if adapter is None:
            Log.warning(f"no channel {name!r} for reply")
            return False
        sent = await adapter.send(reply)
        if sent and name != "voice":
            self._note(str(name), "out", reply.to, reply.text)
        return sent

    def live(self) -> dict[str, Any]:
        """Each adapter's state for the Live page (counters, last traffic, poll alive), memory only."""
        now = time.time()
        out: dict[str, Any] = {}
        for name, adapter in sorted(self._adapters.items()):
            task = getattr(adapter, "_task", None)
            paused = getattr(getattr(adapter, "client", None), "paused_until", 0.0) or 0.0
            polled = getattr(adapter, "last_update_at", None)
            out[name] = {
                "started": name in self._started,
                "alive": None if name == "voice" else bool(task is not None and not task.done()),
                "received": getattr(adapter, "received", None),
                "sent": getattr(adapter, "sent", None),
                "last_in_s": round(now - self.last_in[name]) if name in self.last_in else None,
                "last_out_s": round(now - self.last_out[name]) if name in self.last_out else None,
                "last_poll_s": round(now - polled) if polled else None,
                "error": getattr(adapter, "last_error", None),
                "paused_s": round(paused - now) if paused > now else None,
            }
        return out

    def activity(self, since: float = 0.0, limit: int = 30) -> list[dict[str, Any]]:
        """Messages in and out of the remote channels, newest first."""
        rows = []
        for item in reversed(self._traffic):
            if item["ts"] <= since:
                break
            arrow = "←" if item["direction"] == "in" else "→"
            rows.append(
                {
                    "ts": item["ts"],
                    "module": "channel",
                    "text": f"{item['channel']} {arrow} {item['who'] or ''}: {item['text']}",
                    "level": "info",
                }
            )
        return rows[:limit]

    async def start(self) -> None:
        """Start every adapter."""
        for name, adapter in self._adapters.items():
            if name in self._started:
                continue
            await adapter.start(self.dispatch)
            self._started.add(name)

    def check(self) -> list[dict[str, Any]]:
        """Readiness items: each remote adapter polling without errors (advice, never `bad`)."""
        items: list[dict[str, Any]] = []
        for name in REMOTE:
            adapter = self._adapters.get(name)
            if adapter is None:
                continue
            task = getattr(adapter, "_task", None)
            alive = task is not None and not task.done()
            error = getattr(adapter, "last_error", None)
            items.append(
                {
                    "id": name,
                    "title": name.capitalize() if name != "wechat" else "WeChat",
                    "level": "ok" if alive and not error else "warn",
                    "detail": error or ("polling" if alive else "not polling"),
                }
            )
        if not items:
            items.append(
                {
                    "id": "remote",
                    "title": "remote channels",
                    "level": "off",
                    "detail": "none configured",
                }
            )
        return items

    async def stop(self) -> None:
        """Stop every started adapter."""
        for name in list(self._started):
            adapter = self._adapters.get(name)
            if adapter is not None:
                try:
                    await adapter.stop()
                except Exception as exc:
                    Log.warning(f"channel {name} stop: {exc!r}")
            self._started.discard(name)
