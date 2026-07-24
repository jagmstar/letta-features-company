from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from monitoring.health_monitor import AlertManager, HealthCheck, CRITICAL, INFO  # noqa: E402


def test_check_api_health_returns_status(tmp_path: Path) -> None:
    checker = HealthCheck(log_path=tmp_path / "health.log")

    result = checker.check_api_health()

    assert result["status"] == "ok"
    assert result["component"] == "api"
    assert (tmp_path / "health.log").exists()


def test_check_database_returns_status(tmp_path: Path) -> None:
    checker = HealthCheck(log_path=tmp_path / "health.log")

    result = checker.check_database()

    assert result["status"] == "ok"
    assert result["component"] == "database"
    assert result["details"]["connected"] is True


def test_raise_alert_creates_alert(tmp_path: Path) -> None:
    manager = AlertManager(log_path=tmp_path / "health.log")

    alert = manager.raise_alert("WARNING", "Queue lag detected", component="scheduler", lag_seconds=42)

    assert alert["level"] == "WARNING"
    assert alert["active"] is True
    assert alert["component"] == "scheduler"
    assert alert["metadata"]["lag_seconds"] == 42
    assert alert["priority"] == 2


def test_list_alerts_returns_all(tmp_path: Path) -> None:
    manager = AlertManager(log_path=tmp_path / "health.log")
    first = manager.raise_alert("INFO", "Informational alert")
    second = manager.raise_alert("WARNING", "Warning alert")

    alerts = manager.list_alerts()

    assert len(alerts) == 2
    assert {alert["id"] for alert in alerts} == {first["id"], second["id"]}


def test_resolve_alert_removes_from_active(tmp_path: Path) -> None:
    manager = AlertManager(log_path=tmp_path / "health.log")
    alert = manager.raise_alert("WARNING", "Resolve me")

    resolved = manager.resolve_alert(alert["id"])
    alerts = manager.list_alerts()

    assert resolved is not None
    assert resolved["active"] is False
    assert alerts == []


def test_critical_alert_has_higher_priority_than_info(tmp_path: Path) -> None:
    manager = AlertManager(log_path=tmp_path / "health.log")

    info_alert = manager.raise_alert(INFO, "Low priority")
    critical_alert = manager.raise_alert(CRITICAL, "High priority")

    assert critical_alert["priority"] > info_alert["priority"]
    assert manager.list_alerts()[0]["level"] == "CRITICAL"
