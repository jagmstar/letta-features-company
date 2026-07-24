from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import schedules_api as api  # noqa: E402


class NonClosingBytesIO(io.BytesIO):
    def close(self) -> None:  # pragma: no cover - intentional for handler lifecycle
        pass


class MockSocket:
    def __init__(self, request_bytes: bytes) -> None:
        self._request = io.BytesIO(request_bytes)
        self.response = NonClosingBytesIO()

    def makefile(self, mode: str, *args, **kwargs):
        if "r" in mode:
            return self._request
        if "w" in mode:
            return self.response
        raise ValueError(f"unsupported mode: {mode}")

    def sendall(self, data: bytes) -> None:
        self.response.write(data)

    def close(self) -> None:  # pragma: no cover - nothing to close in tests
        pass


class ChannelsAPITestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.repo_root = self.root / "company"
        self.repo_root.mkdir(parents=True, exist_ok=True)
        self.request_log_path = self.root / "meta" / ".schedules-api-requests.log"
        self.api_key = "test-api-key"

        self.store = api.ScheduleStore(repo_root=self.repo_root)
        api.SchedulesHTTPRequestHandler.store = self.store
        self.context = api.APIContext(
            api_key=self.api_key,
            request_log_path=self.request_log_path,
            version="9.9.9-test",
            started_at=datetime.now(timezone.utc) - timedelta(seconds=90),
        )
        self.context.channels_manager._post_json = mock.Mock(return_value={"status": 200, "body": {"ok": True}})

    def request(
        self,
        method: str,
        path: str,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        remote_ip: str = "127.0.0.1",
    ):
        request_headers = {"Host": "localhost"}
        if headers:
            request_headers.update(headers)
        request_headers["Content-Length"] = str(len(body))
        header_block = "".join(f"{key}: {value}\r\n" for key, value in request_headers.items())
        raw_request = f"{method} {path} HTTP/1.1\r\n{header_block}\r\n".encode("utf-8") + body
        sock = MockSocket(raw_request)
        server = mock.Mock()
        server.server_name = "localhost"
        server.server_port = api.DEFAULT_PORT
        server.app_context = self.context
        api.SchedulesHTTPRequestHandler(sock, (remote_ip, 54321), server)
        return self.parse_response(sock.response.getvalue())

    @staticmethod
    def parse_response(raw: bytes):
        header_blob, body = raw.split(b"\r\n\r\n", 1)
        lines = header_blob.decode("utf-8").split("\r\n")
        status_line = lines[0]
        status = int(status_line.split()[1])
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()
        payload = json.loads(body.decode("utf-8")) if body else None
        return status, headers, payload

    def auth_headers(self) -> dict[str, str]:
        return {api.API_KEY_HEADER: self.api_key}

    def channel_payload(self, name: str, channel_type: str = "slack", enabled: bool = True) -> dict[str, object]:
        return {
            "name": name,
            "type": channel_type,
            "webhook_url": f"https://example.com/{name}",
            "enabled": enabled,
        }

    def seed_channel(self, name: str = "ops", channel_type: str = "slack", enabled: bool = True) -> api.Channel:
        channel = api.Channel(name=name, type=channel_type, webhook_url=f"https://example.com/{name}", enabled=enabled)
        self.context.channels_manager.register(channel)
        return channel

    def test_register_channel_endpoint(self) -> None:
        body = json.dumps(self.channel_payload("ops", "slack", True)).encode("utf-8")

        status, _, payload = self.request("POST", "/api/channels", body=body, headers=self.auth_headers())

        self.assertEqual(status, 201)
        self.assertEqual(payload["name"], "ops")
        self.assertEqual(payload["type"], "slack")
        self.assertTrue(payload["enabled"])
        self.assertEqual(self.context.channels_manager.get("ops").webhook_url, "https://example.com/ops")

    def test_list_channels_endpoint(self) -> None:
        self.seed_channel("ops", "slack")
        self.seed_channel("alerts", "discord")

        status, _, payload = self.request("GET", "/api/channels", headers=self.auth_headers())

        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 2)
        self.assertEqual([item["name"] for item in payload["items"]], ["ops", "alerts"])

    def test_get_channel_details_endpoint(self) -> None:
        self.seed_channel("alerts", "telegram")

        status, _, payload = self.request("GET", "/api/channels/alerts", headers=self.auth_headers())

        self.assertEqual(status, 200)
        self.assertEqual(payload["name"], "alerts")
        self.assertEqual(payload["type"], "telegram")
        self.assertTrue(payload["enabled"])

    def test_send_message_to_channel_endpoint(self) -> None:
        channel = self.seed_channel("ops", "slack")
        body = json.dumps({"message": "Deployment complete"}).encode("utf-8")

        status, _, payload = self.request("POST", "/api/channels/ops/send", body=body, headers=self.auth_headers())

        self.assertEqual(status, 200)
        self.assertEqual(payload["channel"], "ops")
        self.assertEqual(payload["payload"], {"text": "Deployment complete"})
        self.context.channels_manager._post_json.assert_called_once_with(
            channel.webhook_url,
            {"text": "Deployment complete"},
        )

    def test_broadcast_to_enabled_channels_endpoint(self) -> None:
        self.seed_channel("ops", "slack")
        self.seed_channel("prod", "discord")
        self.seed_channel("quiet", "telegram", enabled=False)
        body = json.dumps({"message": "All systems green"}).encode("utf-8")

        status, _, payload = self.request("POST", "/api/channels/broadcast", body=body, headers=self.auth_headers())

        self.assertEqual(status, 200)
        self.assertEqual(payload["message"], "All systems green")
        self.assertEqual(len(payload["sent"]), 2)
        self.assertEqual(payload["failed"], [])
        self.assertEqual(self.context.channels_manager._post_json.call_count, 2)

    def test_delete_channel_endpoint(self) -> None:
        self.seed_channel("ops", "slack")

        status, _, payload = self.request("DELETE", "/api/channels/ops", headers=self.auth_headers())

        self.assertEqual(status, 200)
        self.assertEqual(payload["removed"]["name"], "ops")
        with self.assertRaises(api.ChannelNotFoundError):
            self.context.channels_manager.get("ops")

    def test_get_missing_channel_returns_404(self) -> None:
        status, _, payload = self.request("GET", "/api/channels/missing", headers=self.auth_headers())

        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "channel_not_found")
        self.assertEqual(payload["error"]["status"], 404)

    def test_rejects_invalid_json_payload(self) -> None:
        status, _, payload = self.request("POST", "/api/channels", body=b"{not-json", headers=self.auth_headers())

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_json")
        self.assertEqual(payload["error"]["status"], 400)

    def test_disabled_channel_rejected_for_send(self) -> None:
        self.seed_channel("disabled", "telegram", enabled=False)
        body = json.dumps({"message": "hello"}).encode("utf-8")

        status, _, payload = self.request("POST", "/api/channels/disabled/send", body=body, headers=self.auth_headers())

        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "channel_disabled")
        self.assertEqual(payload["error"]["status"], 409)
        self.context.channels_manager._post_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
