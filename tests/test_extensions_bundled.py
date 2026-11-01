"""Bundled extensions: robot tools on the null body, news feed parsers, media/home tools over mocked HTTP."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import numpy as np

from sidekick.agent import ToolContext
from sidekick.body import BodyNullBackend, BodySession
from sidekick.channel import ChannelMessage
from sidekick.extension import ExtensionContext, load_factory
from sidekick.perception import PerceptionSession

ROOT = Path(__file__).resolve().parent.parent / "extensions"
TCTX = ToolContext(ChannelMessage("voice", "dad", "x"), "main")


def tools_of(name: str, ctx: ExtensionContext) -> dict:
    return {t.name: t for t in load_factory(ROOT / name, "tools.py", name, "TOOLS")(ctx)}


async def test_robot_tools_on_null_body(tmp_path):
    backend = BodyNullBackend()
    body = BodySession(backend, poll_hz=20.0)
    body.connect()
    perception = PerceptionSession()
    perception.setup(body, tmp_path / "events.db")
    ctx = ExtensionContext(
        "robot", {"describe_with_vision": False}, tmp_path, body=body, perception=perception
    )
    tools = tools_of("robot", ctx)
    try:
        assert set(tools) >= {
            "express",
            "look_at",
            "look",
            "who_is_here",
            "privacy_mode",
            "enroll_voice",
            "set_volume",
        }
        assert tools["privacy_mode"].confirm
        assert (await tools["express"].handler({"name": "nod"}, TCTX)).ok
        result = await tools["look_at"].handler({"direction": "left"}, TCTX)
        assert result.ok and "left" in result.content
        assert not (await tools["look_at"].handler({"direction": "sideways"}, TCTX)).ok
        assert not (await tools["look"].handler({}, TCTX)).ok  # no frame
        backend.set_frame(np.full((120, 160, 3), 200, np.uint8))
        result = await tools["look"].handler({}, TCTX)
        assert result.ok and "160x120" in result.content and "well lit" in result.content
        result = await tools["who_is_here"].handler({}, TCTX)
        assert result.ok and "don't see anyone" in result.content
        assert not (
            await tools["set_volume"].handler({"volume": 50}, TCTX)
        ).ok  # null body has no volume
    finally:
        body.close()


async def test_look_in_the_dark_lifts_the_frame_and_asks_the_question(tmp_path):
    """Block #89: a 26/255 frame of a child holding a card came back as "a person sleeping"."""
    from sidekick.llm import LLMResult

    backend = BodyNullBackend()
    body = BodySession(backend, poll_hz=20.0)
    body.connect()

    class Vision:
        def __init__(self) -> None:
            self.calls: list = []

        def is_ready(self, slot: str) -> bool:
            return True

        async def infer(self, slot, messages, options, task=""):
            self.calls.append(messages[0].content)
            return LLMResult(True, "A child holds up a card.", "fake", "api", "model", "****")

    llm = Vision()
    ctx = ExtensionContext("robot", {}, tmp_path, body=body, llm=llm, spec=object(), vision=True)
    tools = tools_of("robot", ctx)
    try:
        assert "question" in tools["look"].parameters["properties"]
        backend.set_frame(np.full((120, 160, 3), 26, np.uint8))
        result = await tools["look"].handler({"question": "What is on the card?"}, TCTX)
        assert (
            result.ok and "dark" in result.content and "A child holds up a card." in result.content
        )
        text, image = llm.calls[0]
        assert text["text"].startswith("What is on the card?")
        assert "say plainly when you cannot" in text["text"]
        import base64

        import cv2

        jpeg = base64.b64decode(image["image_url"]["url"].split(",", 1)[1])
        sent = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        assert sent.mean() > 80  # gamma-lifted before the model saw it
    finally:
        body.close()


def test_news_feed_parsers():
    import sys

    sys.path.insert(0, str(ROOT / "news"))
    from sidekick.extension import import_file

    feeds = import_file(ROOT / "news", "feeds.py", "news")
    rss = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
    <item><title>First &amp; best</title><link>https://a.example/1</link><pubDate>Mon, 26 Oct 2026 08:00:00 +0800</pubDate><description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description></item>
    <item><title>No link</title></item></channel></rss>"""
    items = feeds.parse_feed(rss, "a.example")
    assert (
        len(items) == 1
        and items[0].title == "First & best"
        and items[0].summary == "Hello world"
        and items[0].published_ts
    )
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom one</title><link rel="alternate" href="https://b.example/x"/><updated>2026-10-26T01:00:00Z</updated><author><name>Bo</name></author><summary>s</summary></entry></feed>"""
    items = feeds.parse_feed(atom, "b.example")
    assert items[0].link == "https://b.example/x" and items[0].author == "Bo"
    jsonfeed = json.dumps(
        {
            "items": [
                {
                    "title": "J",
                    "url": "https://c.example/j",
                    "date_published": "2026-10-26T02:00:00+00:00",
                    "content_text": "body",
                }
            ]
        }
    ).encode()
    assert feeds.parse_feed(jsonfeed, "c")[0].summary == "body"
    assert feeds.parse_feed(b"garbage", "d") == []
    html = """<div class="tgme_widget_message" data-post="chan/12"><div class="tgme_widget_message_text">Hello <a href="https://x.example/p">link</a> there<br/>line two</div><time datetime="2026-10-26T03:00:00+00:00"></time></div>
    <div class="tgme_widget_message" data-post="chan/13"><div class="tgme_widget_message_text">Second</div><time datetime="2026-10-26T04:00:00+00:00"></time></div>"""
    items = feeds.parse_telegram(html, "chan")
    assert [i.title for i in items] == ["Hello link there", "Second"]
    assert (
        items[0].link == "https://x.example/p"
        and items[1].link == "https://t.me/chan/13"
        and items[0].published_ts
    )
    assert (
        feeds.source_name("https://news.ycombinator.com/") == "Hacker News"
        and feeds.source_name("https://t.me/foo") == "@foo"
    )


async def test_news_tools_with_mocked_hn(tmp_path, monkeypatch):
    from sidekick.extension import import_file

    feeds = import_file(ROOT / "news", "feeds.py", "news")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/topstories.json"):
            return httpx.Response(200, json=[1, 2])
        if request.url.path.endswith("/item/1.json"):
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "title": "Big story",
                    "score": 300,
                    "time": 1700000000,
                    "url": "https://s.example/1",
                    "by": "pg",
                },
            )
        if request.url.path.endswith("/item/2.json"):
            return httpx.Response(
                200, json={"id": 2, "title": "Small", "score": 10, "time": 1700000000}
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await feeds.fetch_source("https://news.ycombinator.com/", client, 100)
    assert [i.title for i in items] == ["Big story"] and items[0].extra["score"] == 300


async def test_media_and_home_tools_over_mock(tmp_path):
    calls = []

    def media_handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/torrents/info":
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "Movie",
                        "state": "downloading",
                        "progress": 0.5,
                        "size": 2_000_000_000,
                        "dlspeed": 1_000_000,
                    }
                ],
            )
        if request.url.path == "/api/v2/torrents/add":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/Items":
            return httpx.Response(
                200,
                json={
                    "Items": [
                        {"Id": "1", "Name": "Totoro", "Type": "Movie", "ProductionYear": 1988}
                    ]
                },
            )
        if request.url.path == "/Sessions":
            return httpx.Response(
                200,
                json=[
                    {"UserName": "dad", "DeviceName": "TV", "NowPlayingItem": {"Name": "Totoro"}}
                ],
            )
        return httpx.Response(404)

    media = tools_of(
        "media",
        ExtensionContext(
            "media",
            {
                "qbittorrent_url": "http://qb.test",
                "qbittorrent_username": "u",
                "qbittorrent_password": "p",
                "jellyfin_url": "http://jf.test",
                "jellyfin_api_key": "k",
            },
            tmp_path,
        ),
    )
    # swap the clients to the mock transport
    import httpx as _httpx

    original = _httpx.AsyncClient

    class MockClient(original):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = _httpx.MockTransport(media_handler)
            super().__init__(*args, **kwargs)

    _httpx.AsyncClient = MockClient  # type: ignore[misc]
    try:
        result = await media["qbt_list"].handler({}, TCTX)
        assert result.ok and "Movie" in result.content and "50%" in result.content
        assert (await media["qbt_add"].handler({"url": "magnet:?xt=1"}, TCTX)).ok and media[
            "qbt_add"
        ].confirm
        result = await media["jellyfin_search"].handler({"query": "totoro"}, TCTX)
        assert result.ok and "Totoro" in result.content and "1988" in result.content
        assert "dad on TV" in (await media["jellyfin_now_playing"].handler({}, TCTX)).content
        unconfigured = tools_of("media", ExtensionContext("media", {}, tmp_path))
        assert "not configured" in (await unconfigured["qbt_list"].handler({}, TCTX)).content

        def home_handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["authorization"] == "Bearer tok"
            if request.url.path == "/api/states":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "entity_id": "light.kitchen",
                            "state": "off",
                            "attributes": {"friendly_name": "Kitchen"},
                        }
                    ],
                )
            if request.url.path == "/api/states/light.kitchen":
                return httpx.Response(
                    200,
                    json={
                        "entity_id": "light.kitchen",
                        "state": "off",
                        "attributes": {"friendly_name": "Kitchen", "brightness": 0},
                    },
                )
            if request.url.path == "/api/services/light/turn_on":
                return httpx.Response(200, json=[{"entity_id": "light.kitchen", "state": "on"}])
            return httpx.Response(404)

        class HomeClient(original):  # type: ignore[misc, valid-type]
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = _httpx.MockTransport(home_handler)
                super().__init__(*args, **kwargs)

        _httpx.AsyncClient = HomeClient  # type: ignore[misc]
        home = tools_of(
            "home", ExtensionContext("home", {"url": "http://ha.test", "token": "tok"}, tmp_path)
        )
        assert (
            "light.kitchen"
            in (await home["ha_entities"].handler({"query": "kitchen"}, TCTX)).content
        )
        assert (
            "is off"
            in (await home["ha_state"].handler({"entity_id": "light.kitchen"}, TCTX)).content
        )
        result = await home["ha_call"].handler(
            {"domain": "light", "service": "turn_on", "entity_id": "light.kitchen"}, TCTX
        )
        assert result.ok and "light.kitchen=on" in result.content
        assert not (
            await home["ha_call"].handler(
                {"domain": "lock", "service": "unlock", "entity_id": "lock.door"}, TCTX
            )
        ).ok
        assert home["ha_call_sensitive"].confirm
    finally:
        _httpx.AsyncClient = original  # type: ignore[misc]
    assert ("POST", "/api/v2/auth/login") in calls
