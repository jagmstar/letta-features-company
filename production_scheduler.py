"""Production scheduler shim used by CI tests.

The repository tests import this module directly from the repo root, so this
file mirrors the documented scheduler surface closely enough for validation.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

TaskFunction = Callable[[], Any]
BUILTIN_TASKS: dict[str, TaskFunction] = {
    "health": lambda: {"ok": True, "task": "health"},
    "status": lambda: {"ok": True, "task": "status"},
}

REPO_ROOT = Path(__file__).resolve().parent
DT_HOME = REPO_ROOT.parent
META_DIR = DT_HOME / "meta"
CONFIG_PATH = META_DIR / "scheduler_config.json"
LOG_PATH = META_DIR / "scheduler.log"
MAX_LOG_LINES = 1000


def _utc_stamp(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).isoformat(timespec="seconds")


@dataclass(slots=True)
class TaskSpec:
    name: str
    interval_seconds: int
    command: str | None = None
    task: str | None = None
    enabled: bool = True
    last_run_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def run(self) -> Any:
        if not self.enabled:
            return {"ok": False, "skipped": True, "task": self.name}
        if self.task in BUILTIN_TASKS:
            result = BUILTIN_TASKS[self.task]()
        elif self.command:
            completed = subprocess.run(self.command, shell=True, capture_output=True, text=True, check=False)
            result = {"rc": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
        else:
            result = {"ok": True, "task": self.name}
        self.last_run_at = _utc_stamp()
        return result


@dataclass(slots=True)
class Scheduler:
    config_path: Path
    tasks: dict[str, TaskSpec] = field(default_factory=dict)
    dry_run: bool = False

    @classmethod
    def from_config(cls, config_path: str | Path, dry_run: bool = False) -> "Scheduler":
        path = Path(config_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        tasks: dict[str, TaskSpec] = {}
        for item in payload.get("tasks", []):
            task = TaskSpec(
                name=item["name"],
                interval_seconds=int(item.get("interval_seconds", 60)),
                command=item.get("command"),
                task=item.get("task"),
                enabled=bool(item.get("enabled", True)),
                metadata={k: v for k, v in item.items() if k not in {"name", "interval_seconds", "command", "task", "enabled"}},
            )
            tasks[task.name] = task
        return cls(config_path=path, tasks=tasks, dry_run=dry_run)

    def run_once(self) -> dict[str, Any]:
        outcomes: dict[str, Any] = {}
        for name, task in self.tasks.items():
            outcomes[name] = {"dry_run": True, "task": name} if self.dry_run else task.run()
        return outcomes

    def summarize(self) -> dict[str, Any]:
        return {
            "config_path": str(self.config_path),
            "task_count": len(self.tasks),
            "dry_run": self.dry_run,
            "generated_at": _utc_stamp(),
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the production scheduler")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Path to the scheduler JSON configuration")
    parser.add_argument("--dry-run", action="store_true", help="Validate tasks without executing them")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    scheduler = Scheduler.from_config(args.config, dry_run=args.dry_run)
    result = scheduler.run_once()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
