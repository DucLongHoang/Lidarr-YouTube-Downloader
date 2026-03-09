"""Telegram and Discord webhook notifications."""

import logging

import requests

from config import load_config

logger = logging.getLogger(__name__)


def send_telegram(message, log_type=None):
    """Send a message via Telegram bot API.

    Args:
        message: Text to send.
        log_type: If set, only send when this type is in the
            configured telegram_log_types list.
    """
    config = load_config()
    if not (
        config.get("telegram_enabled")
        and config.get("telegram_bot_token")
        and config.get("telegram_chat_id")
    ):
        return

    if log_type is not None:
        allowed_types = config.get("telegram_log_types", [])
        if log_type not in allowed_types:
            return

    try:
        url = (
            f"https://api.telegram.org/"
            f"bot{config['telegram_bot_token']}/sendMessage"
        )
        requests.post(
            url,
            json={
                "chat_id": config["telegram_chat_id"],
                "text": message,
            },
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"Telegram notification failed: {e}")


def send_discord(message, log_type=None, embed_data=None):
    """Send a message or embed via Discord webhook.

    Args:
        message: Fallback text content.
        log_type: If set, only send when this type is in the
            configured discord_log_types list.
        embed_data: Optional dict with title, description, color,
            thumbnail, and fields for a Discord embed.
    """
    config = load_config()
    if not config.get("discord_enabled"):
        return
    webhook_url = config.get("discord_webhook_url", "")
    if not webhook_url:
        return
    if log_type is not None:
        allowed_types = config.get("discord_log_types", [])
        if log_type not in allowed_types:
            return
    try:
        payload = {}
        if embed_data:
            embed = {
                "title": embed_data.get("title", ""),
                "description": embed_data.get("description", ""),
                "color": embed_data.get("color", 0x10B981),
            }
            if embed_data.get("thumbnail"):
                embed["thumbnail"] = {"url": embed_data["thumbnail"]}
            if embed_data.get("fields"):
                embed["fields"] = embed_data["fields"]
            payload["embeds"] = [embed]
        else:
            payload["content"] = message
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception as e:
        logger.warning(f"Discord notification failed: {e}")


def send_notifications(message, log_type=None, embed_data=None):
    """Send notification to all configured channels.

    Args:
        message: Text content for the notification.
        log_type: Filter key for per-channel log type filtering.
        embed_data: Optional Discord embed data dict.
    """
    send_telegram(message, log_type=log_type)
    send_discord(message, log_type=log_type, embed_data=embed_data)
