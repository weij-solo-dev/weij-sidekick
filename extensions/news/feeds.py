"""extensions.news.feeds — feed sources ported from Scoop's SCPSync (RSS/Atom/JSON Feed, Hacker News, Telegram)

Overview
    `fetch_source(url)` returns `FeedItem`s for a feed URL: RSS 2.0 / Atom / JSON Feed documents
    (sniffed), the Hacker News front page through the Firebase API (top stories above a score),
    and public Telegram channels through the server-rendered `t.me/s/<channel>` page. Parsing
    uses the standard library only (`xml.etree`, `html.parser`, `json`).
Design
    Straight port of the Swift backends' behaviour: sniff XML vs JSON by the first non-space
    byte, RSS `item` / Atom `entry` fields, HN `topstories` → items with `score >= min_score`,
    Telegram `div.tgme_widget_message[data-post]` with `time[datetime]` and
    `div.tgme_widget_message_text`. Network errors return an empty list and are logged by the
    caller; items carry `source` for grouping.
Depends on
    sidekick.log, httpx.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

from sidekick.log import Log

USER_AGENT = "Mozilla/5.0 (compatible; sidekick/0.1)"
HN_BASE = "https://hacker-news.firebaseio.com/v0"


@dataclass(frozen=True, slots=True)
class FeedItem:
    """One entry."""

    source: str
    title: str
    link: str
    published_ts: float | None = None
    summary: str = ""
    author: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def age_h(self) -> float | None:
        """Hours since publication."""
        return None if self.published_ts is None else (time.time() - self.published_ts) / 3600.0


_TAGS = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """Plain text from an HTML fragment."""
    return re.sub(r"\s+", " ", unescape(_TAGS.sub(" ", text or ""))).strip()


def parse_date(value: str | None) -> float | None:
    """RFC 2822 or ISO 8601 → timestamp."""
    if not value:
        return None
    value = value.strip()
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def source_name(url: str) -> str:
    """Short label from a URL."""
    host = urlparse(url).netloc.lower()
    if host == "news.ycombinator.com":
        return "Hacker News"
    if host == "t.me":
        return "@" + urlparse(url).path.strip("/").removeprefix("s/").split("/")[0]
    return host.removeprefix("www.").removeprefix("feeds.")


# ------------------------------------------------------------------ RSS / Atom / JSON Feed


def _text(element: ET.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_feed(data: bytes, source: str) -> list[FeedItem]:
    """RSS 2.0, Atom or JSON Feed bytes → items."""
    head = data.lstrip(b"\xef\xbb\xbf \t\r\n")[:1]
    if head in (b"{", b"["):
        return _parse_json_feed(data, source)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        Log.warning(f"feed {source}: xml parse failed: {exc}")
        return []
    items: list[FeedItem] = []
    for element in root.iter():
        kind = _local(element.tag)
        if kind not in ("item", "entry"):
            continue
        fields: dict[str, Any] = {}
        for child in element:
            name = _local(child.tag)
            if name == "link":
                href = child.get("href")
                if href and (child.get("rel") in (None, "alternate")):
                    fields.setdefault("link", href)
                elif _text(child):
                    fields.setdefault("link", _text(child))
            elif name in (
                "title",
                "description",
                "summary",
                "content",
                "encoded",
                "pubDate",
                "published",
                "updated",
                "author",
                "creator",
                "dc:creator",
            ):
                if name == "author":
                    name_el = next((c for c in child if _local(c.tag) == "name"), None)
                    fields["author"] = _text(name_el) if name_el is not None else _text(child)
                else:
                    fields.setdefault(name, _text(child))
        title = strip_html(fields.get("title", ""))
        link = fields.get("link", "")
        if not title or not link:
            continue
        items.append(
            FeedItem(
                source,
                title,
                link,
                parse_date(
                    fields.get("pubDate") or fields.get("published") or fields.get("updated")
                ),
                strip_html(
                    fields.get("description")
                    or fields.get("summary")
                    or fields.get("content")
                    or fields.get("encoded")
                    or ""
                )[:600],
                fields.get("author") or fields.get("creator"),
            )
        )
    return items


def _parse_json_feed(data: bytes, source: str) -> list[FeedItem]:
    try:
        feed = json.loads(data)
    except ValueError as exc:
        Log.warning(f"feed {source}: json parse failed: {exc}")
        return []
    items: list[FeedItem] = []
    for item in feed.get("items") or []:
        title = strip_html(str(item.get("title") or ""))
        link = str(item.get("url") or "")
        if not title or not link:
            continue
        author = (
            (item.get("author") or {}).get("name") if isinstance(item.get("author"), dict) else None
        )
        items.append(
            FeedItem(
                source,
                title,
                link,
                parse_date(item.get("date_published")),
                strip_html(
                    item.get("content_text")
                    or item.get("content_html")
                    or item.get("summary")
                    or ""
                )[:600],
                author,
            )
        )
    return items


# ---------------------------------------------------------------------- Hacker News


async def fetch_hackernews(
    client: httpx.AsyncClient, source: str, min_score: int = 100, top: int = 30
) -> list[FeedItem]:
    """Top stories above a score."""
    response = await client.get(f"{HN_BASE}/topstories.json")
    response.raise_for_status()
    ids = [int(i) for i in response.json()[:top]]

    async def story(story_id: int) -> dict[str, Any] | None:
        try:
            item = await client.get(f"{HN_BASE}/item/{story_id}.json")
            payload = item.json()
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    stories = [s for s in await asyncio.gather(*(story(i) for i in ids)) if s]
    items: list[FeedItem] = []
    for s in stories:
        if int(s.get("score") or 0) < min_score or not s.get("title"):
            continue
        link = str(s.get("url") or f"https://news.ycombinator.com/item?id={s['id']}")
        items.append(
            FeedItem(
                source,
                str(s["title"]),
                link,
                float(s["time"]) if s.get("time") else None,
                strip_html(str(s.get("text") or ""))[:600],
                s.get("by"),
                {
                    "score": s.get("score"),
                    "comments": s.get("descendants"),
                    "hn_url": f"https://news.ycombinator.com/item?id={s['id']}",
                },
            )
        )
    return items


# ------------------------------------------------------------------------- Telegram


class _TelegramParser(HTMLParser):
    """Collects messages from a `t.me/s/<channel>` page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.messages: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._in_text = 0
        self._text_depth = 0
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        self._depth += 1
        if tag == "div" and "tgme_widget_message" in classes and a.get("data-post"):
            self._current = {"post": a["data-post"], "text": "", "datetime": None, "links": []}
        elif self._current is not None:
            if tag == "time" and a.get("datetime"):
                self._current["datetime"] = a["datetime"]
            elif tag == "div" and "tgme_widget_message_text" in classes:
                self._in_text += 1
                self._text_depth = self._depth
            elif (
                tag == "a"
                and self._in_text
                and a.get("href", "").startswith("http")
                and "t.me" not in a.get("href", "")
            ):
                self._current["links"].append(a["href"])
            elif tag == "br" and self._in_text:
                self._current["text"] += "\n"

    def handle_endtag(self, tag: str) -> None:
        if (
            self._current is not None
            and self._in_text
            and tag == "div"
            and self._depth == self._text_depth
        ):
            self._in_text -= 1
        self._depth -= 1
        if tag == "div" and self._current is not None and self._depth < 0:
            self._depth = 0

    def handle_data(self, data: str) -> None:
        if self._current is not None and self._in_text:
            self._current["text"] += data

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br" and self._current is not None and self._in_text:
            self._current["text"] += "\n"

    def flush(self) -> None:
        """Close the open message (the parser cannot tell where a widget ends reliably)."""
        if self._current is not None:
            self.messages.append(self._current)
            self._current = None


def parse_telegram(html: str, channel: str) -> list[FeedItem]:
    """Messages of a public channel page."""
    parser = _TelegramParser()
    # Split by widget so each message is parsed independently (robust to nesting).
    chunks = re.split(r'(?=<div class="tgme_widget_message[^"]*" data-post=")', html)
    items: list[FeedItem] = []
    for chunk in chunks:
        if "tgme_widget_message" not in chunk or "data-post" not in chunk:
            continue
        parser = _TelegramParser()
        parser.feed(chunk)
        parser.flush()
        for message in parser.messages:
            text = re.sub(r"[ \t]+", " ", message["text"]).strip()
            if not text:
                continue
            msg_id = message["post"].rsplit("/", 1)[-1]
            link = message["links"][0] if message["links"] else f"https://t.me/{channel}/{msg_id}"
            title = text.split("\n", 1)[0][:120]
            items.append(
                FeedItem(
                    f"@{channel}",
                    title,
                    link,
                    parse_date(message["datetime"]),
                    text[:600],
                    channel,
                    {"message_id": msg_id},
                )
            )
    return items[-20:]


# ------------------------------------------------------------------------ dispatcher


async def fetch_source(
    url: str, client: httpx.AsyncClient, hn_min_score: int = 100
) -> list[FeedItem]:
    """Items for a URL (type decided by host)."""
    name = source_name(url)
    host = urlparse(url).netloc.lower()
    if host == "news.ycombinator.com":
        return await fetch_hackernews(client, name, hn_min_score)
    if host == "t.me":
        channel = urlparse(url).path.strip("/").removeprefix("s/").split("/")[0]
        response = await client.get(f"https://t.me/s/{channel}", headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return parse_telegram(response.text, channel)
    response = await client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    response.raise_for_status()
    return parse_feed(response.content, name)
