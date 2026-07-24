from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)
ChannelType = Literal["slack", "telegram", "discord"]


class ChannelError(Exception):
    """Base exception for channel management errors."""


class ChannelNotFoundError(ChannelError):
    """Raised when a requested channel does not exist."""


class DisabledChannelError(ChannelError):
    """Raised when a disabled channel receives a message."""


class ChannelSendError(ChannelError):
    """Raised when a channel message cannot be delivered."""


@dataclass(slots=True)
class Channel:
    name: str
    type: ChannelType
    webhook_url: str
    enabled: bool = True

    def __post_init__(self) -> None:
        allowed_types = {"slack", "telegram", "discord"}
        if self.type not in allowed_types:
            raise ValueError(f"Unsupported channel type: {self.type}")
        if not self.name:
            raise ValueError("Channel name cannot be empty")
        if not self.webhook_url:
            raise ValueError("Channel webhook_url cannot be empty")


class ChannelsManager:
    """Register and deliver messages to configured communication channels."""

    def __init__(self, *, timeout: float = 10.0) -> None:
        self._channels: dict[str, Channel] = {}
        self.timeout = timeout
        self.message_log: list[dict[str, Any]] = []

    def register(self, channel: Channel) -> Channel:
        """Register or replace a channel by name."""

        self._channels[channel.name] = channel
        logger.info("Registered channel %s (%s)", channel.name, channel.type)
        return channel

    def get(self, name: str) -> Channel:
        try:
            return self._channels[name]
        except KeyError as exc:
            raise ChannelNotFoundError(f"Channel not found: {name}") from exc

    def enable(self, name: str) -> Channel:
        channel = self.get(name)
        channel.enabled = True
        logger.info("Enabled channel %s", name)
        return channel

    def disable(self, name: str) -> Channel:
        channel = self.get(name)
        channel.enabled = False
        logger.info("Disabled channel %s", name)
        return channel

    def list(self) -> list[Channel]:
        return list(self._channels.values())

    def send_message(self, message: str, channel_name: str) -> dict[str, Any]:
        """Send a message to a single registered channel."""

        channel = self.get(channel_name)
        if not channel.enabled:
            raise DisabledChannelError(f"Channel is disabled: {channel_name}")
        return self._send_to_channel(channel, message)

    def broadcast(self, message: str) -> dict[str, list[dict[str, Any]]]:
        """Send a message to every enabled channel."""

        sent: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for channel in self.list():
            if not channel.enabled:
                continue
            try:
                sent.append(self._send_to_channel(channel, message))
            except ChannelSendError as exc:
                failed.append({"channel": channel.name, "error": str(exc)})
        return {"sent": sent, "failed": failed}

    def _send_to_channel(self, channel: Channel, message: str) -> dict[str, Any]:
        payload = self._build_payload(channel, message)
        try:
            response = self._post_json(channel.webhook_url, payload)
        except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            logger.exception("Failed to send message to %s", channel.name)
            raise ChannelSendError(f"Failed to send message to channel: {channel.name}") from exc

        receipt = {
            "channel": channel.name,
            "type": channel.type,
            "enabled": channel.enabled,
            "message": message,
            "payload": payload,
            "response": response,
        }
        self.message_log.append(receipt)
        logger.info("Sent message to %s (%s): %s", channel.name, channel.type, message)
        return receipt

    @staticmethod
    def _build_payload(channel: Channel, message: str) -> dict[str, Any]:
        if channel.type == "discord":
            return {"content": message}
        return {"text": message}

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=self.timeout) as response:
            raw_body = response.read()
            if not raw_body:
                return {"status": getattr(response, "status", None), "body": None}

            body_text = raw_body.decode("utf-8")
            try:
                body: Any = json.loads(body_text)
            except json.JSONDecodeError:
                body = body_text
            return {"status": getattr(response, "status", None), "body": body}
