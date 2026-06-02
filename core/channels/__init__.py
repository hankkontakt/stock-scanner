"""
core/channels/__init__.py - MarketScan multi-channel alert channels

Alla kanaler är mjuka beroenden — om en kanals bibliotek saknas
eller konfiguration saknas, hoppar den över sig själv graciöst.
"""
from core.channels.telegram_channel import TelegramChannel
from core.channels.discord_channel import DiscordChannel
from core.channels.sms_channel import SmsChannel
from core.channels.push_channel import PushChannel

__all__ = [
    "TelegramChannel",
    "DiscordChannel",
    "SmsChannel",
    "PushChannel",
]
