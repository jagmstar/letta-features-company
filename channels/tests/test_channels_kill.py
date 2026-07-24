from __future__ import annotations

import logging
import sys
from pathlib import Path
from urllib.error import URLError

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from channels.channels_manager import Channel, ChannelsManager  # noqa: E402


def _unsafe_channel(
    *,
    name: str,
    type_: str,
    webhook_url: str,
    enabled: bool = True,
) -> Channel:
    """Build a channel without running dataclass validation."""

    channel = object.__new__(Channel)
    channel.name = name
    channel.type = type_
    channel.webhook_url = webhook_url
    channel.enabled = enabled
    return channel


def test_register_rejects_empty_name() -> None:
    manager = ChannelsManager()
    channel = _unsafe_channel(name="", type_="slack", webhook_url="https://hooks.slack.com/services/T000/B000/XXX")

    with pytest.raises(ValueError, match="Channel name cannot be empty"):
        manager.register(channel)


def test_register_rejects_invalid_type() -> None:
    manager = ChannelsManager()
    channel = _unsafe_channel(name="ops", type_="sms", webhook_url="https://example.invalid/webhook")

    with pytest.raises(ValueError, match="Unsupported channel type"):
        manager.register(channel)


def test_register_rejects_empty_webhook_url() -> None:
    manager = ChannelsManager()
    channel = _unsafe_channel(name="ops", type_="slack", webhook_url="")

    with pytest.raises(ValueError, match="Channel webhook_url cannot be empty"):
        manager.register(channel)


def test_send_message_network_failure_is_handled(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ChannelsManager()
    manager.register(
        Channel(
            name="ops",
            type="slack",
            webhook_url="https://hooks.slack.com/services/T000/B000/XXX",
        )
    )

    def _raise_url_error(*args: object, **kwargs: object) -> None:
        raise URLError("network down")

    monkeypatch.setattr("channels.channels_manager.urlopen", _raise_url_error)
    caplog.set_level(logging.ERROR, logger="channels.channels_manager")

    try:
        result = manager.send_message("Deployment completed", "ops")
    except Exception as exc:  # pragma: no cover - exercising the current bug path
        pytest.fail(f"send_message should catch network failures and keep going, but it raised {exc!r}")

    assert result is None
    assert "Failed to send message to ops" in caplog.text


def test_broadcast_returns_empty_list_when_every_channel_is_disabled() -> None:
    manager = ChannelsManager()
    manager.register(
        Channel(
            name="ops",
            type="slack",
            webhook_url="https://hooks.slack.com/services/T000/B000/XXX",
            enabled=False,
        )
    )
    manager.register(
        Channel(
            name="alerts",
            type="discord",
            webhook_url="https://discord.com/api/webhooks/123/abc",
            enabled=False,
        )
    )

    result = manager.broadcast("maintenance window")

    assert result == []


def test_register_rejects_duplicate_channel() -> None:
    manager = ChannelsManager()
    manager.register(
        Channel(
            name="ops",
            type="slack",
            webhook_url="https://hooks.slack.com/services/T000/B000/XXX",
        )
    )

    duplicate = Channel(
        name="ops",
        type="telegram",
        webhook_url="https://api.telegram.org/botTOKEN/sendMessage",
    )

    with pytest.raises(ValueError, match="already registered"):
        manager.register(duplicate)
