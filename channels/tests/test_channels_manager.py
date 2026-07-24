from __future__ import annotations

from pathlib import Path
from unittest import mock
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from channels.channels_manager import (  # noqa: E402
    Channel,
    ChannelNotFoundError,
    ChannelsManager,
    DisabledChannelError,
)


def test_register_a_channel() -> None:
    manager = ChannelsManager()
    channel = Channel(name="ops", type="slack", webhook_url="https://hooks.slack.com/services/T000/B000/XXX")

    registered = manager.register(channel)

    assert registered is channel
    assert manager.get("ops") is channel
    assert manager.list() == [channel]


def test_enable_disable_a_channel() -> None:
    manager = ChannelsManager()
    channel = Channel(name="alerts", type="discord", webhook_url="https://discord.com/api/webhooks/123/abc", enabled=False)
    manager.register(channel)

    assert manager.get("alerts").enabled is False

    manager.enable("alerts")
    assert manager.get("alerts").enabled is True

    manager.disable("alerts")
    assert manager.get("alerts").enabled is False


def test_send_message_to_a_channel_mocked() -> None:
    manager = ChannelsManager()
    channel = Channel(name="alerts", type="slack", webhook_url="https://hooks.slack.com/services/T000/B000/XXX")
    manager.register(channel)

    post_json = mock.Mock(return_value={"status": 200, "body": {"ok": True}})
    manager._post_json = post_json  # type: ignore[method-assign]

    receipt = manager.send_message("Deployment completed", "alerts")

    assert receipt["channel"] == "alerts"
    assert receipt["type"] == "slack"
    assert receipt["payload"] == {"text": "Deployment completed"}
    assert receipt["response"] == {"status": 200, "body": {"ok": True}}
    post_json.assert_called_once_with("https://hooks.slack.com/services/T000/B000/XXX", {"text": "Deployment completed"})
    assert manager.message_log[-1]["message"] == "Deployment completed"


def test_broadcast_to_all_channels_mocked() -> None:
    manager = ChannelsManager()
    slack = Channel(name="ops", type="slack", webhook_url="https://hooks.slack.com/services/T000/B000/SLACK")
    telegram = Channel(name="team", type="telegram", webhook_url="https://api.telegram.org/botTOKEN/sendMessage")
    discord = Channel(name="prod", type="discord", webhook_url="https://discord.com/api/webhooks/123/abc")
    manager.register(slack)
    manager.register(telegram)
    manager.register(discord)

    post_json = mock.Mock(side_effect=lambda url, payload: {"url": url, "payload": payload})
    manager._post_json = post_json  # type: ignore[method-assign]

    result = manager.broadcast("System maintenance at 22:00 UTC")

    assert len(result["sent"]) == 3
    assert result["failed"] == []
    assert post_json.call_count == 3
    assert mock.call("https://hooks.slack.com/services/T000/B000/SLACK", {"text": "System maintenance at 22:00 UTC"}) in post_json.call_args_list
    assert mock.call("https://api.telegram.org/botTOKEN/sendMessage", {"text": "System maintenance at 22:00 UTC"}) in post_json.call_args_list
    assert mock.call("https://discord.com/api/webhooks/123/abc", {"content": "System maintenance at 22:00 UTC"}) in post_json.call_args_list


def test_channel_not_found_rejected() -> None:
    manager = ChannelsManager()

    with pytest.raises(ChannelNotFoundError):
        manager.send_message("hello", "missing")


def test_disabled_channel_rejection() -> None:
    manager = ChannelsManager()
    channel = Channel(name="disabled", type="telegram", webhook_url="https://api.telegram.org/botTOKEN/sendMessage", enabled=False)
    manager.register(channel)

    with pytest.raises(DisabledChannelError):
        manager.send_message("hello", "disabled")
