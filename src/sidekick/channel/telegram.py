"""sidekick.channel.telegram — Telegram bot over the raw Bot API with long polling and pairing

Overview
    One bot, a few paired chats. The adapter long-polls `getUpdates`, delivers text messages from
    allow-listed chats to the inbound handler as `ChannelMessage(channel="telegram",
    speaker="tg:<chat id>")`, and sends replies with `sendMessage`. Pairing: the dashboard's
    Channel page stores a one-time code; the owner sends `/pair <code>` from their chat and that chat id
    is added to the allowlist (the first paired chat becomes the owner's remote channel).
Design
    `httpx.AsyncClient` only, no bot framework (AGENTS.md "Conventions"). The update offset is
    kept in memory and advanced after each batch; a restart may redeliver the last update, which
    the agent tolerates. Unknown chats get one "not paired" reply per process and are then
    ignored. Failures back off (2 s, then 30 s after three in a row). Allowlist changes are saved
    through a callback so `config.json` stays the single source of truth.
Depends on
    sidekick.log, httpx.

See Also
--------
    AGENTS.md "channel" yellow page, PLAN.md block "[2026-10-26 #16]".

"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from sidekick.log import Log, mask_secret

from .schemas import ChannelCapabilities, ChannelMessage, ChannelReply, InboundHandler

API = "https://api.telegram.org"
PairingSaver = Callable[[str, bool], Awaitable[None]]


class TelegramAdapter:
    """`ChannelAdapter` for a Telegram bot."""

    name = "telegram"
    capabilities = ChannelCapabilities(text=True, audio=False, images=False, streaming=False)

    def __init__(
        self,
        token: str,
        allow_chat_ids: list[str],
        pairing_code: str | None = None,
        on_paired: PairingSaver | None = None,
        poll_timeout_s: int = 30,
        client: httpx.AsyncClient | None = None,
        base_url: str = API,
    ) -> None:
        self.token = token
        self.allow = set(allow_chat_ids)
        self.pairing_code = pairing_code
        self.on_paired = on_paired
        self.poll_timeout_s = poll_timeout_s
        self.client = client or httpx.AsyncClient(timeout=poll_timeout_s + 10)
        self.base = f"{base_url}/bot{token}"
        self.handler: InboundHandler | None = None
        self._task: asyncio.Task[None] | None = None
        self.offset: int | None = None
        self.last_update_at: float | None = None
        self.last_error: str | None = None
        self.received = 0
        self.sent = 0
        self._warned: set[str] = set()
        self.me: dict[str, Any] | None = None

    # ----------------------------------------------------------------- api

    async def call(self, method: str, **params: Any) -> Any | None:
        """One Bot API call (dict or list result); None on failure (never raises)."""
        try:
            response = await self.client.post(f"{self.base}/{method}", json=params)
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            self.last_error = f"{method}: {type(exc).__name__}"
            Log.warning(f"telegram {method}: {type(exc).__name__}")
            return None
        if not payload.get("ok"):
            self.last_error = f"{method}: {payload.get('description')}"
            Log.warning(f"telegram {method} failed: {payload.get('description')}")
            return None
        self.last_error = None
        result = payload.get("result")
        return result if isinstance(result, dict | list) else {"result": result}

    async def get_me(self) -> dict[str, Any] | None:
        """Bot identity (also a token check)."""
        result = await self.call("getMe")
        if isinstance(result, dict):
            self.me = result
        return self.me

    async def send(self, reply: ChannelReply) -> bool:
        """Deliver a text reply to a chat id (`reply.to` with or without the `tg:` prefix)."""
        chat_id = (reply.to or "").removeprefix("tg:")
        if not chat_id:
            Log.warning("telegram send: no chat id")
            return False
        result = await self.call("sendMessage", chat_id=chat_id, text=reply.text[:4000])
        if result is not None:
            self.sent += 1
        return result is not None

    async def typing(self, chat_id: str) -> None:
        """Typing indicator."""
        await self.call("sendChatAction", chat_id=chat_id.removeprefix("tg:"), action="typing")

    # ------------------------------------------------------------------ loop

    async def start(self, handler: InboundHandler) -> None:
        """Begin long polling."""
        self.handler = handler
        Log.info0(f"telegram token={mask_secret(self.token)} allow={sorted(self.allow)}")
        await self.get_me()
        self._task = asyncio.create_task(self._loop(), name="telegram-poll")

    async def stop(self) -> None:
        """Stop polling."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        await self.client.aclose()

    async def _loop(self) -> None:
        failures = 0
        while True:
            try:
                updates = await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                updates = None
                self.last_error = repr(exc)
                Log.error(f"telegram poll: {exc!r}")
            if updates is None:
                failures += 1
                await asyncio.sleep(30.0 if failures >= 3 else 2.0)
                continue
            failures = 0

    async def poll_once(self) -> list[dict[str, Any]] | None:
        """One `getUpdates` round; dispatches each update. None on API failure."""
        params: dict[str, Any] = {"timeout": self.poll_timeout_s, "allowed_updates": ["message"]}
        if self.offset is not None:
            params["offset"] = self.offset
        result = await self.call("getUpdates", **params)
        if result is None:
            return None
        updates: list[dict[str, Any]] = (
            [u for u in result if isinstance(u, dict)] if isinstance(result, list) else []
        )
        for update in updates:
            self.offset = int(update.get("update_id", 0)) + 1
            try:
                await self.handle_update(update)
            except Exception as exc:
                Log.error(f"telegram update: {exc!r}")
        return updates

    async def handle_update(self, update: dict[str, Any]) -> None:
        """Route one update."""
        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = str(message.get("text") or message.get("caption") or "").strip()
        if not chat_id or not text:
            return
        self.last_update_at = time.time()
        if text.startswith("/pair"):
            await self._pair(chat_id, text, chat)
            return
        if chat_id not in self.allow:
            if chat_id not in self._warned:
                self._warned.add(chat_id)
                Log.info(f"telegram: message from unpaired chat {chat_id}")
                await self.send(
                    ChannelReply(
                        "This chat is not paired with Bobby. Make a pairing code on the dashboard "
                        "(Channel) and send /pair <code> here.",
                        to=chat_id,
                    )
                )
            return
        if text in ("/start", "/help"):
            await self.send(ChannelReply("Paired. Just talk to me.", to=chat_id))
            return
        self.received += 1
        sender = message.get("from") or {}
        inbound = ChannelMessage(
            "telegram",
            f"tg:{chat_id}",
            text,
            id=f"tg-{update.get('update_id')}",
            ts=float(message.get("date") or time.time()),
            metadata={
                "chat_type": chat.get("type"),
                "private": chat.get("type") == "private",  # a DM stays with its person (#70)
                "username": sender.get("username"),
                "first_name": sender.get("first_name"),
                "message_id": message.get("message_id"),
            },
        )
        await self.typing(chat_id)
        if self.handler is not None:
            await self.handler(inbound)

    async def _pair(self, chat_id: str, text: str, chat: dict[str, Any]) -> None:
        code = text.split(maxsplit=1)[1].strip() if " " in text else ""
        if not self.pairing_code or code != self.pairing_code:
            Log.info(f"telegram: bad pairing attempt from {chat_id}")
            await self.send(ChannelReply("Wrong or missing code.", to=chat_id))
            return
        first = not self.allow
        self.allow.add(chat_id)
        self.pairing_code = None
        Log.info(f"telegram: paired chat {chat_id} ({chat.get('type')})")
        if self.on_paired is not None:
            await self.on_paired(chat_id, first)
        await self.send(ChannelReply("Paired with Bobby. You can talk to me here now.", to=chat_id))
