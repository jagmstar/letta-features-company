"""Local scheduled demo worker used by the test suite.

This lightweight implementation mirrors the documented CLI surface so docs and
smoke tests can import it directly from the repository root during CI.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TASK_CHOICES = ("brief", "log")
REPO_ROOT = Path(__file__).resolve().parent
DT_HOME = REPO_ROOT.parent
META_DIR = DT_HOME / "meta"
LOG_PATH = META_DIR / ".scheduled-demo.log"
BRIEF_PATH = META_DIR / ".scheduled-demo-brief.json"
HEARTBEAT_PATH = META_DIR / "heartbeat-step-health.jsonl"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_stamp(moment: datetime | None = None) -> str:
    return (moment or _utc_now()).isoformat(timespec="seconds")


def build_brief(source: str = "cli", task: str = "brief") -> dict[str, Any]:
    return {
        "timestamp": _iso_stamp(),
        "source": source,
        "task": task,
        "summary": "inbox=0; voice=ok",
        "inbox": {"top_items": [], "signal_counts": {}},
        "team_status": {"agent_count": 0, "online_count": 0, "status": {}},
        "voice_health": {"available": True, "summary": "voice healthy"},
    }


def append_demo_line(source: str, task: str, detail: str = "") -> str:
    suffix = f" detail={detail}" if detail else ""
    line = (
        f"{_iso_stamp()} scheduled-demo task={task} source={source} "
        f"host=localhost user=ci pid=0{suffix}"
    )
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return line


def write_brief_snapshot(brief: dict[str, Any] | None = None, snapshot_path: Path | None = None) -> str:
    payload = brief or build_brief()
    destination = snapshot_path or BRIEF_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return str(destination)


def write_heartbeat_state(source: str, task: str, detail: str = "") -> dict[str, Any]:
    state = {"timestamp": _iso_stamp(), "source": source, "task": task, "detail": detail, "status": "ok"}
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HEARTBEAT_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n")
    return state


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Produce scheduled demo evidence")
    parser.add_argument("--source", default="cli", help="Source label for the demo run")
    parser.add_argument("--task", choices=("brief", "log"), default="brief", help="Demo task to execute")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    brief = build_brief(args.source, args.task)
    if args.task == "brief":
        write_brief_snapshot(brief)
        detail = brief["summary"]
    else:
        detail = "log-only"
    append_demo_line(args.source, args.task, detail)
    write_heartbeat_state(args.source, args.task, detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
