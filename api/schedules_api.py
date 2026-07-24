from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_PORT = 8290
API_PREFIX = "/api"
API_VERSION = "2.0.0"
API_KEY_HEADER = "X-API-Key"
RATE_LIMIT_MAX_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60
REPO_ROOT = Path(__file__).resolve().parents[1]
META_ROOT = REPO_ROOT.parent / "meta"
DEFAULT_DEMO_PATH = META_ROOT / "scheduled_demo.py"
DEFAULT_LOG_PATH = META_ROOT / ".scheduled-demo.log"
DEFAULT_REQUEST_LOG_PATH = META_ROOT / ".schedules-api-requests.log"
DEFAULT_BRIEF_PATH = META_ROOT / ".scheduled-demo-brief.json"
DEFAULT_HEARTBEAT_PATH = META_ROOT / "heartbeat-step-health.jsonl"
DEFAULT_API_KEY = os.environ.get("SCHEDULES_API_KEY", "letta-schedules-demo-key")

LOG_LINE_RE = re.compile(
    r"^(?P<timestamp>\S+) scheduled-demo task=(?P<task>\S+) source=(?P<source>\S+) "
    r"host=(?P<host>\S+) user=(?P<user>\S+) pid=(?P<pid>\d+)(?: detail=(?P<detail>.*))?$"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {"items": data}


def load_scheduled_demo_module(path: Path = DEFAULT_DEMO_PATH) -> Any | None:
    """Load the local schedules demo implementation when it is available."""

    if not path.exists():
        return None

    spec = importlib.util.spec_from_file_location("scheduled_demo", path)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(slots=True)
class ScheduleDefinition:
    name: str
    description: str
    command: str
    task: str


@dataclass(slots=True)
class APIContext:
    api_key: str = DEFAULT_API_KEY
    request_log_path: Path = DEFAULT_REQUEST_LOG_PATH
    version: str = API_VERSION
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    rate_limit_max_requests: int = RATE_LIMIT_MAX_REQUESTS
    rate_limit_window_seconds: int = RATE_LIMIT_WINDOW_SECONDS
    _rate_limits: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def health_payload(self, *, schedule_count: int) -> dict[str, Any]:
        uptime = datetime.now(timezone.utc) - self.started_at
        return {
            "status": "ok",
            "service": "schedules-api",
            "version": self.version,
            "started_at": self.started_at.isoformat(),
            "uptime_seconds": round(uptime.total_seconds(), 3),
            "uptime": str(uptime).split(".", 1)[0],
            "schedules": schedule_count,
            "timestamp": _utc_now(),
        }

    def authenticate(self, headers: Any) -> tuple[bool, dict[str, Any] | None]:
        provided = headers.get(API_KEY_HEADER)
        if provided is None:
            return False, {
                "status": HTTPStatus.UNAUTHORIZED,
                "code": "missing_api_key",
                "message": f"Missing required header: {API_KEY_HEADER}",
            }
        if provided != self.api_key:
            return False, {
                "status": HTTPStatus.FORBIDDEN,
                "code": "invalid_api_key",
                "message": "Invalid API key",
            }
        return True, None

    def check_rate_limit(self, ip: str) -> tuple[bool, int | None]:
        now = time.monotonic()
        with self._lock:
            window = self._rate_limits[ip]
            cutoff = now - self.rate_limit_window_seconds
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= self.rate_limit_max_requests:
                retry_after = max(1, math.ceil(self.rate_limit_window_seconds - (now - window[0])))
                return False, retry_after
            window.append(now)
            return True, None

    def log_request(self, record: dict[str, Any]) -> None:
        self.request_log_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with self._lock:
            with self.request_log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


class ScheduleStore:
    """In-memory schedule registry backed by the demo script's files."""

    def __init__(
        self,
        *,
        repo_root: Path = REPO_ROOT,
        demo_module: Any | None = None,
        log_path: Path = DEFAULT_LOG_PATH,
        brief_path: Path = DEFAULT_BRIEF_PATH,
        heartbeat_path: Path = DEFAULT_HEARTBEAT_PATH,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.meta_root = self.repo_root.parent / "meta"
        self.demo_path = self.meta_root / "scheduled_demo.py"
        self.log_path = Path(log_path)
        self.brief_path = Path(brief_path)
        self.heartbeat_path = Path(heartbeat_path)
        self.demo_module = demo_module if demo_module is not None else load_scheduled_demo_module(self.demo_path)
        self.lock = threading.RLock()
        self.definitions = {
            "brief": ScheduleDefinition(
                name="brief",
                description="Build a local inbox and team-status brief, then persist a snapshot.",
                command="python scheduled_demo.py --task brief",
                task="brief",
            ),
            "log": ScheduleDefinition(
                name="log",
                description="Append a schedule evidence line and heartbeat record without generating a brief snapshot.",
                command="python scheduled_demo.py --task log",
                task="log",
            ),
        }
        self._logs: dict[str, list[dict[str, Any]]] = {
            name: self._load_log_entries(name) for name in self.definitions
        }
        self._runtime_state: dict[str, dict[str, Any]] = {
            name: {
                "status": "stopped",
                "running": False,
                "last_run_at": self._logs[name][-1]["timestamp"] if self._logs[name] else None,
                "run_count": len(self._logs[name]),
                "last_result": None,
            }
            for name in self.definitions
        }
        self._last_brief_snapshot = self._load_json_if_exists(self.brief_path)

    def _load_json_if_exists(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return _read_json(path)

    def _load_log_entries(self, task: str) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        if not self.log_path.exists():
            return entries

        for raw_line in _read_text(self.log_path).splitlines():
            parsed = self._parse_log_line(raw_line)
            if parsed and parsed["task"] == task:
                entries.append(parsed)
        return entries

    @staticmethod
    def _parse_log_line(line: str) -> dict[str, Any] | None:
        match = LOG_LINE_RE.match(line.strip())
        if not match:
            return None
        payload = match.groupdict()
        payload["pid"] = int(payload["pid"])
        payload["detail"] = payload["detail"] or ""
        return payload

    def _schedule_or_404(self, name: str) -> ScheduleDefinition | None:
        return self.definitions.get(name)

    def list_schedules(self) -> dict[str, Any]:
        items = [self.get_schedule(name) for name in self.definitions]
        return {
            "items": [
                {
                    "name": item["name"],
                    "description": item["description"],
                    "command": item["command"],
                    "status": item["status"],
                    "running": item["running"],
                    "run_count": item["run_count"],
                    "last_run_at": item["last_run_at"],
                }
                for item in items
            ],
            "count": len(items),
        }

    def get_schedule(self, name: str) -> dict[str, Any]:
        definition = self._schedule_or_404(name)
        if definition is None:
            raise KeyError(name)

        state = self._runtime_state[name]
        logs = self._logs[name]
        last_log = logs[-1] if logs else None
        details = {
            "name": definition.name,
            "description": definition.description,
            "command": definition.command,
            "source_script": str(self.demo_path),
            "status": state["status"],
            "running": state["running"],
            "run_count": state["run_count"],
            "last_run_at": state["last_run_at"],
            "recent_logs": logs[-5:],
            "last_log": last_log,
            "paths": {
                "log": str(self.log_path),
                "brief": str(self.brief_path),
                "heartbeat": str(self.heartbeat_path),
            },
        }
        if name == "brief" and self._last_brief_snapshot:
            details["latest_snapshot"] = self._last_brief_snapshot
        return details

    def get_log_entries(self, name: str) -> dict[str, Any]:
        self._schedule_or_404(name) or (_ for _ in ()).throw(KeyError(name))
        return {"name": name, "count": len(self._logs[name]), "entries": list(self._logs[name])}

    def get_status(self, name: str) -> dict[str, Any]:
        self._schedule_or_404(name) or (_ for _ in ()).throw(KeyError(name))
        state = self._runtime_state[name]
        return {
            "name": name,
            "status": state["status"],
            "running": state["running"],
            "run_count": state["run_count"],
            "last_run_at": state["last_run_at"],
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "schedules-api",
            "port": DEFAULT_PORT,
            "schedules": len(self.definitions),
            "timestamp": _utc_now(),
        }

    def run_schedule(self, name: str, *, source: str = "api") -> dict[str, Any]:
        definition = self._schedule_or_404(name)
        if definition is None:
            raise KeyError(name)

        with self.lock:
            state = self._runtime_state[name]
            state["running"] = True
            state["status"] = "running"
            try:
                if definition.task == "brief":
                    result = self._run_brief(source=source)
                else:
                    result = self._run_log(source=source)

                parsed_line = self._parse_log_line(result["log_line"])
                if parsed_line is None:
                    parsed_line = {
                        "timestamp": result.get("timestamp", _utc_now()),
                        "task": definition.task,
                        "source": source,
                        "host": result.get("host", "localhost"),
                        "user": result.get("user", "api"),
                        "pid": int(result.get("pid", 0)),
                        "detail": result.get("detail", ""),
                    }
                self._logs[name].append(parsed_line)
                self._runtime_state[name] = {
                    "status": "stopped",
                    "running": False,
                    "last_run_at": parsed_line["timestamp"],
                    "run_count": len(self._logs[name]),
                    "last_result": result,
                }
                if definition.task == "brief" and result.get("brief"):
                    self._last_brief_snapshot = result["brief"]
                return {
                    "name": name,
                    "status": "stopped",
                    "running": False,
                    "triggered": True,
                    "run_count": len(self._logs[name]),
                    "last_run_at": parsed_line["timestamp"],
                    "result": result,
                }
            except Exception:
                self._runtime_state[name]["running"] = False
                self._runtime_state[name]["status"] = "stopped"
                raise

    def _run_brief(self, *, source: str) -> dict[str, Any]:
        demo = self.demo_module
        if demo is not None and all(
            hasattr(demo, attr)
            for attr in ("build_brief", "write_brief_snapshot", "append_demo_line", "write_heartbeat_state")
        ):
            brief = demo.build_brief(source)
            snapshot_path = demo.write_brief_snapshot(brief)
            detail = brief.get("summary", "")
            log_line = demo.append_demo_line(source, "brief", detail)
            heartbeat = demo.write_heartbeat_state(source, "brief", detail or "task=brief")
            return {
                "brief": brief,
                "snapshot_path": str(snapshot_path),
                "log_line": log_line,
                "heartbeat": heartbeat,
                "detail": detail,
            }

        brief = {
            "timestamp": _utc_now(),
            "source": source,
            "task": "brief",
            "summary": "fallback brief generated by schedules_api",
        }
        self.brief_path.parent.mkdir(parents=True, exist_ok=True)
        self.brief_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
        log_line = (
            f"{brief['timestamp']} scheduled-demo task=brief source={source} host=localhost "
            f"user=api pid=0 detail={brief['summary']}"
        )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(log_line + "\n")
        return {
            "brief": brief,
            "snapshot_path": str(self.brief_path),
            "log_line": log_line,
            "heartbeat": {"status": "ok", "task": "brief"},
            "detail": brief["summary"],
        }

    def _run_log(self, *, source: str) -> dict[str, Any]:
        demo = self.demo_module
        if demo is not None and all(
            hasattr(demo, attr) for attr in ("append_demo_line", "write_heartbeat_state")
        ):
            log_line = demo.append_demo_line(source, "log", "")
            heartbeat = demo.write_heartbeat_state(source, "log", "task=log")
            return {
                "log_line": log_line,
                "heartbeat": heartbeat,
                "detail": "",
            }

        timestamp = _utc_now()
        log_line = f"{timestamp} scheduled-demo task=log source={source} host=localhost user=api pid=0"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(log_line + "\n")
        return {
            "log_line": log_line,
            "heartbeat": {"status": "ok", "task": "log"},
            "detail": "",
        }


DEFAULT_STORE = ScheduleStore()


class SchedulesHTTPRequestHandler(BaseHTTPRequestHandler):
    store: ScheduleStore = DEFAULT_STORE
    protocol_version = "HTTP/1.1"
    server_version = f"SchedulesAPI/{API_VERSION}"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def send_response(self, code: int | HTTPStatus, message: str | None = None) -> None:
        self._response_status_code = int(code)
        super().send_response(code, message)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key")
        self.send_header("Access-Control-Max-Age", "86400")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        parsed = urlparse(self.path)
        started = time.perf_counter()
        self._reset_response_state()
        try:
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
        finally:
            self._log_request("OPTIONS", parsed.path, started)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        started = time.perf_counter()
        self._reset_response_state()
        try:
            self._dispatch_request("GET", parsed)
        except Exception:
            if self._response_status_code is None:
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "Internal server error", "internal_server_error")
        finally:
            self._log_request("GET", parsed.path, started)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        started = time.perf_counter()
        self._reset_response_state()
        try:
            self._dispatch_request("POST", parsed)
        except Exception:
            if self._response_status_code is None:
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "Internal server error", "internal_server_error")
        finally:
            self._log_request("POST", parsed.path, started)

    def _dispatch_request(self, method: str, parsed) -> None:
        route = [segment for segment in parsed.path.split("/") if segment]

        if parsed.path == f"{API_PREFIX}/health":
            if method != "GET":
                self._send_error_json(
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    "GET is required for health checks",
                    "method_not_allowed",
                    allow="GET",
                )
                return
            self._send_json(HTTPStatus.OK, self._health_payload())
            return

        if route[:2] != ["api", "schedules"]:
            self._send_error_json(HTTPStatus.NOT_FOUND, "Endpoint not found", "not_found")
            return

        if method == "POST" and len(route) == 4 and route[3] == "run":
            if not self._validate_json_body():
                return

        if method in {"GET", "POST"}:
            if not self._enforce_rate_limit():
                return
            if not self._require_api_key():
                return

        if method == "GET":
            self._handle_get(route)
            return

        if method == "POST":
            self._handle_post(route)
            return

        self._send_error_json(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed", "method_not_allowed")

    def _handle_get(self, route: list[str]) -> None:
        if len(route) == 2:
            self._send_json(HTTPStatus.OK, self.store.list_schedules())
            return

        if len(route) == 3:
            name = route[2]
            try:
                self._send_json(HTTPStatus.OK, self.store.get_schedule(name))
            except KeyError:
                self._send_error_json(HTTPStatus.NOT_FOUND, f"Unknown schedule '{name}'", "task_not_found")
            return

        if len(route) == 4:
            name, action = route[2], route[3]
            if action == "run":
                self._send_error_json(
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    "POST is required to run a schedule",
                    "method_not_allowed",
                    allow="POST",
                )
                return
            if action == "log":
                try:
                    self._send_json(HTTPStatus.OK, self.store.get_log_entries(name))
                except KeyError:
                    self._send_error_json(HTTPStatus.NOT_FOUND, f"Unknown schedule '{name}'", "task_not_found")
                return
            if action == "status":
                try:
                    self._send_json(HTTPStatus.OK, self.store.get_status(name))
                except KeyError:
                    self._send_error_json(HTTPStatus.NOT_FOUND, f"Unknown schedule '{name}'", "task_not_found")
                return

        self._send_error_json(HTTPStatus.NOT_FOUND, "Endpoint not found", "not_found")

    def _handle_post(self, route: list[str]) -> None:
        if len(route) == 4:
            name, action = route[2], route[3]
            if action == "run":
                try:
                    self._send_json(HTTPStatus.OK, self.store.run_schedule(name))
                except KeyError:
                    self._send_error_json(HTTPStatus.NOT_FOUND, f"Unknown schedule '{name}'", "task_not_found")
                return
            if action in {"log", "status"}:
                self._send_error_json(
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    f"GET is required for schedule {action} requests",
                    "method_not_allowed",
                    allow="GET",
                )
                return

        if len(route) == 3:
            self._send_error_json(
                HTTPStatus.METHOD_NOT_ALLOWED,
                "POST is only supported for manual schedule runs",
                "method_not_allowed",
                allow="GET",
            )
            return

        self._send_error_json(HTTPStatus.NOT_FOUND, "Endpoint not found", "not_found")

    def _context(self) -> APIContext:
        context = getattr(self.server, "app_context", None)
        if context is None:
            context = APIContext()
            setattr(self.server, "app_context", context)
        return context

    def _health_payload(self) -> dict[str, Any]:
        return self._context().health_payload(schedule_count=len(self.store.definitions))

    def _client_ip(self) -> str:
        return self.client_address[0] if self.client_address else "unknown"

    def _read_request_body(self) -> bytes:
        content_length = self.headers.get("Content-Length")
        if not content_length:
            return b""
        try:
            length = int(content_length)
        except ValueError:
            return b""
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _validate_json_body(self) -> bool:
        raw_body = self._read_request_body()
        if not raw_body:
            return True
        try:
            json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Request body contains invalid JSON", "invalid_json")
            return False
        return True

    def _reset_response_state(self) -> None:
        self._response_status_code = None
        self._response_error_code = None

    def _require_api_key(self) -> bool:
        ok, error = self._context().authenticate(self.headers)
        if ok:
            return True
        assert error is not None
        self._send_error_json(
            HTTPStatus(error["status"]),
            error["message"],
            error["code"],
        )
        return False

    def _enforce_rate_limit(self) -> bool:
        ok, retry_after = self._context().check_rate_limit(self._client_ip())
        if ok:
            return True
        headers = {"Retry-After": str(retry_after or 1)}
        self._send_error_json(
            HTTPStatus.TOO_MANY_REQUESTS,
            "Rate limit exceeded",
            "rate_limit_exceeded",
            headers=headers,
        )
        return False

    def _log_request(self, method: str, path: str, started_at: float) -> None:
        status = self._response_status_code if self._response_status_code is not None else int(
            HTTPStatus.INTERNAL_SERVER_ERROR
        )
        record = {
            "timestamp": _utc_now(),
            "method": method,
            "path": path,
            "status": status,
            "client_ip": self._client_ip(),
            "api_key_present": API_KEY_HEADER in self.headers,
            "error_code": self._response_error_code,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 3),
        }
        self._context().log_request(record)

    def _send_json(
        self,
        status: HTTPStatus,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        self._response_error_code = None
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(
        self,
        status: HTTPStatus,
        message: str,
        code: str,
        *,
        allow: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._response_error_code = code
        response_headers = dict(headers or {})
        if allow is not None:
            response_headers["Allow"] = allow
        payload = {
            "error": {
                "code": code,
                "message": message,
                "status": int(status),
            }
        }
        self._send_json(status, payload, headers=response_headers or None)


def create_server(
    host: str = "0.0.0.0",
    port: int = DEFAULT_PORT,
    *,
    store: ScheduleStore | None = None,
    api_key: str | None = None,
    request_log_path: Path | None = None,
    version: str = API_VERSION,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), SchedulesHTTPRequestHandler)
    SchedulesHTTPRequestHandler.store = store if store is not None else DEFAULT_STORE
    server.app_context = APIContext(
        api_key=api_key if api_key is not None else DEFAULT_API_KEY,
        request_log_path=request_log_path if request_log_path is not None else DEFAULT_REQUEST_LOG_PATH,
        version=version,
    )
    return server


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the schedules API server.")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="API key required via the X-API-Key header")
    parser.add_argument(
        "--request-log-path",
        default=str(DEFAULT_REQUEST_LOG_PATH),
        help="Path to the request log file",
    )
    args = parser.parse_args(argv)

    server = create_server(
        args.host,
        args.port,
        api_key=args.api_key,
        request_log_path=Path(args.request_log_path),
    )
    print(f"Schedules API listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
