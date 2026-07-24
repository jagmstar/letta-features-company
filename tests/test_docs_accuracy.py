from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
DT_HOME = REPO_ROOT.parent
META_DIR = DT_HOME / "meta"
API_DIR = REPO_ROOT / "api"
if str(META_DIR) not in sys.path:
    sys.path.insert(0, str(META_DIR))
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import production_scheduler as ps  # noqa: E402
import scheduled_demo as sd  # noqa: E402
import schedules_api as api  # noqa: E402


def _load_dashboard_module():
    import importlib.util

    dashboard_path = REPO_ROOT / "dashboard" / "generate_dashboard.py"
    spec = importlib.util.spec_from_file_location("generate_dashboard", dashboard_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load dashboard module from {dashboard_path}")
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


class DocsAccuracyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="docs-accuracy-")
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

    def test_api_has_all_documented_endpoints(self) -> None:
        status, headers, payload = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "schedules-api")
        self.assertEqual(payload["version"], "9.9.9-test")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")

        status, _, payload = self.request("GET", "/api/schedules", headers=self.auth_headers())
        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 2)
        self.assertEqual([item["name"] for item in payload["items"]], ["brief", "log"])

        status, _, payload = self.request("GET", "/api/schedules/brief", headers=self.auth_headers())
        self.assertEqual(status, 200)
        self.assertEqual(payload["name"], "brief")
        self.assertEqual(payload["paths"]["log"], str(self.log_path))
        self.assertEqual(payload["paths"]["brief"], str(self.brief_path))
        self.assertEqual(payload["paths"]["heartbeat"], str(self.heartbeat_path))

        status, _, payload = self.request("GET", "/api/schedules/brief/log", headers=self.auth_headers())
        self.assertEqual(status, 200)
        self.assertEqual(payload["name"], "brief")
        self.assertEqual(payload["entries"], [])

        status, _, payload = self.request("GET", "/api/schedules/brief/status", headers=self.auth_headers())
        self.assertEqual(status, 200)
        self.assertEqual(payload["name"], "brief")
        self.assertFalse(payload["running"])

        status, headers, payload = self.request("POST", "/api/schedules/brief/run", headers=self.auth_headers())
        self.assertEqual(status, 200)
        self.assertTrue(payload["triggered"])
        self.assertEqual(payload["name"], "brief")
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

        status, headers, _ = self.request("OPTIONS", "/api/schedules/brief")
        self.assertEqual(status, 204)
        self.assertEqual(headers["Access-Control-Allow-Methods"], "GET, POST, OPTIONS")

    def test_readme_test_commands_actually_work(self) -> None:
        commands = [
            [sys.executable, "-m", "pytest", str(REPO_ROOT / "tests" / "test_kill_tests.py"), "-q"],
            [sys.executable, str(REPO_ROOT / "tests" / "test_kill_tests.py"), "-q"],
        ]
        for command in commands:
            completed = subprocess.run(
                command,
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                msg=(
                    f"Command failed: {' '.join(command)}\n"
                    f"stdout:\n{completed.stdout}\n"
                    f"stderr:\n{completed.stderr}"
                ),
            )

    def test_configuration_options_exist_in_code(self) -> None:
        scheduled_demo_source = Path(sd.__file__).read_text(encoding="utf-8")
        production_scheduler_source = Path(ps.__file__).read_text(encoding="utf-8")
        schedules_api_source = Path(api.__file__).read_text(encoding="utf-8")
        dashboard_source = Path(gd.__file__).read_text(encoding="utf-8")

        for option in ["--source", "--task", 'choices=("brief", "log")']:
            self.assertIn(option, scheduled_demo_source)

        for option in ["--config", "--dry-run", 'BUILTIN_TASKS: dict[str, TaskFunction]']:
            self.assertIn(option, production_scheduler_source)

        for option in ["--host", "--port", "--api-key", "--request-log-path", "SCHEDULES_API_KEY", "X-API-Key"]:
            self.assertIn(option, schedules_api_source)

        self.assertIn("LOG_PATH = META_DIR /", dashboard_source)
        self.assertIn("BRIEF_PATH = META_DIR /", dashboard_source)
        self.assertIn("OUTPUT_PATH = Path(__file__).resolve().with_name(\"index.html\")", dashboard_source)

    def test_docker_files_exist_and_are_valid(self) -> None:
        dockerfile = REPO_ROOT / "Dockerfile"
        compose_file = REPO_ROOT / "docker-compose.yml"
        self.assertTrue(dockerfile.exists(), "Dockerfile is missing")
        self.assertTrue(compose_file.exists(), "docker-compose.yml is missing")

        dockerfile_text = dockerfile.read_text(encoding="utf-8")
        self.assertIn("FROM python:3.12-slim", dockerfile_text)
        self.assertIn("COPY api/ ./api/", dockerfile_text)
        self.assertIn("EXPOSE 8290", dockerfile_text)
        self.assertIn('CMD ["python", "api/schedules_api.py", "--host", "0.0.0.0", "--port", "8290"]', dockerfile_text)

        compose_text = compose_file.read_text(encoding="utf-8")
        self.assertIn("services:", compose_text)
        self.assertIn("api:", compose_text)
        self.assertIn("dashboard:", compose_text)
        self.assertIn('"8290:8290"', compose_text)
        self.assertIn('"8080:80"', compose_text)
        self.assertIn("./dashboard:/usr/share/nginx/html:ro", compose_text)

    def test_readme_installation_command_executes(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "pip", "pytest", "requests"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"pip install command failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
