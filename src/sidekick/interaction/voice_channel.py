"""sidekick.interaction.voice_channel — the robot's voice as a `ChannelAdapter`

Overview
    Lets the rest of sidekick treat in-person speech like any other channel: automations and
    the heartbeat `send()` a `ChannelReply` and the robot speaks it (opening a robot-initiated
    session so follow-ups work), while accepted turns appear as `ChannelMessage`s with
    `channel="voice"`.
Design
    Inbound messages are produced by the façade's turn loop (the responder is called directly
    so streaming is preserved); `start()` only records the handler for completeness. `send()`
    delegates to `InteractionSession.say()`.
Depends on
    sidekick.channel, sidekick.log.

See Also
--------
    AGENTS.md "Automations, heartbeat, delivery" (delivery policy `in_person`).

"""

from __future__ import annotations

from typing import Any

from sidekick.channel import ChannelCapabilities, ChannelReply, InboundHandler
from sidekick.log import Log


class VoiceChannel:
    """`ChannelAdapter` over the interaction session."""

    name = "voice"
    capabilities = ChannelCapabilities(text=True, audio=True, streaming=True, in_person=True)

    def __init__(self, session: Any) -> None:
        self.session = session
        self.handler: InboundHandler | None = None

    async def start(self, handler: InboundHandler) -> None:
        """Remember the handler (turns stream to the responder directly)."""
        self.handler = handler

    async def stop(self) -> None:
        """Nothing to stop; the façade owns the threads."""
        self.handler = None

    async def send(self, reply: ChannelReply) -> bool:
        """Speak a reply in the room."""
        if not reply.text.strip() and not reply.expression:
            return False
        result = await self.session.say(reply.text, expression=reply.expression, addressee=reply.to)
        if not result.ok:
            Log.warning(f"voice send failed: {result.error}")
        return bool(result.ok)
