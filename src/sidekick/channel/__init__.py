"""sidekick.channel — adapter protocol, message types, registry, Telegram and WeChat adapters."""

from .channel import ChannelSession
from .schemas import (
    ChannelAdapter,
    ChannelCapabilities,
    ChannelMessage,
    ChannelReply,
    InboundHandler,
)
from .telegram import TelegramAdapter
from .wechat import WeChatAdapter, WeChatClient, WeChatLogin, WeChatState, message_text

__all__ = [
    "ChannelAdapter",
    "ChannelCapabilities",
    "ChannelMessage",
    "ChannelReply",
    "ChannelSession",
    "InboundHandler",
    "TelegramAdapter",
    "WeChatAdapter",
    "WeChatClient",
    "WeChatLogin",
    "WeChatState",
    "message_text",
]
