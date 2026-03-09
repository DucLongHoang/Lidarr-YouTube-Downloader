"""Tests for notifications module — Telegram and Discord webhooks."""

from unittest.mock import patch, MagicMock

import pytest

import notifications


@pytest.fixture
def mock_config():
    return {
        "telegram_enabled": True,
        "telegram_bot_token": "token123",
        "telegram_chat_id": "chat456",
        "telegram_log_types": ["album_error", "partial_success"],
        "discord_enabled": True,
        "discord_webhook_url": "https://discord.com/api/webhooks/test",
        "discord_log_types": ["album_error", "partial_success"],
    }


# --- send_telegram ---


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_telegram_sends_message(mock_cfg, mock_post, mock_config):
    mock_cfg.return_value = mock_config
    notifications.send_telegram("test msg", log_type="album_error")
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert payload["text"] == "test msg"
    assert payload["chat_id"] == "chat456"


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_telegram_filters_log_type(
    mock_cfg, mock_post, mock_config
):
    mock_cfg.return_value = mock_config
    notifications.send_telegram("test msg", log_type="download_started")
    mock_post.assert_not_called()


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_telegram_no_log_type_sends(
    mock_cfg, mock_post, mock_config
):
    """When log_type is None, no filtering occurs."""
    mock_cfg.return_value = mock_config
    notifications.send_telegram("test msg")
    mock_post.assert_called_once()


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_telegram_disabled(mock_cfg, mock_post, mock_config):
    mock_config["telegram_enabled"] = False
    mock_cfg.return_value = mock_config
    notifications.send_telegram("test msg", log_type="album_error")
    mock_post.assert_not_called()


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_telegram_missing_token(mock_cfg, mock_post, mock_config):
    mock_config["telegram_bot_token"] = ""
    mock_cfg.return_value = mock_config
    notifications.send_telegram("test msg", log_type="album_error")
    mock_post.assert_not_called()


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_telegram_missing_chat_id(mock_cfg, mock_post, mock_config):
    mock_config["telegram_chat_id"] = ""
    mock_cfg.return_value = mock_config
    notifications.send_telegram("test msg", log_type="album_error")
    mock_post.assert_not_called()


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_telegram_exception_logged(
    mock_cfg, mock_post, mock_config, caplog
):
    mock_cfg.return_value = mock_config
    mock_post.side_effect = Exception("network error")
    notifications.send_telegram("test msg", log_type="album_error")
    assert "Telegram notification failed" in caplog.text


# --- send_discord ---


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_discord_sends_plain_message(
    mock_cfg, mock_post, mock_config
):
    mock_cfg.return_value = mock_config
    notifications.send_discord("plain msg", log_type="album_error")
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert payload["content"] == "plain msg"


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_discord_sends_embed(mock_cfg, mock_post, mock_config):
    mock_cfg.return_value = mock_config
    embed = {
        "title": "Test",
        "description": "desc",
        "color": 0xFF0000,
    }
    notifications.send_discord(
        "msg", log_type="album_error", embed_data=embed
    )
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert "embeds" in payload
    assert payload["embeds"][0]["title"] == "Test"
    assert payload["embeds"][0]["color"] == 0xFF0000


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_discord_embed_with_thumbnail(
    mock_cfg, mock_post, mock_config
):
    mock_cfg.return_value = mock_config
    embed = {
        "title": "T",
        "description": "d",
        "thumbnail": "https://img.example.com/art.jpg",
    }
    notifications.send_discord(
        "msg", log_type="album_error", embed_data=embed
    )
    call_kwargs = mock_post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert payload["embeds"][0]["thumbnail"]["url"] == embed["thumbnail"]


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_discord_embed_with_fields(
    mock_cfg, mock_post, mock_config
):
    mock_cfg.return_value = mock_config
    fields = [{"name": "Artist", "value": "Test", "inline": True}]
    embed = {"title": "T", "description": "d", "fields": fields}
    notifications.send_discord(
        "msg", log_type="album_error", embed_data=embed
    )
    call_kwargs = mock_post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert payload["embeds"][0]["fields"] == fields


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_discord_filters_log_type(
    mock_cfg, mock_post, mock_config
):
    mock_cfg.return_value = mock_config
    notifications.send_discord("msg", log_type="download_started")
    mock_post.assert_not_called()


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_discord_disabled(mock_cfg, mock_post, mock_config):
    mock_config["discord_enabled"] = False
    mock_cfg.return_value = mock_config
    notifications.send_discord("msg", log_type="album_error")
    mock_post.assert_not_called()


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_discord_no_webhook_url(mock_cfg, mock_post, mock_config):
    mock_config["discord_webhook_url"] = ""
    mock_cfg.return_value = mock_config
    notifications.send_discord("msg", log_type="album_error")
    mock_post.assert_not_called()


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_discord_no_log_type_sends(
    mock_cfg, mock_post, mock_config
):
    mock_cfg.return_value = mock_config
    notifications.send_discord("msg")
    mock_post.assert_called_once()


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_discord_exception_logged(
    mock_cfg, mock_post, mock_config, caplog
):
    mock_cfg.return_value = mock_config
    mock_post.side_effect = Exception("webhook error")
    notifications.send_discord("msg", log_type="album_error")
    assert "Discord notification failed" in caplog.text


# --- send_notifications ---


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_notifications_calls_both(
    mock_cfg, mock_post, mock_config
):
    mock_cfg.return_value = mock_config
    notifications.send_notifications("msg", log_type="album_error")
    assert mock_post.call_count == 2


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_notifications_passes_embed(
    mock_cfg, mock_post, mock_config
):
    mock_cfg.return_value = mock_config
    embed = {"title": "T", "description": "d", "color": 0x00FF00}
    notifications.send_notifications(
        "msg", log_type="album_error", embed_data=embed
    )
    assert mock_post.call_count == 2
    # Discord call should have embed
    discord_call = mock_post.call_args_list[1]
    payload = (
        discord_call.kwargs.get("json")
        or discord_call[1].get("json")
    )
    assert "embeds" in payload


@patch("notifications.requests.post")
@patch("notifications.load_config")
def test_send_notifications_filtered_sends_none(
    mock_cfg, mock_post, mock_config
):
    mock_cfg.return_value = mock_config
    notifications.send_notifications(
        "msg", log_type="download_started"
    )
    mock_post.assert_not_called()
