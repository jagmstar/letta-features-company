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


class SchedulesAPITestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.repo_root = self.root / "company"
        self.repo_root.mkdir(parents=True, exist_ok=True)
        self.log_path = self.root / "meta" / ".scheduled-demo.log"
        self.request_log_path = self.root / "meta" / ".schedules-api-requests.log"
        self.brief_path = self.root / "meta" / ".scheduled-demo-brief.json"
        self.heartbeat_path = self.root / "meta" / "heartbeat-step-health.jsonl"
        self.snapshot_path = self.root / "snapshots" / "brief.json"
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        self.api_key = "test-api-key"

        self.demo_module = SimpleNamespace(
            build_brief=mock.Mock(return_value={"summary": "inbox=1; voice=ok", "task": "brief"}),
            write_brief_snapshot=mock.Mock(return_value=str(self.snapshot_path)),
            append_demo_line=mock.Mock(side_effect=self._build_log_line),
            write_heartbeat_state=mock.Mock(return_value={"status": "ok", "task": "brief"}),
        )

        self.store = api.ScheduleStore(
            repo_root=self.repo_root,
            demo_module=self.demo_module,
            log_path=self.log_path,
            brief_path=self.brief_path,
            heartbeat_path=self.heartbeat_path,
        )
        api.SchedulesHTTPRequestHandler.store = self.store
        self.context = api.APIContext(
            api_key=self.api_key,
            request_log_path=self.request_log_path,
            version="9.9.9-test",
            started_at=datetime.now(timezone.utc) - timedelta(seconds=90),
        )

    def _build_log_line(self, source: str, task: str, detail: str = "") -> str:
        suffix = f" detail={detail}" if detail else ""
        return (
            f"2026-01-01T00:00:00+00:00 scheduled-demo task={task} source={source} "
            f"host=testhost user=testuser pid=123{suffix}"
        )

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

    def test_health_endpoint(self) -> None:
        status, headers, payload = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "schedules-api")
        self.assertEqual(payload["version"], "9.9.9-test")
        self.assertGreaterEqual(payload["uptime_seconds"], 90.0)
        self.assertIn("started_at", payload)
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")

    def test_health_endpoint_rejects_post(self) -> None:
        status, headers, payload = self.request("POST", "/api/health")
        self.assertEqual(status, 405)
        self.assertEqual(payload["error"]["code"], "method_not_allowed")
        self.assertEqual(payload["error"]["status"], 405)
        self.assertEqual(headers["Allow"], "GET")

    def test_requires_api_key_for_protected_endpoints(self) -> None:
        status, _, payload = self.request("GET", "/api/schedules")
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "missing_api_key")
        self.assertEqual(payload["error"]["status"], 401)

    def test_rejects_invalid_api_key(self) -> None:
        status, _, payload = self.request("GET", "/api/schedules", headers={api.API_KEY_HEADER: "wrong-key"})
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "invalid_api_key")
        self.assertEqual(payload["error"]["status"], 403)

    def test_list_schedules_endpoint(self) -> None:
        status, _, payload = self.request("GET", "/api/schedules", headers=self.auth_headers())
        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 2)
        self.assertEqual([item["name"] for item in payload["items"]], ["brief", "log"])

    def test_schedule_details_endpoint(self) -> None:
        status, _, payload = self.request("GET", "/api/schedules/brief", headers=self.auth_headers())
        self.assertEqual(status, 200)
        self.assertEqual(payload["name"], "brief")
        self.assertEqual(payload["status"], "stopped")
        self.assertEqual(payload["run_count"], 0)
        self.assertIn("paths", payload)

    def test_schedule_log_endpoint(self) -> None:
        status, _, payload = self.request("GET", "/api/schedules/brief/log", headers=self.auth_headers())
        self.assertEqual(status, 200)
        self.assertEqual(payload["name"], "brief")
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["entries"], [])

    def test_schedule_status_endpoint(self) -> None:
        status, _, payload = self.request("GET", "/api/schedules/brief/status", headers=self.auth_headers())
        self.assertEqual(status, 200)
        self.assertEqual(payload["name"], "brief")
        self.assertEqual(payload["status"], "stopped")
        self.assertFalse(payload["running"])

    def test_manual_run_endpoint(self) -> None:
        status, headers, payload = self.request("POST", "/api/schedules/brief/run", headers=self.auth_headers())
        self.assertEqual(status, 200)
        self.assertEqual(payload["name"], "brief")
        self.assertTrue(payload["triggered"])
        self.assertEqual(payload["status"], "stopped")
        self.assertEqual(payload["run_count"], 1)
        self.assertEqual(payload["result"]["brief"]["summary"], "inbox=1; voice=ok")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")
        self.demo_module.build_brief.assert_called_once_with("api")
        self.demo_module.write_brief_snapshot.assert_called_once()
        self.demo_module.append_demo_line.assert_called_once_with("api", "brief", "inbox=1; voice=ok")
        self.demo_module.write_heartbeat_state.assert_called_once_with("api", "brief", "inbox=1; voice=ok")

        log_status, _, log_payload = self.request("GET", "/api/schedules/brief/log", headers=self.auth_headers())
        self.assertEqual(log_status, 200)
        self.assertEqual(log_payload["count"], 1)
        self.assertEqual(log_payload["entries"][0]["task"], "brief")
        self.assertEqual(log_payload["entries"][0]["detail"], "inbox=1; voice=ok")

    def test_rate_limit_enforces_per_ip_limit(self) -> None:
        for _ in range(10):
            status, _, payload = self.request("GET", "/api/schedules", headers=self.auth_headers())
            self.assertEqual(status, 200)
            self.assertEqual(payload["count"], 2)

        status, headers, payload = self.request("GET", "/api/schedules", headers=self.auth_headers())
        self.assertEqual(status, 429)
        self.assertEqual(payload["error"]["code"], "rate_limit_exceeded")
        self.assertEqual(payload["error"]["status"], 429)
        self.assertIn("Retry-After", headers)

    def test_requests_are_logged_to_file(self) -> None:
        status, _, payload = self.request("GET", "/api/schedules/brief", headers=self.auth_headers())
        self.assertEqual(status, 200)
        self.assertEqual(payload["name"], "brief")
        self.assertTrue(self.request_log_path.exists())

        lines = self.request_log_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["method"], "GET")
        self.assertEqual(record["path"], "/api/schedules/brief")
        self.assertEqual(record["status"], 200)
        self.assertEqual(record["client_ip"], "127.0.0.1")
        self.assertEqual(record["error_code"], None)

    def test_unknown_schedule_returns_404(self) -> None:
        status, _, payload = self.request("GET", "/api/schedules/unknown", headers=self.auth_headers())
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "task_not_found")
        self.assertEqual(payload["error"]["status"], 404)

    def test_invalid_request_returns_405(self) -> None:
        status, headers, payload = self.request("GET", "/api/schedules/brief/run", headers=self.auth_headers())
        self.assertEqual(status, 405)
        self.assertEqual(payload["error"]["code"], "method_not_allowed")
        self.assertEqual(payload["error"]["status"], 405)
        self.assertEqual(headers["Allow"], "POST")


if __name__ == "__main__":
    unittest.main()
