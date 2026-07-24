from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
DT_HOME = REPO_ROOT.parent
META_DIR = DT_HOME / "meta"
API_DIR = REPO_ROOT / "api"
DASHBOARD_PATH = REPO_ROOT / "dashboard" / "generate_dashboard.py"

if str(META_DIR) not in sys.path:
    sys.path.insert(0, str(META_DIR))
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import production_scheduler as ps  # noqa: E402
import scheduled_demo as sd  # noqa: E402
import schedules_api as api  # noqa: E402


def _load_dashboard_module():
    spec = importlib.util.spec_from_file_location("generate_dashboard", DASHBOARD_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load dashboard module from {DASHBOARD_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gd = _load_dashboard_module()


class NonClosingBytesIO(io.BytesIO):
    def close(self) -> None:  # pragma: no cover - keep handler output readable after lifecycle ends
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


class KillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="schedules-kill-tests-")
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)

    @staticmethod
    def _parse_response(raw: bytes):
        header_blob, body = raw.split(b"\r\n\r\n", 1)
        lines = header_blob.decode("utf-8").split("\r\n")
        status = int(lines[0].split()[1])
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()
        payload = None
        if body:
            decoder = json.JSONDecoder()
            payload, _ = decoder.raw_decode(body.decode("utf-8"))
        return status, headers, payload

    def _request(self, store: api.ScheduleStore, method: str, path: str, body: bytes = b"", headers: dict[str, str] | None = None):
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

        api.SchedulesHTTPRequestHandler.store = store
        api.SchedulesHTTPRequestHandler(sock, ("127.0.0.1", 54321), server)
        return self._parse_response(sock.response.getvalue())

    def test_scheduled_demo_rejects_invalid_task_value(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            sd.parse_args(["--task", "definitely-not-valid"])

        self.assertEqual(cm.exception.code, 2)

    def test_production_scheduler_rejects_malformed_config(self) -> None:
        config_path = self.root / "scheduler_config.json"
        config_path.write_text('{"log": {', encoding="utf-8")

        with self.assertRaises(json.JSONDecodeError):
            ps.Scheduler.from_config(config_path)

    def test_api_returns_bad_request_for_invalid_json_body(self) -> None:
        demo_module = SimpleNamespace(
            build_brief=mock.Mock(return_value={"summary": "inbox=1; voice=ok", "task": "brief"}),
            write_brief_snapshot=mock.Mock(return_value=str(self.root / "brief.json")),
            append_demo_line=mock.Mock(return_value="2026-01-01T00:00:00+00:00 scheduled-demo task=brief source=api host=testhost user=testuser pid=123 detail=inbox=1; voice=ok"),
            write_heartbeat_state=mock.Mock(return_value={"status": "ok", "task": "brief"}),
        )

        repo_root = self.root / "company"
        repo_root.mkdir(parents=True, exist_ok=True)
        store = api.ScheduleStore(
            repo_root=repo_root,
            demo_module=demo_module,
            log_path=self.root / "meta" / ".scheduled-demo.log",
            brief_path=self.root / "meta" / ".scheduled-demo-brief.json",
            heartbeat_path=self.root / "meta" / "heartbeat-step-health.jsonl",
        )

        status, _, payload = self._request(
            store,
            "POST",
            "/api/schedules/brief/run",
            body=b'{"broken": true,',
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(status, 400, msg=f"API accepted invalid JSON and returned {status}: {payload}")
        self.assertEqual(payload["error"]["code"], "invalid_json")

    def test_dashboard_generator_handles_missing_log_file_gracefully(self) -> None:
        log_path = self.root / "meta" / ".scheduled-demo.log"
        brief_path = self.root / "meta" / ".scheduled-demo-brief.json"
        brief_path.parent.mkdir(parents=True, exist_ok=True)
        brief_path.write_text(
            json.dumps(
                {
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "summary": "inbox=0; voice=ok",
                    "inbox": {"top_items": [], "signal_counts": {}},
                    "team_status": {"agent_count": 0, "online_count": 0, "status": {}},
                    "voice_health": {"available": True, "summary": "voice healthy"},
                }
            ),
            encoding="utf-8",
        )

        with mock.patch.object(gd, "LOG_PATH", log_path), mock.patch.object(gd, "BRIEF_PATH", brief_path):
            try:
                gd.build_dashboard()
            except Exception as exc:
                self.assertIsInstance(
                    exc,
                    RuntimeError,
                    msg=f"Expected a RuntimeError for a missing log file, got {type(exc).__name__}: {exc}",
                )
            else:
                self.fail("Expected dashboard generator to raise RuntimeError for a missing log file")


if __name__ == "__main__":
    unittest.main(verbosity=2)
