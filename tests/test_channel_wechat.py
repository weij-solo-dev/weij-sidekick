"""WeChat iLink client, adapter and login over a mocked backend."""

from __future__ import annotations

import json
import time

import httpx

from sidekick.channel import (
    ChannelReply,
    WeChatAdapter,
    WeChatClient,
    WeChatLogin,
    WeChatState,
    message_text,
)


class FakeILink:
    def __init__(self):
        self.requests = []
        self.updates = []
        self.sent = []
        self.statuses = ["wait", "scaned", "confirmed"]
        self.stale = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content or b"{}") if request.content else {}
        self.requests.append(
            (request.method, path, dict(request.url.params), body, dict(request.headers))
        )
        if path.endswith("/get_bot_qrcode"):
            return httpx.Response(
                200, json={"qrcode": "QR123", "qrcode_img_content": "https://weixin.qq.com/q/abc"}
            )
        if path.endswith("/get_qrcode_status"):
            status = self.statuses.pop(0) if self.statuses else "wait"
            payload = {"status": status}
            if status == "confirmed":
                payload.update(
                    {
                        "bot_token": "BOT-TOKEN-XYZ",
                        "ilink_bot_id": "bot123@im.bot",
                        "baseurl": "https://ilink-sh.weixin.qq.com",
                        "ilink_user_id": "user777",
                    }
                )
            return httpx.Response(200, json=payload)
        if path.endswith("/getupdates"):
            if self.stale:
                return httpx.Response(
                    200, json={"ret": -14, "errcode": -14, "errmsg": "session timeout"}
                )
            msgs, self.updates = self.updates, []
            return httpx.Response(
                200,
                json={
                    "ret": 0,
                    "msgs": msgs,
                    "get_updates_buf": f"buf-{len(self.requests)}",
                    "longpolling_timeout_ms": 20000,
                },
            )
        if path.endswith("/sendmessage"):
            self.sent.append(body)
            return httpx.Response(200, json={"ret": 0, "message_id": 123456789012345678901})
        if path.endswith("/getconfig"):
            return httpx.Response(200, json={"typing_ticket": "T1"})
        if path.endswith("/sendtyping"):
            return httpx.Response(200, json={"ret": 0})
        return httpx.Response(404, text="nope")


def inbound(user, text, token="ctx-1", kind=1):
    item = (
        {"type": kind, "text_item": {"text": text}}
        if kind == 1
        else {"type": 3, "voice_item": {"text": text, "encode_type": 6}}
    )
    return {
        "from_user_id": user,
        "to_user_id": "bot123@im.bot",
        "message_type": 1,
        "message_id": "987654321098765432",
        "create_time_ms": 1700000000000,
        "item_list": [item],
        "context_token": token,
    }


def test_message_text_and_headers():
    assert message_text(inbound("u", "你好")) == "你好"
    assert message_text(inbound("u", "語音轉文字", kind=3)) == "語音轉文字"
    assert message_text({"item_list": [{"type": 2, "image_item": {}}]}) == "[圖片]"
    client = WeChatClient("tok", bot_agent="sidekick/0.1.0")
    headers = client.headers()
    assert (
        headers["Authorization"] == "Bearer tok"
        and headers["AuthorizationType"] == "ilink_bot_token"
    )
    assert headers["iLink-App-Id"] == "bot" and headers["iLink-App-ClientVersion"] == str(1 << 8)
    assert headers["X-WECHAT-UIN"]


async def test_login_flow(tmp_path):
    fake = FakeILink()
    client = WeChatClient(
        None, client=httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    )
    flow = WeChatLogin(client)
    url = await flow.start()
    assert url == "https://weixin.qq.com/q/abc" and flow.status == "wait"
    assert (
        fake.requests[0][2] == {"bot_type": "3"} and fake.requests[0][3]["local_token_list"] == []
    )
    assert await flow.poll() == "wait"
    assert await flow.poll() == "scaned"
    assert await flow.poll() == "confirmed"
    assert flow.result == {
        "bot_token": "BOT-TOKEN-XYZ",
        "bot_id": "bot123@im.bot",
        "base_url": "https://ilink-sh.weixin.qq.com",
        "user_id": "user777",
    }
    assert fake.requests[-1][2]["qrcode"] == "QR123"
    await client.aclose()


async def test_adapter_poll_send_and_stale_token(tmp_path):
    fake = FakeILink()
    client = WeChatClient(
        "BOT-TOKEN-XYZ",
        "https://ilink-sh.weixin.qq.com",
        client=httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)),
    )
    state = WeChatState(tmp_path / "wechat_state.json")
    adapter = WeChatAdapter(client, state, ["user777"])
    received = []

    async def handler(msg):
        received.append(msg)

    adapter.handler = handler
    fake.updates = [
        inbound("user777", "Bobby 你好"),
        inbound("stranger", "hi", token="ctx-s"),
        {
            "from_user_id": "user777",
            "message_type": 2,
            "item_list": [{"type": 1, "text_item": {"text": "echo of ours"}}],
        },
    ]
    assert await adapter.poll_once()
    assert (
        len(received) == 1
        and received[0].channel == "wechat"
        and received[0].speaker == "wx:user777"
        and received[0].text == "Bobby 你好"
    )
    assert state.buf.startswith("buf-") and state.context_tokens["user777"] == "ctx-1"
    assert (
        json.loads((tmp_path / "wechat_state.json").read_text())["context_tokens"]["user777"]
        == "ctx-1"
    )
    assert adapter.next_timeout_s == 20.0
    # stranger got one notice, with its own context token
    notices = [s for s in fake.sent if s["msg"]["to_user_id"] == "stranger"]
    assert len(notices) == 1 and notices[0]["msg"]["context_token"] == "ctx-s"
    # getupdates body echoes the buf and carries base_info; headers carry the token
    gu = [r for r in fake.requests if r[1].endswith("/getupdates")][-1]
    assert (
        gu[3]["get_updates_buf"] == ""
        and gu[3]["base_info"]["bot_agent"] == "sidekick/0.1.0"
        and gu[4]["authorization"] == "Bearer BOT-TOKEN-XYZ"
    )
    # reply to the user echoes the stored context token
    assert await adapter.send(ChannelReply("你好呀", to="wx:user777"))
    sent = fake.sent[-1]["msg"]
    assert (
        sent["to_user_id"] == "user777"
        and sent["context_token"] == "ctx-1"
        and sent["message_type"] == 2
        and sent["item_list"][0]["text_item"]["text"] == "你好呀"
    )
    # second poll sends the saved buf
    assert await adapter.poll_once()
    gu = [r for r in fake.requests if r[1].endswith("/getupdates")][-1]
    assert gu[3]["get_updates_buf"].startswith("buf-")
    # stale token pauses the account for an hour; send refuses meanwhile
    fake.stale = True
    assert await adapter.poll_once() is True
    assert client.paused_until > time.monotonic() + 3000 and "stale" in adapter.last_error
    assert not await adapter.send(ChannelReply("x", to="wx:user777"))
    await client.aclose()
