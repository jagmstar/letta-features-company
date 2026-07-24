from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
MONITORING_DIR = Path(__file__).resolve().parent
API_PATH = BASE_DIR / "api" / "schedules_api.py"
DASHBOARD_PATH = BASE_DIR / "dashboard" / "generate_dashboard.py"
SCHEDULER_PATH = BASE_DIR / "production_scheduler.py"
DEFAULT_LOG_PATH = MONITORING_DIR / "health.log"

INFO = "INFO"
WARNING = "WARNING"
CRITICAL = "CRITICAL"
ALERT_LEVELS = (INFO, WARNING, CRITICAL)
ALERT_PRIORITY = {INFO: 1, WARNING: 2, CRITICAL: 3}

_MODULE_STARTED_MONOTONIC = time.monotonic()
_MODULE_STARTED_AT = datetime.now(timezone.utc)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_module_from_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(slots=True)
class AlertRecord:
    id: str
    level: str
    message: str
    component: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now)
    resolved_at: str | None = None
    active: bool = True
    priority: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "level": self.level,
            "message": self.message,
            "component": self.component,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "active": self.active,
            "priority": self.priority,
        }


class HealthCheck:
    def __init__(self, *, log_path: str | Path = DEFAULT_LOG_PATH) -> None:
        self.log_path = Path(log_path)
        self._lock = threading.RLock()

    def _log_health_check(self, check_name: str, payload: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": _utc_now(),
            "check": check_name,
            "status": payload.get("status", "unknown"),
            "payload": payload,
        }
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def check_api_health(self) -> dict[str, Any]:
        try:
            module = _load_module_from_path("monitoring_schedules_api", API_PATH)
            if hasattr(module, "DEFAULT_STORE") and hasattr(module.DEFAULT_STORE, "health"):
                payload = module.DEFAULT_STORE.health()
            elif hasattr(module, "APIContext"):
                default_store = getattr(module, "DEFAULT_STORE", None)
                schedule_count = len(getattr(default_store, "definitions", {})) if default_store is not None else 0
                payload = module.APIContext().health_payload(schedule_count=schedule_count)
            else:
                payload = {"status": "warning", "service": "schedules-api", "detail": "API health probe unavailable"}
        except Exception as exc:  # pragma: no cover - defensive path
            payload = {"status": CRITICAL.lower(), "service": "schedules-api", "error": str(exc)}

        result = {
            "component": "api",
            "checked_at": _utc_now(),
            "status": str(payload.get("status", "unknown")).lower(),
            "details": payload,
        }
        self._log_health_check("api", result)
        return result

    def check_database(self, database_path: str | Path | None = None) -> dict[str, Any]:
        db_path = Path(database_path) if database_path is not None else None
        try:
            if db_path is None:
                with sqlite3.connect(":memory:") as connection:
                    connection.execute("SELECT 1")
                    connection.commit()
                details = {"engine": "sqlite", "database": ":memory:", "connected": True}
            else:
                db_path.parent.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(str(db_path)) as connection:
                    connection.execute("SELECT 1")
                    connection.commit()
                details = {"engine": "sqlite", "database": str(db_path), "connected": True}
            status = "ok"
        except Exception as exc:  # pragma: no cover - defensive path
            details = {"engine": "sqlite", "connected": False, "error": str(exc)}
            status = CRITICAL.lower()

        result = {
            "component": "database",
            "checked_at": _utc_now(),
            "status": status,
            "details": details,
        }
        self._log_health_check("database", result)
        return result

    def check_scheduler(self) -> dict[str, Any]:
        try:
            module = _load_module_from_path("monitoring_production_scheduler", SCHEDULER_PATH)
            config_path = Path(getattr(module, "CONFIG_PATH", BASE_DIR / "meta" / "scheduler_config.json"))
            scheduler_cls = getattr(module, "Scheduler", None)
            if scheduler_cls is None:
                raise RuntimeError("Scheduler class is not available")

            if config_path.exists():
                scheduler = scheduler_cls.from_config(config_path, dry_run=True)
                details = {**scheduler.summarize(), "healthy": True}
                status = "ok"
            else:
                details = {
                    "config_path": str(config_path),
                    "healthy": False,
                    "reason": "scheduler configuration file is missing",
                }
                status = WARNING.lower()
        except Exception as exc:  # pragma: no cover - defensive path
            details = {"healthy": False, "error": str(exc)}
            status = CRITICAL.lower()

        result = {
            "component": "scheduler",
            "checked_at": _utc_now(),
            "status": status,
            "details": details,
        }
        self._log_health_check("scheduler", result)
        return result

    def check_dashboard(self) -> dict[str, Any]:
        try:
            module = _load_module_from_path("monitoring_generate_dashboard", DASHBOARD_PATH)
            build_dashboard = getattr(module, "build_dashboard", None)
            if not callable(build_dashboard):
                raise RuntimeError("build_dashboard() is not available")

            brief_path = Path(getattr(module, "BRIEF_PATH", BASE_DIR / "meta" / ".scheduled-demo-brief.json"))
            if not brief_path.exists():
                details = {
                    "dashboard_path": str(DASHBOARD_PATH),
                    "brief_path": str(brief_path),
                    "healthy": False,
                    "reason": "brief snapshot is missing",
                }
                status = WARNING.lower()
            else:
                output = build_dashboard()
                details = {
                    "dashboard_path": str(DASHBOARD_PATH),
                    "output_length": len(output),
                    "contains_html": "<html" in output.lower(),
                    "healthy": "<html" in output.lower(),
                }
                status = "ok" if details["contains_html"] else WARNING.lower()
        except Exception as exc:  # pragma: no cover - defensive path
            details = {"healthy": False, "error": str(exc)}
            status = CRITICAL.lower()

        result = {
            "component": "dashboard",
            "checked_at": _utc_now(),
            "status": status,
            "details": details,
        }
        self._log_health_check("dashboard", result)
        return result


class SystemMonitor:
    def __init__(self, *, base_dir: str | Path = BASE_DIR) -> None:
        self.base_dir = Path(base_dir)

    def get_cpu_usage(self) -> dict[str, Any]:
        try:
            import psutil  # type: ignore

            value = float(psutil.cpu_percent(interval=0.0))
            source = "psutil"
        except Exception:
            try:
                load_average = os.getloadavg()[0]
                cpu_count = max(os.cpu_count() or 1, 1)
                value = min((load_average / cpu_count) * 100.0, 100.0)
                source = "loadavg"
            except Exception:
                value = 0.0
                source = "unavailable"
        return {"metric": "cpu", "value": round(value, 2), "unit": "percent", "source": source}

    def get_memory_usage(self) -> dict[str, Any]:
        try:
            import psutil  # type: ignore

            value = float(psutil.virtual_memory().percent)
            source = "psutil"
        except Exception:
            try:
                page_size = os.sysconf("SC_PAGE_SIZE")  # type: ignore[arg-type]
                phys_pages = os.sysconf("SC_PHYS_PAGES")  # type: ignore[arg-type]
                avail_pages = os.sysconf("SC_AVPHYS_PAGES")  # type: ignore[arg-type]
                total = page_size * phys_pages
                available = page_size * avail_pages
                used = max(total - available, 0)
                value = (used / total) * 100.0 if total else 0.0
                source = "sysconf"
            except Exception:
                value = 0.0
                source = "unavailable"
        return {"metric": "memory", "value": round(value, 2), "unit": "percent", "source": source}

    def get_disk_usage(self) -> dict[str, Any]:
        usage = shutil.disk_usage(str(self.base_dir))
        percent = (usage.used / usage.total * 100.0) if usage.total else 0.0
        return {
            "metric": "disk",
            "path": str(self.base_dir),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "value": round(percent, 2),
            "unit": "percent",
            "source": "shutil",
        }

    def get_uptime(self) -> dict[str, Any]:
        try:
            import psutil  # type: ignore

            boot_time = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)
            delta = datetime.now(timezone.utc) - boot_time
            source = "psutil"
        except Exception:
            delta = datetime.now(timezone.utc) - _MODULE_STARTED_AT
            source = "module"
        seconds = max(delta.total_seconds(), 0.0)
        return {
            "metric": "uptime",
            "seconds": round(seconds, 2),
            "human_readable": _format_duration(seconds),
            "source": source,
        }


class AlertManager:
    def __init__(self, *, log_path: str | Path = DEFAULT_LOG_PATH) -> None:
        self.log_path = Path(log_path)
        self._lock = threading.RLock()
        self._alerts: list[AlertRecord] = []
        self._resolved: list[AlertRecord] = []

    def _write_log(self, action: str, alert: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {"timestamp": _utc_now(), "action": action, "alert": alert}
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def raise_alert(
        self,
        level: str,
        message: str,
        *,
        component: str | None = None,
        **metadata: Any,
    ) -> dict[str, Any]:
        normalized_level = level.upper()
        if normalized_level not in ALERT_LEVELS:
            raise ValueError(f"Unsupported alert level: {level}")

        alert = AlertRecord(
            id=str(uuid.uuid4()),
            level=normalized_level,
            message=message,
            component=component,
            metadata=dict(metadata),
            priority=ALERT_PRIORITY[normalized_level],
        )
        with self._lock:
            self._alerts.append(alert)
        payload = alert.to_dict()
        self._write_log("raise", payload)
        return payload

    def list_alerts(self, *, include_resolved: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            alerts = list(self._alerts)
            if include_resolved:
                alerts.extend(self._resolved)
        alerts.sort(key=lambda alert: (alert.priority, alert.created_at), reverse=True)
        return [alert.to_dict() for alert in alerts]

    def resolve_alert(self, alert_id: str) -> dict[str, Any] | None:
        with self._lock:
            for index, alert in enumerate(self._alerts):
                if alert.id == alert_id:
                    alert.active = False
                    alert.resolved_at = _utc_now()
                    resolved_alert = self._alerts.pop(index)
                    self._resolved.append(resolved_alert)
                    payload = resolved_alert.to_dict()
                    self._write_log("resolve", payload)
                    return payload
        return None


def _format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, remaining = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {remaining}s" if remaining else f"{minutes}m"
    hours, remaining_minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {remaining_minutes}m" if remaining_minutes else f"{hours}h"
    days, remaining_hours = divmod(hours, 24)
    return f"{days}d {remaining_hours}h" if remaining_hours else f"{days}d"


__all__ = [
    "ALERT_LEVELS",
    "ALERT_PRIORITY",
    "AlertManager",
    "CRITICAL",
    "DEFAULT_LOG_PATH",
    "HealthCheck",
    "INFO",
    "SystemMonitor",
    "WARNING",
]
