from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "api"
for path in (REPO_ROOT, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import schedules_api as api  # noqa: E402
from imagegen.image_manager import ImageManager  # noqa: E402
from skills.skills_manager import Skill, SkillsManager  # noqa: E402
from storage.db import SQLiteStorage  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _build_demo_line(source: str, task: str, detail: str = "") -> str:
    suffix = f" detail={detail}" if detail else ""
    return (
        f"{_utc_now()} scheduled-demo task={task} source={source} host=integration user=qa pid=4242"
        f"{suffix}"
    )


def _build_default_demo_module(log_path: Path, brief_path: Path, heartbeat_path: Path) -> SimpleNamespace:
    def build_brief(source: str) -> dict[str, Any]:
        return {
            "timestamp": _utc_now(),
            "source": source,
            "task": "brief",
            "summary": f"brief generated from {source}",
        }

    def write_brief_snapshot(brief: dict[str, Any]) -> Path:
        brief_path.parent.mkdir(parents=True, exist_ok=True)
        brief_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
        return brief_path

    def append_demo_line(source: str, task: str, detail: str = "") -> str:
        line = _build_demo_line(source, task, detail)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return line

    def write_heartbeat_state(source: str, task: str, detail: str = "") -> dict[str, Any]:
        record = {
            "timestamp": _utc_now(),
            "status": "ok",
            "source": source,
            "task": task,
            "detail": detail,
        }
        heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        with heartbeat_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    return SimpleNamespace(
        build_brief=build_brief,
        write_brief_snapshot=write_brief_snapshot,
        append_demo_line=append_demo_line,
        write_heartbeat_state=write_heartbeat_state,
    )


def _build_workflow_demo_module(
    *,
    skills_manager: SkillsManager,
    skill_name: str,
    log_path: Path,
    brief_path: Path,
    heartbeat_path: Path,
) -> SimpleNamespace:
    def build_brief(source: str) -> dict[str, Any]:
        execution_result = skills_manager.execute(skill_name, source)
        summary = f"{skill_name} executed for {source}"
        return {
            "timestamp": _utc_now(),
            "source": source,
            "task": "brief",
            "summary": summary,
            "execution_result": execution_result,
        }

    def write_brief_snapshot(brief: dict[str, Any]) -> Path:
        brief_path.parent.mkdir(parents=True, exist_ok=True)
        brief_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
        return brief_path

    def append_demo_line(source: str, task: str, detail: str = "") -> str:
        line = _build_demo_line(source, task, detail)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return line

    def write_heartbeat_state(source: str, task: str, detail: str = "") -> dict[str, Any]:
        record = {
            "timestamp": _utc_now(),
            "status": "ok",
            "source": source,
            "task": task,
            "detail": detail,
        }
        heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        with heartbeat_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    return SimpleNamespace(
        build_brief=build_brief,
        write_brief_snapshot=write_brief_snapshot,
        append_demo_line=append_demo_line,
        write_heartbeat_state=write_heartbeat_state,
    )


def _add_custom_schedule(store: api.ScheduleStore, name: str, description: str, task: str = "brief") -> None:
    store.definitions[name] = api.ScheduleDefinition(
        name=name,
        description=description,
        command=f"python scheduled_demo.py --task {task}",
        task=task,
    )
    store._logs[name] = []  # noqa: SLF001 - test setup seeds an in-memory schedule
    store._runtime_state[name] = {
        "status": "stopped",
        "running": False,
        "last_run_at": None,
        "run_count": 0,
        "last_result": None,
    }


@dataclass(slots=True)
class ApiHarness:
    tempdir: tempfile.TemporaryDirectory[str]
    root: Path
    repo_root: Path
    storage: SQLiteStorage
    skills_manager: SkillsManager
    channels_manager: Any
    image_manager: ImageManager
    store: api.ScheduleStore
    server: Any
    thread: threading.Thread
    api_key: str
    request_log_path: Path
    log_path: Path
    brief_path: Path
    heartbeat_path: Path

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "ApiHarness":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        api.SchedulesHTTPRequestHandler.store = api.DEFAULT_STORE
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.storage.close()
        self.tempdir.cleanup()

    def auth_headers(self, api_key: str | None = None) -> dict[str, str]:
        return {api.API_KEY_HEADER: api_key or self.api_key}

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | dict[str, Any] | list[Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], Any]:
        if isinstance(body, (dict, list)):
            body_bytes = json.dumps(body).encode("utf-8")
        elif isinstance(body, bytes):
            body_bytes = body
        else:
            body_bytes = None

        request_headers = {"Host": "localhost"}
        if headers:
            request_headers.update(headers)
        if body_bytes is not None:
            request_headers.setdefault("Content-Type", "application/json")

        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(method, path, body=body_bytes, headers=request_headers)
            response = connection.getresponse()
            raw_body = response.read()
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else None
            return response.status, {key: value for key, value in response.headers.items()}, payload
        finally:
            connection.close()


def build_harness(*, rate_limit_max_requests: int | None = None) -> ApiHarness:
    tempdir = tempfile.TemporaryDirectory(prefix="integration-tests-")
    root = Path(tempdir.name)
    repo_root = root / "company"
    repo_root.mkdir(parents=True, exist_ok=True)

    meta_dir = root / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    log_path = meta_dir / ".scheduled-demo.log"
    request_log_path = meta_dir / ".schedules-api-requests.log"
    brief_path = meta_dir / ".scheduled-demo-brief.json"
    heartbeat_path = meta_dir / "heartbeat-step-health.jsonl"
    storage = SQLiteStorage(meta_dir / "integration.sqlite3")
    skills_manager = SkillsManager()
    channels_manager = api.ChannelsManager(timeout=1.0)
    image_manager = ImageManager()
    channels_manager._post_json = mock.Mock(return_value={"status": 200, "body": {"ok": True}})

    default_demo_module = _build_default_demo_module(log_path, brief_path, heartbeat_path)
    store = api.ScheduleStore(
        repo_root=repo_root,
        demo_module=default_demo_module,
        log_path=log_path,
        brief_path=brief_path,
        heartbeat_path=heartbeat_path,
    )

    server = api.create_server(
        "127.0.0.1",
        0,
        store=store,
        api_key="test-api-key",
        request_log_path=request_log_path,
        version="9.9.9-test",
    )
    server.app_context.channels_manager = channels_manager
    server.app_context.image_manager = image_manager
    if rate_limit_max_requests is not None:
        server.app_context.rate_limit_max_requests = rate_limit_max_requests

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return ApiHarness(
        tempdir=tempdir,
        root=root,
        repo_root=repo_root,
        storage=storage,
        skills_manager=skills_manager,
        channels_manager=channels_manager,
        image_manager=image_manager,
        store=store,
        server=server,
        thread=thread,
        api_key="test-api-key",
        request_log_path=request_log_path,
        log_path=log_path,
        brief_path=brief_path,
        heartbeat_path=heartbeat_path,
    )


def test_skill_registration_enable_execute_and_db_verification() -> None:
    with build_harness() as harness:
        skill = Skill(
            name="relay_to_ops",
            description="Relay a status update to the operations channel",
            version="1.0.0",
            enabled=False,
            config={"channel": "ops"},
        )
        harness.storage.create_skill(
            name=skill.name,
            description=skill.description,
            version=skill.version,
            enabled=skill.enabled,
            config=skill.config,
        )

        def execute(source: str) -> dict[str, Any]:
            return {"source": source, "status": "ok", "channel": skill.config["channel"]}

        harness.skills_manager.register(skill, execute)
        harness.skills_manager.enable(skill.name)
        harness.storage.update_skill(skill.name, enabled=True)

        result = harness.skills_manager.execute(skill.name, "daily-summary")
        stored_skill = harness.storage.get_skill(skill.name)

        assert result == {"source": "daily-summary", "status": "ok", "channel": "ops"}
        assert stored_skill == {
            "name": "relay_to_ops",
            "description": "Relay a status update to the operations channel",
            "version": "1.0.0",
            "enabled": True,
            "config": {"channel": "ops"},
        }
        assert harness.skills_manager.execution_log[-1]["skill"] == skill.name
        assert harness.skills_manager.execution_log[-1]["status"] == "success"
        assert harness.storage.list_skills() == [stored_skill]


def test_register_channel_send_message_and_verify_logged() -> None:
    with build_harness() as harness:
        channel_payload = {
            "name": "ops",
            "type": "slack",
            "webhook_url": "https://example.com/ops",
            "enabled": True,
        }

        status, _, payload = harness.request("POST", "/api/channels", body=channel_payload, headers=harness.auth_headers())
        assert status == 201
        assert payload == channel_payload

        harness.storage.create_channel(**channel_payload)

        status, _, send_payload = harness.request(
            "POST",
            "/api/channels/ops/send",
            body={"message": "Deployment complete"},
            headers=harness.auth_headers(),
        )
        assert status == 200
        assert send_payload["channel"] == "ops"
        assert send_payload["payload"] == {"text": "Deployment complete"}
        assert harness.channels_manager.message_log[-1]["message"] == "Deployment complete"
        assert harness.channels_manager.message_log[-1]["payload"] == {"text": "Deployment complete"}
        assert harness.storage.get_channel("ops") == channel_payload


def test_generate_image_edit_image_list_history_and_verify() -> None:
    with build_harness() as harness:
        generate_body = {
            "prompt": "A neon city skyline at sunset",
            "size": "1024x1024",
            "style": "cinematic",
            "format": "png",
        }
        status, _, generated = harness.request(
            "POST",
            "/api/images/generate",
            body=generate_body,
            headers=harness.auth_headers(),
        )
        assert status == 201
        assert generated["operation"] == "generate"
        assert generated["prompt"] == generate_body["prompt"]
        assert generated["image_data"].startswith("mock-image://")

        harness.storage.create_image(
            prompt=generated["prompt"],
            size=generated["size"],
            style=generated["style"],
            format=generated["format"],
            image_id=generated["image_id"],
            created_at=generated["created_at"],
        )

        edit_body = {"prompt": "Add a flying train and glowing clouds"}
        status, _, edited = harness.request(
            "POST",
            f"/api/images/{generated['image_id']}/edit",
            body=edit_body,
            headers=harness.auth_headers(),
        )
        assert status == 201
        assert edited["operation"] == "edit"
        assert edited["source_image_id"] == generated["image_id"]
        assert edited["edit_prompt"] == edit_body["prompt"]

        harness.storage.create_image(
            prompt=edited["prompt"],
            size=edited["size"],
            style=edited["style"],
            format=edited["format"],
            image_id=edited["image_id"],
            created_at=edited["created_at"],
        )

        status, _, history = harness.request("GET", "/api/images", headers=harness.auth_headers())
        assert status == 200
        assert history["count"] == 2
        assert [item["operation"] for item in history["items"]] == ["generate", "edit"]
        assert history["items"][1]["source_image_id"] == generated["image_id"]
        assert len(harness.image_manager.list_history()) == 2
        assert harness.storage.get_image(generated["image_id"]) is not None
        assert harness.storage.get_image(edited["image_id"]) is not None


def test_create_schedule_run_log_and_verify() -> None:
    with build_harness() as harness:
        _add_custom_schedule(harness.store, "report", "Generate the daily team report")

        status, _, payload = harness.request("POST", "/api/schedules/report/run", headers=harness.auth_headers())
        assert status == 200
        assert payload["name"] == "report"
        assert payload["triggered"] is True
        assert payload["result"]["brief"]["summary"] == "brief generated from api"

        status, _, log_payload = harness.request("GET", "/api/schedules/report/log", headers=harness.auth_headers())
        assert status == 200
        assert log_payload["count"] == 1
        assert log_payload["entries"][0]["task"] == "brief"
        assert log_payload["entries"][0]["source"] == "api"
        assert "brief generated from api" in log_payload["entries"][0]["detail"]
        assert harness.store.get_status("report")["run_count"] == 1
        assert harness.store.get_schedule("report")["last_log"]["detail"] == "brief generated from api"
        assert harness.log_path.exists()
        assert harness.brief_path.exists()


def test_full_workflow_schedule_triggers_skill_that_sends_to_channel() -> None:
    with build_harness() as harness:
        channel_payload = {
            "name": "ops",
            "type": "slack",
            "webhook_url": "https://example.com/ops",
            "enabled": True,
        }
        status, _, _ = harness.request("POST", "/api/channels", body=channel_payload, headers=harness.auth_headers())
        assert status == 201
        harness.storage.create_channel(**channel_payload)

        skill = Skill(
            name="relay_workflow",
            description="Relay a schedule brief to the operations channel",
            version="1.0.0",
            enabled=False,
            config={"channel": "ops"},
        )
        harness.storage.create_skill(
            name=skill.name,
            description=skill.description,
            version=skill.version,
            enabled=skill.enabled,
            config=skill.config,
        )

        def execute(source: str) -> dict[str, Any]:
            message = f"workflow triggered by {source}"
            receipt = harness.channels_manager.send_message(message, skill.config["channel"])
            return {"message": message, "receipt": receipt}

        harness.skills_manager.register(skill, execute)
        harness.skills_manager.enable(skill.name)
        harness.storage.update_skill(skill.name, enabled=True)

        harness.store.demo_module = _build_workflow_demo_module(
            skills_manager=harness.skills_manager,
            skill_name=skill.name,
            log_path=harness.log_path,
            brief_path=harness.brief_path,
            heartbeat_path=harness.heartbeat_path,
        )

        payload = harness.store.run_schedule("brief")
        assert payload["name"] == "brief"
        assert payload["triggered"] is True
        assert payload["result"]["brief"]["summary"] == "relay_workflow executed for api"

        log_payload = harness.request("GET", "/api/schedules/brief/log", headers=harness.auth_headers())[2]
        assert log_payload["count"] == 1
        assert log_payload["entries"][0]["task"] == "brief"
        assert "relay_workflow executed for api" in log_payload["entries"][0]["detail"]
        assert harness.skills_manager.execution_log[-1]["skill"] == skill.name
        assert harness.skills_manager.execution_log[-1]["status"] == "success"
        assert harness.channels_manager.message_log[-1]["channel"] == "ops"
        assert harness.channels_manager.message_log[-1]["message"] == "workflow triggered by api"
        assert harness.storage.get_skill(skill.name)["enabled"] is True
        assert harness.storage.get_channel("ops")["enabled"] is True
        assert harness.store.get_status("brief")["run_count"] == 1


def test_health_check_returns_all_systems_healthy() -> None:
    with build_harness() as harness:
        status, headers, payload = harness.request("GET", "/api/health")
        assert status == 200
        assert payload["status"] == "ok"
        assert payload["service"] == "schedules-api"
        assert payload["version"] == "9.9.9-test"
        assert payload["schedules"] == 2
        assert "started_at" in payload
        assert headers["Access-Control-Allow-Origin"] == "*"


def test_rate_limiting_works_across_multiple_endpoints() -> None:
    with build_harness(rate_limit_max_requests=4) as harness:
        assert harness.request("GET", "/api/schedules", headers=harness.auth_headers())[0] == 200
        assert harness.request("GET", "/api/channels", headers=harness.auth_headers())[0] == 200
        assert harness.request("GET", "/api/images", headers=harness.auth_headers())[0] == 200
        assert harness.request(
            "POST",
            "/api/images/generate",
            body={"prompt": "A rate limited image"},
            headers=harness.auth_headers(),
        )[0] == 201

        status, headers, payload = harness.request("GET", "/api/schedules/brief", headers=harness.auth_headers())
        assert status == 429
        assert payload["error"]["code"] == "rate_limit_exceeded"
        assert payload["error"]["status"] == 429
        assert "Retry-After" in headers


def test_invalid_api_key_rejected_on_all_authenticated_endpoints() -> None:
    with build_harness(rate_limit_max_requests=100) as harness:
        invalid_headers = harness.auth_headers("wrong-key")
        cases = [
            ("GET", "/api/schedules", None),
            ("GET", "/api/schedules/brief", None),
            ("GET", "/api/schedules/brief/log", None),
            ("GET", "/api/schedules/brief/status", None),
            ("POST", "/api/schedules/brief/run", {}),
            ("GET", "/api/channels", None),
            (
                "POST",
                "/api/channels",
                {"name": "ops", "type": "slack", "webhook_url": "https://example.com/ops", "enabled": True},
            ),
            ("GET", "/api/channels/ops", None),
            ("POST", "/api/channels/ops/send", {"message": "hello"}),
            ("POST", "/api/channels/broadcast", {"message": "hello"}),
            ("DELETE", "/api/channels/ops", None),
            ("GET", "/api/images", None),
            (
                "POST",
                "/api/images/generate",
                {"prompt": "A sunset over the mountains", "size": "1024x1024"},
            ),
            ("GET", "/api/images/missing-image", None),
            ("POST", "/api/images/missing-image/edit", {"prompt": "Add a moon"}),
        ]

        for method, path, body in cases:
            status, _, payload = harness.request(method, path, body=body, headers=invalid_headers)
            assert status == 403, f"{method} {path} returned {status}: {payload}"
            assert payload["error"]["code"] == "invalid_api_key"
            assert payload["error"]["status"] == 403
