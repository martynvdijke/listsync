"""
Notification modules for ListSync.
"""

from .discord import send_to_discord_webhook
from .gotify import send_to_gotify

__all__ = ['send_to_discord_webhook', 'send_to_gotify']
