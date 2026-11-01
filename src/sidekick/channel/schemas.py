"""sidekick.channel.schemas — inbound messages, replies and the adapter protocol every channel implements

Overview
    A channel is anything a person talks through: the robot's voice front end, Telegram, WeChat.
    All of them deliver `ChannelMessage`s to one handler (the agent) and accept `ChannelReply`s
    back. The protocol is deliberately small so the dialogue timeline (invariant 12) and the
    reply routing rule (invariant 14) see every channel the same way.
Design
    Frozen dataclasses; `speaker` is a contact id, `guest:<n>` or the channel's own user id when
    identification is not available; `language` is the ISO-like code used project-wide (`yue`,
    `zh`, `en`) or None for unknown. Capabilities tell the agent what a reply may contain.
Depends on
    stdlib only.

See Also
--------
    AGENTS.md "Dialogue and memory", "Automations, heartbeat, delivery".

"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ChannelCapabilities:
    """What a channel can carry."""

    text: bool = True
    audio: bool = False
    images: bool = False
    streaming: bool = False
    in_person: bool = False


@dataclass(frozen=True, slots=True)
class ChannelMessage:
    """One inbound message."""

    channel: str
    speaker: str
    text: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = field(default_factory=time.time)
    language: str | None = None
    reply_to: str | None = None
    attachments: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChannelReply:
    """One outbound message."""

    text: str
    channel: str | None = None
    to: str | None = None
    expression: str | None = None
    reply_to: str | None = None
    attachments: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


InboundHandler = Callable[[ChannelMessage], Awaitable[None]]


class ChannelAdapter(Protocol):
    """Start/stop plus send; inbound goes to the handler given at start."""

    name: str
    capabilities: ChannelCapabilities

    async def start(self, handler: InboundHandler) -> None:
        """Begin delivering inbound messages to `handler`."""
        ...

    async def stop(self) -> None:
        """Stop delivering."""
        ...

    async def send(self, reply: ChannelReply) -> bool:
        """Deliver a reply; False when the channel could not."""
        ...
