"""Telegram adapter over a mocked Bot API: pairing, allowlist, inbound → handler, send."""

from __future__ import annotations

import json

import httpx

from sidekick.channel import ChannelReply, TelegramAdapter


class FakeBotApi:
    def __init__(self):
        self.updates = []
        self.sent = []
        self.actions = []
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content or b"{}")
        self.calls.append((method, body))
        if method == "getMe":
            return httpx.Response(
                200, json={"ok": True, "result": {"id": 1, "username": "banana_bot"}}
            )
        if method == "getUpdates":
            offset = body.get("offset", 0)
            pending = [u for u in self.updates if u["update_id"] >= offset]
            return httpx.Response(200, json={"ok": True, "result": pending})
        if method == "sendMessage":
            self.sent.append(body)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": len(self.sent)}})
        if method == "sendChatAction":
            self.actions.append(body)
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(200, json={"ok": False, "description": "unknown method"})


def message(update_id, chat_id, text, chat_type="private"):
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": chat_type},
            "from": {"username": "weij", "first_name": "W"},
            "text": text,
        },
    }


async def test_pairing_allowlist_and_dispatch():
    api = FakeBotApi()
    client = httpx.AsyncClient(transport=httpx.MockTransport(api.handler))
    paired = []

    async def on_paired(chat_id, first):
        paired.append((chat_id, first))

    adapter = TelegramAdapter(
        "123:TOKEN",
        [],
        pairing_code="424242",
        on_paired=on_paired,
        client=client,
        base_url="https://tg.test",
    )
    inbound = []

    async def handler(msg):
        inbound.append(msg)

    adapter.handler = handler
    assert (await adapter.get_me())["username"] == "banana_bot"
    # unpaired chat: warned once, never dispatched
    api.updates = [message(1, 42, "你好")]
    await adapter.poll_once()
    assert inbound == [] and len(api.sent) == 1 and "not paired" in api.sent[0]["text"]
    api.updates = [message(2, 42, "再講一次")]
    await adapter.poll_once()
    assert len(api.sent) == 1  # no second warning
    # wrong code, then right code
    api.updates = [message(3, 42, "/pair 000000")]
    await adapter.poll_once()
    assert "Wrong" in api.sent[-1]["text"] and paired == []
    api.updates = [message(4, 42, "/pair 424242")]
    await adapter.poll_once()
    assert paired == [("42", True)] and "42" in adapter.allow and adapter.pairing_code is None
    # paired chat → handler, typing action, reply via send()
    api.updates = [message(5, 42, "今日天氣點呀")]
    await adapter.poll_once()
    assert len(inbound) == 1 and inbound[0].channel == "telegram" and inbound[0].speaker == "tg:42"
    assert inbound[0].text == "今日天氣點呀" and inbound[0].metadata["username"] == "weij"
    assert api.actions and api.actions[-1]["action"] == "typing"
    assert adapter.offset == 6
    assert await adapter.send(ChannelReply("好天呀", to="tg:42"))
    assert api.sent[-1] == {"chat_id": "42", "text": "好天呀"}
    assert not await adapter.send(ChannelReply("x", to=""))
    # API failure path returns None without raising
    api.updates = None
    assert await adapter.call("nope") is None and adapter.last_error
    await client.aclose()
