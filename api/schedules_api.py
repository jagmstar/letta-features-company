from __future__ import annotations

import importlib.util
import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_PORT = 8290
API_PREFIX = "/api"
REPO_ROOT = Path(__file__).resolve().parents[1]
META_ROOT = REPO_ROOT.parent / "meta"
DEFAULT_DEMO_PATH = META_ROOT / "scheduled_demo.py"
DEFAULT_LOG_PATH = META_ROOT / ".scheduled-demo.log"
DEFAULT_BRIEF_PATH = META_ROOT / ".scheduled-demo-brief.json"
DEFAULT_HEARTBEAT_PATH = META_ROOT / "heartbeat-step-health.jsonl"

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
    server_version = "SchedulesAPI/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = [segment for segment in parsed.path.split("/") if segment]

        if parsed.path == f"{API_PREFIX}/health":
            self._send_json(HTTPStatus.OK, self.store.health())
            return

        if route[:2] != ["api", "schedules"]:
            self._send_error_json(HTTPStatus.NOT_FOUND, "Endpoint not found", "not_found")
            return

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

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route = [segment for segment in parsed.path.split("/") if segment]

        if route[:2] != ["api", "schedules"]:
            if parsed.path == f"{API_PREFIX}/health":
                self._send_error_json(
                    HTTPStatus.METHOD_NOT_ALLOWED,
                    "GET is required for health checks",
                    "method_not_allowed",
                    allow="GET",
                )
                return
            self._send_error_json(HTTPStatus.NOT_FOUND, "Endpoint not found", "not_found")
            return

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
                allow="GET, POST",
            )
            return

        self._send_error_json(HTTPStatus.NOT_FOUND, "Endpoint not found", "not_found")

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
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
    ) -> None:
        headers = {"Allow": allow} if allow else None
        self._send_json(status, {"error": {"code": code, "message": message}}, headers=headers)


def create_server(host: str = "0.0.0.0", port: int = DEFAULT_PORT, *, store: ScheduleStore | None = None) -> ThreadingHTTPServer:
    SchedulesHTTPRequestHandler.store = store if store is not None else DEFAULT_STORE
    return ThreadingHTTPServer((host, port), SchedulesHTTPRequestHandler)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the schedules API server.")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind")
    args = parser.parse_args(argv)

    server = create_server(args.host, args.port)
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
