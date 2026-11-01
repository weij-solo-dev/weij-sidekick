"""sidekick.channel.wechat — personal WeChat through Tencent's iLink bot protocol

Overview
    The protocol is the one Tencent's official OpenClaw plugin speaks (PLAN.md block #16): a QR
    login that yields a bot token, a `getupdates` long poll whose opaque `get_updates_buf` must
    be echoed back, and a `sendmessage` call that must carry the per-user `context_token` from
    the last inbound message. `WeChatClient` is the HTTP layer; `WeChatAdapter` is the
    `ChannelAdapter` that runs the poll loop, filters senders by allowlist and delivers replies.
Design
    `httpx.AsyncClient` only. State that must survive restarts (`get_updates_buf`, context tokens
    per user) lives in one JSON file under the home. A stale token (`errcode -14`) pauses the
    account for an hour as the reference plugin does. Only text items and voice transcripts are
    handled; media (AES-ECB over CDN) is a later step. Credentials never reach logs: the token is
    masked.
Depends on
    sidekick.log, httpx.

See Also
--------
    AGENTS.md "channel" yellow page, PLAN.md block "[2026-10-26 #16]".

"""

from __future__ import annotations

import asyncio
import base64
import json
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from sidekick.log import Log, mask_secret

from .schemas import ChannelCapabilities, ChannelMessage, ChannelReply, InboundHandler

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
APP_ID = "bot"
CLIENT_VERSION = (0 << 16) | (1 << 8) | 0  # 0.1.0 encoded as major<<16 | minor<<8 | patch
STALE_TOKEN = -14
PAUSE_S = 3600.0
TEXT, IMAGE, VOICE, FILE, VIDEO = 1, 2, 3, 4, 5
MEDIA_LABELS = {IMAGE: "[圖片]", VOICE: "[語音]", FILE: "[檔案]", VIDEO: "[影片]"}

AllowSaver = Callable[[str], Awaitable[None]]


def _uin() -> str:
    return base64.b64encode(str(secrets.randbits(32)).encode()).decode()


class WeChatClient:
    """iLink HTTP calls."""

    def __init__(
        self,
        token: str | None,
        base_url: str = DEFAULT_BASE_URL,
        bot_agent: str = "sidekick/0.1.0",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.bot_agent = bot_agent
        self.client = client or httpx.AsyncClient(timeout=45.0)
        self.paused_until = 0.0

    def headers(self, with_token: bool = True) -> dict[str, str]:
        """Headers the backend expects."""
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": _uin(),
            "iLink-App-Id": APP_ID,
            "iLink-App-ClientVersion": str(CLIENT_VERSION),
        }
        if with_token and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def base_info(self) -> dict[str, str]:
        """Observability block attached to every body."""
        return {"channel_version": "0.1.0", "bot_agent": self.bot_agent}

    async def post(
        self,
        endpoint: str,
        body: dict[str, Any],
        timeout: float = 15.0,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """POST JSON; raises `httpx.HTTPError` on transport/HTTP failure."""
        url = f"{(base_url or self.base_url).rstrip('/')}/{endpoint}"
        response = await self.client.post(
            url,
            json={**body, "base_info": self.base_info()},
            headers=self.headers(),
            timeout=timeout,
        )
        response.raise_for_status()
        return _parse(response.text)

    async def get(
        self, endpoint: str, timeout: float = 35.0, base_url: str | None = None
    ) -> dict[str, Any]:
        """GET; raises on failure."""
        url = f"{(base_url or self.base_url).rstrip('/')}/{endpoint}"
        response = await self.client.get(
            url, headers=self.headers(with_token=False), timeout=timeout
        )
        response.raise_for_status()
        return _parse(response.text)

    # ------------------------------------------------------------------ login

    async def get_qrcode(
        self, local_tokens: list[str] | None = None, bot_type: str = "3"
    ) -> dict[str, Any]:
        """Start a login: returns `{qrcode, qrcode_img_content}`."""
        return await self.post(
            f"ilink/bot/get_bot_qrcode?bot_type={bot_type}",
            {"local_token_list": local_tokens or []},
            timeout=15.0,
            base_url=DEFAULT_BASE_URL,
        )

    async def qrcode_status(
        self, qrcode: str, verify_code: str | None = None, base_url: str | None = None
    ) -> dict[str, Any]:
        """Long-poll the login status (`wait`, `scaned`, `confirmed`, …)."""
        endpoint = f"ilink/bot/get_qrcode_status?qrcode={httpx.QueryParams({'q': qrcode})['q']}"
        if verify_code:
            endpoint += f"&verify_code={verify_code}"
        try:
            return await self.get(endpoint, timeout=35.0, base_url=base_url or DEFAULT_BASE_URL)
        except httpx.TimeoutException:
            return {"status": "wait"}

    # --------------------------------------------------------------- messages

    async def get_updates(self, buf: str, timeout_s: float = 35.0) -> dict[str, Any]:
        """One long poll; returns the raw response (`ret`, `errcode`, `msgs`, `get_updates_buf`, …)."""
        try:
            return await self.post(
                "ilink/bot/getupdates", {"get_updates_buf": buf}, timeout=timeout_s
            )
        except httpx.TimeoutException:
            return {"ret": 0, "msgs": [], "get_updates_buf": buf}

    async def send_text(
        self, to_user_id: str, text: str, context_token: str | None
    ) -> dict[str, Any]:
        """Send one text message."""
        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": f"sidekick-{uuid.uuid4().hex}",
                "message_type": 2,
                "message_state": 2,
                "item_list": [{"type": TEXT, "text_item": {"text": text}}],
                "context_token": context_token,
            }
        }
        return await self.post("ilink/bot/sendmessage", body, timeout=15.0)

    async def send_typing(self, user_id: str, context_token: str | None) -> None:
        """Best-effort typing indicator."""
        try:
            config = await self.post(
                "ilink/bot/getconfig",
                {"ilink_user_id": user_id, "context_token": context_token},
                timeout=10.0,
            )
            ticket = config.get("typing_ticket")
            if ticket:
                await self.post(
                    "ilink/bot/sendtyping",
                    {"ilink_user_id": user_id, "typing_ticket": ticket, "status": 1},
                    timeout=10.0,
                )
        except Exception as exc:
            Log.debug(f"wechat typing: {exc!r}")

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()


def _parse(raw: str) -> dict[str, Any]:
    """JSON with uint64 ids kept as strings (`parse_int` keeps big ints exact in Python anyway)."""
    value = json.loads(raw) if raw.strip() else {}
    return value if isinstance(value, dict) else {"value": value}


def message_text(message: dict[str, Any]) -> str:
    """Text of an inbound message: text item, voice transcript, or a media label."""
    for item in message.get("item_list") or []:
        kind = item.get("type")
        if kind == TEXT and (item.get("text_item") or {}).get("text") is not None:
            return str(item["text_item"]["text"])
        if kind == VOICE and (item.get("voice_item") or {}).get("text"):
            return str(item["voice_item"]["text"])
        if kind in MEDIA_LABELS:
            return MEDIA_LABELS[kind]
    return ""


class WeChatState:
    """`get_updates_buf` + per-user context tokens persisted as JSON."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.buf = ""
        self.context_tokens: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        """Read the file if present."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.buf = str(data.get("get_updates_buf", ""))
        self.context_tokens = {
            str(k): str(v) for k, v in (data.get("context_tokens") or {}).items()
        }

    def save(self) -> None:
        """Write atomically-enough for a small file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"get_updates_buf": self.buf, "context_tokens": self.context_tokens}),
            encoding="utf-8",
        )


class WeChatAdapter:
    """`ChannelAdapter` for one iLink bot account."""

    name = "wechat"
    capabilities = ChannelCapabilities(text=True, audio=False, images=False, streaming=False)

    def __init__(
        self,
        client: WeChatClient,
        state: WeChatState,
        allow_user_ids: list[str],
        on_allow: AllowSaver | None = None,
    ) -> None:
        self.client = client
        self.state = state
        self.allow = set(allow_user_ids)
        self.on_allow = on_allow
        self.handler: InboundHandler | None = None
        self._task: asyncio.Task[None] | None = None
        self.received = 0
        self.sent = 0
        self.last_update_at: float | None = None
        self.last_error: str | None = None
        self._warned: set[str] = set()
        self.next_timeout_s = 35.0

    async def start(self, handler: InboundHandler) -> None:
        """Begin long polling."""
        self.handler = handler
        Log.info0(
            f"wechat token={mask_secret(self.client.token)} allow={sorted(self.allow)} buf={len(self.state.buf)}B"
        )
        self._task = asyncio.create_task(self._loop(), name="wechat-poll")

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

    async def send(self, reply: ChannelReply) -> bool:
        """Deliver a text reply to a user id (`reply.to` with or without the `wx:` prefix)."""
        user_id = (reply.to or "").removeprefix("wx:")
        if not user_id:
            Log.warning("wechat send: no user id")
            return False
        if time.monotonic() < self.client.paused_until:
            Log.warning("wechat send: account paused (stale token)")
            return False
        try:
            response = await self.client.send_text(
                user_id, reply.text[:4000], self.state.context_tokens.get(user_id)
            )
        except httpx.HTTPError as exc:
            self.last_error = f"send: {type(exc).__name__}"
            Log.warning(f"wechat send: {type(exc).__name__}")
            return False
        if response.get("ret") not in (None, 0):
            self.last_error = f"send ret={response.get('ret')} {response.get('errmsg')}"
            Log.warning(f"wechat send failed: {self.last_error}")
            return False
        self.sent += 1
        return True

    async def _loop(self) -> None:
        failures = 0
        while True:
            if time.monotonic() < self.client.paused_until:
                await asyncio.sleep(min(60.0, self.client.paused_until - time.monotonic()))
                continue
            try:
                ok = await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                ok = False
                self.last_error = repr(exc)
                Log.error(f"wechat poll: {exc!r}")
            if not ok:
                failures += 1
                await asyncio.sleep(30.0 if failures >= 3 else 2.0)
                continue
            failures = 0

    async def poll_once(self) -> bool:
        """One getupdates round; dispatches messages. False on API failure."""
        try:
            response = await self.client.get_updates(self.state.buf, self.next_timeout_s)
        except httpx.HTTPError as exc:
            self.last_error = f"getupdates: {type(exc).__name__}"
            Log.warning(f"wechat getupdates: {type(exc).__name__}")
            return False
        ret = response.get("ret", 0) or 0
        errcode = response.get("errcode", 0) or 0
        if ret != 0 or errcode != 0:
            if STALE_TOKEN in (ret, errcode):
                self.client.paused_until = time.monotonic() + PAUSE_S
                self.last_error = (
                    "stale token; paused for an hour (log in again on the dashboard's Channel page)"
                )
                Log.error("wechat: bot token is stale; pausing for an hour")
                return True
            self.last_error = f"getupdates ret={ret} errcode={errcode} {response.get('errmsg')}"
            Log.warning(f"wechat getupdates failed: {self.last_error}")
            return False
        self.last_error = None
        suggested = response.get("longpolling_timeout_ms")
        if isinstance(suggested, int | float) and suggested > 0:
            self.next_timeout_s = max(5.0, min(60.0, suggested / 1000.0))
        new_buf = response.get("get_updates_buf")
        if isinstance(new_buf, str) and new_buf:
            self.state.buf = new_buf
            self.state.save()
        for message in response.get("msgs") or []:
            try:
                await self.handle_message(message)
            except Exception as exc:
                Log.error(f"wechat message: {exc!r}")
        return True

    async def handle_message(self, message: dict[str, Any]) -> None:
        """Route one inbound message."""
        if message.get("message_type") == 2:
            return  # our own
        user_id = str(message.get("from_user_id") or "")
        text = message_text(message).strip()
        if not user_id or not text:
            return
        token = message.get("context_token")
        if isinstance(token, str) and token:
            self.state.context_tokens[user_id] = token
            self.state.save()
        self.last_update_at = time.time()
        if user_id not in self.allow:
            if user_id not in self._warned:
                self._warned.add(user_id)
                Log.info(f"wechat: message from unlisted user {mask_secret(user_id)}")
                await self.send(
                    ChannelReply(
                        "這個微信未同 Bobby 配對。請聯絡喺 dashboard 掃碼登入嘅佈置者。",
                        to=user_id,
                    )
                )
            return
        self.received += 1
        inbound = ChannelMessage(
            "wechat",
            f"wx:{user_id}",
            text,
            id=f"wx-{message.get('message_id') or uuid.uuid4().hex}",
            ts=float(message.get("create_time_ms") or time.time() * 1000) / 1000.0,
            metadata={
                "session_id": message.get("session_id"),
                "message_id": message.get("message_id"),
                "private": True,  # iLink bot chats are one-to-one: they stay with their person
            },
        )
        await self.client.send_typing(user_id, token if isinstance(token, str) else None)
        if self.handler is not None:
            await self.handler(inbound)


class WeChatLogin:
    """QR login state machine (the dashboard's Channel page)."""

    def __init__(self, client: WeChatClient) -> None:
        self.client = client
        self.qrcode: str | None = None
        self.qrcode_url: str | None = None
        self.status = "idle"
        self.base_url = DEFAULT_BASE_URL
        self.verify_code: str | None = None
        self.result: dict[str, Any] | None = None
        self.started_at = 0.0
        self.refreshes = 0

    async def start(self, local_tokens: list[str] | None = None) -> str:
        """Fetch a QR code; returns the URL to encode."""
        response = await self.client.get_qrcode(local_tokens)
        self.qrcode = str(response.get("qrcode", ""))
        self.qrcode_url = str(response.get("qrcode_img_content", ""))
        self.status = "wait"
        self.started_at = time.monotonic()
        self.base_url = DEFAULT_BASE_URL
        Log.info("wechat login: QR code obtained")
        return self.qrcode_url

    async def poll(self) -> str:
        """One status poll; returns the status. `confirmed` fills `result`."""
        if not self.qrcode:
            raise RuntimeError("login not started")
        response = await self.client.qrcode_status(self.qrcode, self.verify_code, self.base_url)
        status = str(response.get("status", "wait"))
        self.status = status
        if status == "scaned" and self.verify_code:
            self.verify_code = None
        elif status == "scaned_but_redirect" and response.get("redirect_host"):
            self.base_url = f"https://{response['redirect_host']}"
        elif status == "expired":
            self.refreshes += 1
            if self.refreshes <= 3:
                await self.start()
                self.status = "wait"
        elif status == "confirmed":
            self.result = {
                "bot_token": response.get("bot_token"),
                "bot_id": response.get("ilink_bot_id"),
                "base_url": response.get("baseurl") or self.base_url,
                "user_id": response.get("ilink_user_id"),
            }
            Log.info(
                f"wechat login confirmed: bot={self.result['bot_id']} user={mask_secret(self.result['user_id'])}"
            )
        return self.status
