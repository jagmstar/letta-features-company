from __future__ import annotations

import ast
import html
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module_from_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_skills_module = _load_module_from_path("dashboard_skills_manager", REPO_ROOT / "skills" / "skills_manager.py")
_channels_module = _load_module_from_path("dashboard_channels_manager", REPO_ROOT / "channels" / "channels_manager.py")
Skill = _skills_module.Skill
SkillsManager = _skills_module.SkillsManager
Channel = _channels_module.Channel
ChannelsManager = _channels_module.ChannelsManager

META_DIR = BASE_DIR / "meta"
LOG_PATH = META_DIR / ".scheduled-demo.log"
BRIEF_PATH = META_DIR / ".scheduled-demo-brief.json"
OUTPUT_PATH = Path(__file__).resolve().with_name("index.html")

LOG_LINE_RE = re.compile(r"^(?P<timestamp>\S+)\s+(?P<schedule>\S+)\s+(?P<body>.*)$")
KV_RE = re.compile(r"^(?P<key>[A-Za-z0-9_\-]+)=(?P<value>.*)$")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_log_line(line: str) -> dict[str, Any]:
    match = LOG_LINE_RE.match(line.strip())
    if not match:
        return {"raw": line.strip()}

    ts = datetime.fromisoformat(match.group("timestamp").replace("Z", "+00:00"))
    schedule = match.group("schedule")
    body = match.group("body")

    fields: dict[str, str] = {}
    current_key: str | None = None
    known_keys = {"task", "source", "host", "user", "pid", "detail"}

    for token in body.split():
        token_match = KV_RE.match(token)
        if token_match:
            key = token_match.group("key")
            value = token_match.group("value")
            if key in known_keys:
                current_key = key
                fields[current_key] = value
                continue
        if current_key == "detail":
            fields[current_key] += f" {token}"
        elif current_key:
            fields[current_key] += f" {token}"

    return {
        "timestamp": ts,
        "schedule": schedule,
        "fields": fields,
        "raw": line.strip(),
    }


def human_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {rem}s" if rem else f"{minutes}m"
    hours, rem = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {rem}m" if rem else f"{hours}h"
    days, rem = divmod(hours, 24)
    return f"{days}d {rem}h" if rem else f"{days}d"


def format_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def format_relative(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    future = seconds >= 0
    seconds = abs(seconds)
    if seconds < 60:
        text = f"{seconds}s"
    elif seconds < 3600:
        minutes, rem = divmod(seconds, 60)
        text = f"{minutes}m {rem}s" if rem else f"{minutes}m"
    elif seconds < 86400:
        hours, rem = divmod(seconds, 3600)
        minutes = rem // 60
        text = f"{hours}h {minutes}m" if minutes else f"{hours}h"
    else:
        days, rem = divmod(seconds, 86400)
        hours = rem // 3600
        text = f"{days}d {hours}h" if hours else f"{days}d"
    return f"in {text}" if future else f"{text} ago"


def estimate_interval_seconds(log_entries: list[dict[str, Any]]) -> float:
    timestamps = [entry["timestamp"] for entry in log_entries if isinstance(entry.get("timestamp"), datetime)]
    timestamps.sort()
    diffs = [
        (later - earlier).total_seconds()
        for earlier, later in zip(timestamps, timestamps[1:])
        if (later - earlier).total_seconds() > 0
    ]
    return float(median(diffs)) if diffs else 300.0


def badge_class_for_status(status: str) -> str:
    normalized = status.lower()
    if normalized in {"active", "online", "ok", "healthy", "live"}:
        return "badge badge--good"
    if normalized in {"warning", "degraded", "partial"}:
        return "badge badge--warn"
    return "badge badge--neutral"


def count_test_cases(repo_root: Path) -> int:
    total = 0
    for path in repo_root.rglob("test_*.py"):
        if "__pycache__" in path.parts or ".git" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue

        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                total += 1
            elif isinstance(node, ast.ClassDef):
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name.startswith("test_"):
                        total += 1
    return total


def git_commit_count(repo_root: Path) -> int:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return 0
    if completed.returncode != 0:
        return 0
    try:
        return int((completed.stdout or "0").strip())
    except ValueError:
        return 0


def load_registered_skills() -> list[Skill]:
    manager = SkillsManager()
    manager.load_skills_from_directory(REPO_ROOT / "skills")
    return sorted(manager.list(), key=lambda skill: skill.name.lower())


def load_registered_channels() -> list[Channel]:
    manager = ChannelsManager()
    demo_channels = [
        Channel(name="ops", type="slack", webhook_url="https://hooks.slack.com/services/T000/B000/OPS"),
        Channel(name="team", type="telegram", webhook_url="https://api.telegram.org/botTOKEN/sendMessage"),
        Channel(name="alerts", type="discord", webhook_url="https://discord.com/api/webhooks/123/abc", enabled=False),
    ]
    for channel in demo_channels:
        manager.register(channel)
    return sorted(manager.list(), key=lambda channel: channel.name.lower())


def build_skill_rows(skills: list[Skill]) -> str:
    if not skills:
        return '<div class="summary-box">No skills registered.</div>'

    rows = []
    for skill in skills:
        status_label = "Enabled" if skill.enabled else "Disabled"
        status_class = badge_class_for_status("live" if skill.enabled else "warning")
        rows.append(
            f"""
            <div class="registry-row">
              <div>
                <div class="registry-name">{html.escape(skill.name)}</div>
                <div class="registry-meta">v{html.escape(skill.version)} · {html.escape(skill.description)}</div>
              </div>
              <div class="team-meta">
                <span class="{status_class}">{status_label}</span>
                <span class="muted">skill</span>
              </div>
            </div>
            """.strip()
        )
    return "\n".join(rows)


def build_channel_rows(channels: list[Channel]) -> str:
    if not channels:
        return '<div class="summary-box">No channels registered.</div>'

    rows = []
    for channel in channels:
        status_label = "Enabled" if channel.enabled else "Disabled"
        status_class = badge_class_for_status("live" if channel.enabled else "warning")
        rows.append(
            f"""
            <div class="registry-row">
              <div>
                <div class="registry-name">{html.escape(channel.name)}</div>
                <div class="registry-meta">{html.escape(channel.type.title())} · webhook configured</div>
              </div>
              <div class="team-meta">
                <span class="{status_class}">{status_label}</span>
                <span class="muted">channel</span>
              </div>
            </div>
            """.strip()
        )
    return "\n".join(rows)


def build_log_list(log_entries: list[dict[str, Any]]) -> str:
    items = []
    for entry in reversed(log_entries):
        fields = entry.get("fields", {})
        time_iso = entry["timestamp"].astimezone(timezone.utc).isoformat()
        tags = []
        for key in ("task", "source", "host", "user", "pid"):
            if key in fields:
                tags.append(f'<span class="chip">{html.escape(key)}: {html.escape(str(fields[key]))}</span>')
        detail = fields.get("detail")
        if detail:
            detail_html = f'<div class="log-detail">{html.escape(detail)}</div>'
        else:
            detail_html = ""

        raw = html.escape(entry["raw"])
        items.append(
            f"""
            <li class="log-item">
              <div class="log-item__top">
                <time class="log-time js-local-time" datetime="{time_iso}" data-iso="{time_iso}">{html.escape(format_dt(entry['timestamp']))}</time>
                <span class="log-schedule">{html.escape(entry['schedule'])}</span>
              </div>
              <div class="log-tags">{''.join(tags)}</div>
              {detail_html}
              <details class="raw-details">
                <summary>Raw log line</summary>
                <code>{raw}</code>
              </details>
            </li>
            """.strip()
        )
    return "\n".join(items)


def build_team_status(team_status: dict[str, Any]) -> str:
    status_map = team_status.get("status", {})
    rows = []
    for name, value in status_map.items():
        badge = badge_class_for_status(str(value.get("status", "")))
        rows.append(
            f"""
            <div class="team-row">
              <div>
                <div class="team-name">{html.escape(name)}</div>
                <div class="team-focus">{html.escape(str(value.get('focus', '')))}</div>
              </div>
              <div class="team-meta">
                <span class="{badge}">{html.escape(str(value.get('status', '')))}</span>
                <span class="muted">{html.escape(str(value.get('lead', '')))}</span>
              </div>
            </div>
            """.strip()
        )
    return "\n".join(rows)


def build_top_items(items: list[str]) -> str:
    return "\n".join(
        f'<li>{html.escape(item)}</li>'
        for item in items
    )


def build_dashboard() -> str:
    generated_at = datetime.now(timezone.utc)
    brief = json.loads(read_text(BRIEF_PATH))

    try:
        log_text = read_text(LOG_PATH)
    except FileNotFoundError:
        log_lines = []
    else:
        log_lines = [line for line in log_text.splitlines() if line.strip()]

    log_entries = [parse_log_line(line) for line in log_lines]
    log_entries = [entry for entry in log_entries if isinstance(entry.get("timestamp"), datetime)]
    log_entries.sort(key=lambda item: item["timestamp"])

    teams = brief.get("team_status", {})
    online_count = teams.get("online_count", 0)
    agent_count = teams.get("agent_count", 0)
    signal_counts = brief.get("inbox", {}).get("signal_counts", {})
    top_items = brief.get("inbox", {}).get("top_items", [])
    voice_health = brief.get("voice_health", {})
    summary = brief.get("summary", "")

    if log_entries:
        last_run = log_entries[-1]["timestamp"]
        interval_seconds = estimate_interval_seconds(log_entries)
        interval_td = timedelta(seconds=interval_seconds)
        next_run = last_run + interval_td
        now = datetime.now(timezone.utc)
        age = now - last_run
        freshness = "Active" if age.total_seconds() < 900 else "Idle"
        last_run_rel = format_relative(last_run - now)
        next_run_rel = format_relative(next_run - now)
        schedule_name = log_entries[-1]["schedule"]
        schedule_source = log_entries[-1].get("fields", {}).get("source", "task-scheduler")
        recent_count = len(log_entries)
        log_items_html = build_log_list(log_entries)
        interval_label = human_duration(interval_seconds)
        log_panel_description = f"The last {recent_count} lines from .scheduled-demo.log, parsed into structured cards."
        hero_summary = summary.replace("; ", " • ")
        interval_summary = f"{html.escape(interval_label)} observed median cadence across the recent log set."
    else:
        last_run = generated_at
        next_run = generated_at
        freshness = "No data available"
        last_run_rel = "No data available"
        next_run_rel = "No data available"
        schedule_name = "scheduled-demo"
        schedule_source = "task-scheduler"
        recent_count = 0
        log_items_html = """
          <li class="log-item">
            <div class="summary-box">No data available</div>
          </li>
        """.strip()
        interval_label = "No data available"
        log_panel_description = "No data available"
        hero_summary = summary.replace("; ", " • ")
        hero_summary = f"No data available — {hero_summary}" if hero_summary else "No data available"
        interval_summary = "No data available"

    team_rows_html = build_team_status(teams)
    top_items_html = build_top_items(top_items)
    skills = load_registered_skills()
    channels = load_registered_channels()
    skill_enabled_count = sum(1 for skill in skills if skill.enabled)
    skill_disabled_count = len(skills) - skill_enabled_count
    channel_enabled_count = sum(1 for channel in channels if channel.enabled)
    channel_disabled_count = len(channels) - channel_enabled_count
    total_features = 3
    total_tests = count_test_cases(REPO_ROOT)
    total_commits = git_commit_count(REPO_ROOT)
    skills_rows_html = build_skill_rows(skills)
    channels_rows_html = build_channel_rows(channels)

    system_overview_html = f"""
      <div class="feature-grid">
        <article class="metric">
          <div class="metric__label">Total features</div>
          <div class="metric__value">{total_features}</div>
          <div class="metric__detail">Schedules, Skills, and Channels.</div>
        </article>
        <article class="metric">
          <div class="metric__label">Total tests</div>
          <div class="metric__value">{total_tests}</div>
          <div class="metric__detail">Collected from the repository test suite.</div>
        </article>
        <article class="metric">
          <div class="metric__label">Total commits</div>
          <div class="metric__value">{total_commits}</div>
          <div class="metric__detail">Counted from the current Git history.</div>
        </article>
      </div>
    """.strip()

    feature_status_html = f"""
      <div class="feature-grid">
        <article class="metric">
          <div class="metric__label">Schedules</div>
          <div class="metric__value"><span class="{badge_class_for_status('live')}">LIVE</span></div>
          <div class="metric__detail">Active schedules dashboard fed by the current log and brief snapshot.</div>
        </article>
        <article class="metric">
          <div class="metric__label">Skills</div>
          <div class="metric__value"><span class="badge badge--neutral">READY</span></div>
          <div class="metric__detail">{len(skills)} registered skill(s) · {skill_enabled_count} enabled · {skill_disabled_count} disabled.</div>
        </article>
        <article class="metric">
          <div class="metric__label">Channels</div>
          <div class="metric__value"><span class="badge badge--neutral">READY</span></div>
          <div class="metric__detail">{len(channels)} registered channel(s) · {channel_enabled_count} enabled · {channel_disabled_count} disabled.</div>
        </article>
      </div>
    """.strip()

    skills_panel_html = f"""
      <div class="summary-box">
        <strong>Registry snapshot</strong><br />
        {len(skills)} registered skill(s) · {skill_enabled_count} enabled · {skill_disabled_count} disabled
      </div>
      <div class="registry-list">
        {skills_rows_html}
      </div>
    """.strip()

    channels_panel_html = f"""
      <div class="summary-box">
        <strong>Registry snapshot</strong><br />
        {len(channels)} registered channel(s) · {channel_enabled_count} enabled · {channel_disabled_count} disabled
      </div>
      <div class="registry-list">
        {channels_rows_html}
      </div>
    """.strip()

    html_doc = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <meta http-equiv=\"refresh\" content=\"60\" />
  <title>Schedules, Skills, and Channels Dashboard</title>
  <meta name=\"description\" content=\"Live dashboard for the Schedules, Skills, and Channels feature set\" />
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0b1020;
      --bg-elevated: #11182b;
      --panel: rgba(16, 23, 40, 0.92);
      --panel-border: rgba(148, 163, 184, 0.18);
      --text: #e5eefc;
      --muted: #95a3bb;
      --muted-strong: #c5d0e3;
      --accent: #7c9cff;
      --accent-2: #34d399;
      --warn: #f59e0b;
      --shadow: 0 24px 80px rgba(0, 0, 0, 0.35);
      --radius: 20px;
      --radius-sm: 14px;
      --max-width: 1240px;
    }}

    * {{ box-sizing: border-box; }}

    html {{
      background:
        radial-gradient(circle at top left, rgba(124, 156, 255, 0.18), transparent 28%),
        radial-gradient(circle at top right, rgba(52, 211, 153, 0.1), transparent 22%),
        linear-gradient(180deg, #060912 0%, #0b1020 32%, #0a0f1b 100%);
      min-height: 100%;
    }}

    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }}

    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    .page {{
      width: min(100%, var(--max-width));
      margin: 0 auto;
      padding: 28px 18px 44px;
    }}

    .header {{
      display: flex;
      flex-wrap: wrap;
      gap: 18px;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 20px;
    }}

    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-size: 0.72rem;
      color: var(--accent-2);
      margin-bottom: 8px;
      font-weight: 700;
    }}

    h1 {{
      margin: 0;
      font-size: clamp(2rem, 4vw, 3.5rem);
      line-height: 1.05;
      letter-spacing: -0.04em;
    }}

    .subtitle {{
      margin: 12px 0 0;
      max-width: 72ch;
      color: var(--muted);
      font-size: 1rem;
    }}

    .header-card {{
      display: grid;
      gap: 12px;
      min-width: min(100%, 340px);
      padding: 18px 20px;
      background: rgba(12, 18, 33, 0.86);
      border: 1px solid var(--panel-border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
    }}

    .header-card__label {{ color: var(--muted); font-size: 0.86rem; }}
    .header-card__value {{ font-size: 1.02rem; font-weight: 650; }}
    .header-card__meta {{ color: var(--muted); font-size: 0.9rem; }}

    .hero {{
      padding: 22px 22px 24px;
      border-radius: calc(var(--radius) + 6px);
      background: linear-gradient(135deg, rgba(17, 24, 43, 0.95), rgba(10, 16, 29, 0.9));
      border: 1px solid var(--panel-border);
      box-shadow: var(--shadow);
      margin-bottom: 18px;
    }}

    .hero__grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin-top: 18px;
    }}

    .metric {{
      padding: 16px;
      background: rgba(10, 16, 29, 0.65);
      border: 1px solid rgba(148, 163, 184, 0.14);
      border-radius: var(--radius-sm);
      min-height: 110px;
    }}

    .metric__label {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 10px; }}
    .metric__value {{ font-size: clamp(1.08rem, 2vw, 1.35rem); font-weight: 700; letter-spacing: -0.02em; }}
    .metric__detail {{ color: var(--muted); margin-top: 8px; font-size: 0.88rem; }}

    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 0.35rem 0.72rem;
      border-radius: 999px;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.03em;
      text-transform: uppercase;
      border: 1px solid transparent;
      white-space: nowrap;
    }}

    .badge--good {{ background: rgba(52, 211, 153, 0.14); color: #8ff5c7; border-color: rgba(52, 211, 153, 0.25); }}
    .badge--warn {{ background: rgba(245, 158, 11, 0.12); color: #fed7aa; border-color: rgba(245, 158, 11, 0.25); }}
    .badge--neutral {{ background: rgba(124, 156, 255, 0.12); color: #c7d2fe; border-color: rgba(124, 156, 255, 0.25); }}

    .layout {{
      display: grid;
      grid-template-columns: 1.05fr 1.35fr;
      gap: 18px;
      margin-top: 18px;
    }}

    .panel {{
      background: var(--panel);
      border: 1px solid var(--panel-border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
      overflow: hidden;
    }}

    .panel__head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      padding: 20px 20px 0;
    }}

    .panel__title {{ margin: 0; font-size: 1.15rem; letter-spacing: -0.02em; }}
    .panel__description {{ margin: 6px 0 0; color: var(--muted); font-size: 0.92rem; }}

    .panel__body {{ padding: 18px 20px 20px; }}

    .stat-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}

    .feature-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }}

    .stack {{ display: grid; gap: 14px; }}

    .registry-list {{
      display: grid;
      gap: 10px;
      margin-top: 16px;
    }}

    .registry-row {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 0;
      border-bottom: 1px solid rgba(148, 163, 184, 0.12);
    }}

    .registry-row:last-child {{ border-bottom: 0; padding-bottom: 0; }}
    .registry-name {{ font-weight: 700; }}
    .registry-meta {{ color: var(--muted); font-size: 0.92rem; margin-top: 4px; }}

    .list {{ margin: 0; padding-left: 18px; color: var(--muted-strong); }}
    .list li + li {{ margin-top: 10px; }}

    .summary-box {{
      padding: 16px;
      border-radius: var(--radius-sm);
      background: linear-gradient(180deg, rgba(124, 156, 255, 0.11), rgba(124, 156, 255, 0.05));
      border: 1px solid rgba(124, 156, 255, 0.18);
      color: var(--muted-strong);
    }}

    .summary-box code, .log-detail code, .raw-details code, .hero code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
    }}

    .chips {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .chip {{
      display: inline-flex;
      align-items: center;
      padding: 0.32rem 0.62rem;
      border-radius: 999px;
      border: 1px solid rgba(148, 163, 184, 0.16);
      background: rgba(148, 163, 184, 0.08);
      color: #dbe5f8;
      font-size: 0.78rem;
    }}

    .team-list {{ display: grid; gap: 10px; margin-top: 16px; }}
    .team-row {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 0;
      border-bottom: 1px solid rgba(148, 163, 184, 0.12);
    }}
    .team-row:last-child {{ border-bottom: 0; padding-bottom: 0; }}
    .team-name {{ font-weight: 700; }}
    .team-focus {{ color: var(--muted); font-size: 0.92rem; margin-top: 4px; }}
    .team-meta {{ display: grid; justify-items: end; gap: 6px; align-content: start; }}

    .log-list {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; }}
    .log-item {{
      padding: 14px 14px 12px;
      border-radius: 16px;
      background: rgba(10, 16, 29, 0.72);
      border: 1px solid rgba(148, 163, 184, 0.13);
    }}
    .log-item__top {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; flex-wrap: wrap; }}
    .log-time {{ color: var(--muted-strong); font-size: 0.92rem; font-weight: 600; }}
    .log-schedule {{ color: var(--accent-2); font-weight: 700; font-size: 0.84rem; text-transform: uppercase; letter-spacing: 0.08em; }}
    .log-tags {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
    .log-detail {{ margin-top: 10px; color: #d8e2f2; font-size: 0.94rem; }}
    .raw-details {{ margin-top: 10px; }}
    .raw-details summary {{ cursor: pointer; color: var(--muted); font-size: 0.9rem; }}
    .raw-details code {{ display: block; margin-top: 10px; padding: 12px; border-radius: 12px; background: rgba(2, 6, 23, 0.75); color: #dbe5f8; overflow-x: auto; }}

    .footer {{
      margin-top: 18px;
      padding: 14px 2px 0;
      color: var(--muted);
      font-size: 0.88rem;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 12px;
    }}

    .muted {{ color: var(--muted); }}
    .sr-only {{ position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }}

    @media (max-width: 1040px) {{
      .hero__grid, .layout, .feature-grid {{ grid-template-columns: 1fr 1fr; }}
    }}

    @media (max-width: 780px) {{
      .page {{ padding: 18px 14px 28px; }}
      .hero, .panel {{ border-radius: 18px; }}
      .hero__grid, .layout, .stat-grid, .feature-grid {{ grid-template-columns: 1fr; }}
      .header {{ margin-bottom: 16px; }}
      .panel__head, .panel__body {{ padding-left: 16px; padding-right: 16px; }}
      .team-row, .registry-row {{ flex-direction: column; }}
      .team-meta {{ justify-items: start; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <header class="header">
      <div>
        <div class="eyebrow">Feature dashboard</div>
        <h1>Schedules, Skills, Channels</h1>
        <p class="subtitle">
          Live operational view for the <strong>scheduled-demo</strong> workflow plus the repository skill and channel registries.
          The dashboard refreshes every 60 seconds and is intended for a GitHub Pages deployment.
        </p>
      </div>
      <aside class="header-card">
        <div>
          <div class="header-card__label">Dashboard status</div>
          <div class="header-card__value"><span class="{badge_class_for_status(freshness)}">{html.escape(freshness)}</span> <span class="muted">/ schedules, skills, and channels ready</span></div>
        </div>
        <div>
          <div class="header-card__label">Generated at</div>
          <div class="header-card__meta js-local-time" datetime="{generated_at.astimezone(timezone.utc).isoformat()}" data-iso="{generated_at.astimezone(timezone.utc).isoformat()}">{html.escape(format_dt(generated_at))}</div>
        </div>
        <div>
          <div class="header-card__label">Data sources</div>
          <div class="header-card__meta">{html.escape(str(LOG_PATH))}<br />{html.escape(str(BRIEF_PATH))}<br />skills/: repository skill files<br />channels/: channel registry demo</div>
        </div>
      </aside>
    </header>

    <section class="hero">
      <div class="chips" aria-label="summary tags">
        <span class="badge badge--good">{html.escape(freshness)}</span>
        <span class="badge badge--neutral">{html.escape(schedule_source)}</span>
        <span class="badge badge--neutral">{recent_count} recent log entries</span>
        <span class="badge badge--neutral">{html.escape(interval_label)} interval</span>
      </div>
      <p class="subtitle" style="margin-top: 14px; font-size: 1.02rem;">
        {html.escape(hero_summary)}
      </p>
      <div class="hero__grid">
        <article class="metric">
          <div class="metric__label">Scheduled task name</div>
          <div class="metric__value">{html.escape(schedule_name)}</div>
          <div class="metric__detail">Task source: {html.escape(schedule_source)}</div>
        </article>
        <article class="metric">
          <div class="metric__label">Status</div>
          <div class="metric__value">{html.escape(freshness)}</div>
          <div class="metric__detail">Latest run is <span class="js-relative" data-iso="{last_run.astimezone(timezone.utc).isoformat()}">{html.escape(last_run_rel)}</span>.</div>
        </article>
        <article class="metric">
          <div class="metric__label">Last run</div>
          <div class="metric__value js-local-time" datetime="{last_run.astimezone(timezone.utc).isoformat()}" data-iso="{last_run.astimezone(timezone.utc).isoformat()}">{html.escape(format_dt(last_run))}</div>
          <div class="metric__detail">Observed <span class="js-relative" data-iso="{last_run.astimezone(timezone.utc).isoformat()}">{html.escape(last_run_rel)}</span>.</div>
        </article>
        <article class="metric">
          <div class="metric__label">Next run</div>
          <div class="metric__value js-local-time" datetime="{next_run.astimezone(timezone.utc).isoformat()}" data-iso="{next_run.astimezone(timezone.utc).isoformat()}">{html.escape(format_dt(next_run))}</div>
          <div class="metric__detail">Estimated <span class="js-relative" data-iso="{next_run.astimezone(timezone.utc).isoformat()}">{html.escape(next_run_rel)}</span>.</div>
        </article>
      </div>
      <div class="stat-grid" style="margin-top: 14px;">
        <div class="summary-box">
          <strong>Interval</strong><br />
          {interval_summary}
        </div>
        <div class="summary-box">
          <strong>Brief summary</strong><br />
          <code>{html.escape(summary)}</code>
        </div>
      </div>
    </section>

    <section class="layout">
      <article class="panel">
        <div class="panel__head">
          <div>
            <h2 class="panel__title">System overview</h2>
            <p class="panel__description">Cross-cutting health for the dashboard and repository.</p>
          </div>
          <span class="badge badge--neutral">all features</span>
        </div>
        <div class="panel__body">
          {system_overview_html}
        </div>
      </article>

      <article class="panel">
        <div class="panel__head">
          <div>
            <h2 class="panel__title">Feature status</h2>
            <p class="panel__description">Live readiness across schedules, skills, and channels.</p>
          </div>
          <span class="badge badge--neutral">dashboard readiness</span>
        </div>
        <div class="panel__body">
          {feature_status_html}
        </div>
      </article>

      <article class="panel">
        <div class="panel__head">
          <div>
            <h2 class="panel__title">Schedules snapshot</h2>
            <p class="panel__description">Pulled from the latest .scheduled-demo-brief.json payload.</p>
          </div>
          <span class="badge badge--good">{html.escape(str(online_count))}/{html.escape(str(agent_count))} online</span>
        </div>
        <div class="panel__body stack">
          <div class="summary-box">
            <div><strong>Snapshot timestamp</strong></div>
            <div class="js-local-time" datetime="{brief.get('timestamp', '').replace('+00:00', 'Z')}" data-iso="{brief.get('timestamp', '').replace('+00:00', 'Z')}">{html.escape(str(brief.get('timestamp', '')))}</div>
            <div style="margin-top: 10px;"><strong>Voice health</strong></div>
            <div>{html.escape(str(voice_health.get('summary', '')))}</div>
          </div>

          <div>
            <h3 style="margin: 0 0 10px; font-size: 1rem;">Inbox top items</h3>
            <ul class="list">
              {top_items_html}
            </ul>
          </div>

          <div>
            <h3 style="margin: 0 0 10px; font-size: 1rem;">Signal counts</h3>
            <div class="chips">
              {''.join(f'<span class="chip">{html.escape(str(key))}: {html.escape(str(value))}</span>' for key, value in signal_counts.items())}
            </div>
          </div>

          <div>
            <h3 style="margin: 0 0 10px; font-size: 1rem;">Team status</h3>
            <div class="team-list">
              {team_rows_html}
            </div>
          </div>
        </div>
      </article>

      <article class="panel">
        <div class="panel__head">
          <div>
            <h2 class="panel__title">Skills registry</h2>
            <p class="panel__description">Registered skills discovered from the local skills directory.</p>
          </div>
          <span class="badge badge--neutral">{len(skills)} skills</span>
        </div>
        <div class="panel__body">
          {skills_panel_html}
        </div>
      </article>

      <article class="panel">
        <div class="panel__head">
          <div>
            <h2 class="panel__title">Channels registry</h2>
            <p class="panel__description">Registered channels discovered from the local channels directory.</p>
          </div>
          <span class="badge badge--neutral">{len(channels)} channels</span>
        </div>
        <div class="panel__body">
          {channels_panel_html}
        </div>
      </article>

      <article class="panel">
        <div class="panel__head">
          <div>
            <h2 class="panel__title">Recent log entries</h2>
            <p class="panel__description">{html.escape(log_panel_description)}</p>
          </div>
          <span class="badge badge--neutral">{html.escape(interval_label)} cadence</span>
        </div>
        <div class="panel__body">
          <ul class="log-list">
            {log_items_html}
          </ul>
        </div>
      </article>
    </section>

    <footer class="footer">
      <div>Live data loaded from the demo log and brief snapshot on disk.</div>
      <div>Auto-refreshes every 60 seconds.</div>
    </footer>
  </main>

  <script>
    (() => {{
      const formatRelative = (iso) => {{
        const target = new Date(iso);
        const diffMs = target.getTime() - Date.now();
        const future = diffMs >= 0;
        const absSeconds = Math.round(Math.abs(diffMs) / 1000);
        const parts = [];
        const days = Math.floor(absSeconds / 86400);
        const hours = Math.floor((absSeconds % 86400) / 3600);
        const minutes = Math.floor((absSeconds % 3600) / 60);
        const seconds = absSeconds % 60;
        if (days) parts.push(days + 'd');
        if (hours || days) parts.push(hours + 'h');
        if (!days) {{
          if (minutes || hours) parts.push(minutes + 'm');
          if (!hours) parts.push(seconds + 's');
        }}
        const text = parts.length ? parts.slice(0, 2).join(' ') : '0s';
        return future ? `in ${{text}}` : `${{text}} ago`;
      }};

      const formatLocal = (iso) => {{
        const d = new Date(iso);
        return new Intl.DateTimeFormat(undefined, {{
          dateStyle: 'medium',
          timeStyle: 'medium',
        }}).format(d);
      }};

      const updateTimes = () => {{
        document.querySelectorAll('.js-local-time[data-iso]').forEach((node) => {{
          const iso = node.getAttribute('data-iso');
          if (!iso) return;
          if (!node.dataset.renderedLocal) {{
            node.textContent = formatLocal(iso);
            node.dataset.renderedLocal = 'true';
          }}
        }});

        document.querySelectorAll('.js-relative[data-iso]').forEach((node) => {{
          const iso = node.getAttribute('data-iso');
          if (!iso) return;
          node.textContent = formatRelative(iso);
        }});
      }};

      updateTimes();
      setInterval(updateTimes, 1000);
    }})();
  </script>
</body>
</html>
"""

    return html_doc


def main() -> None:
    OUTPUT_PATH.write_text(build_dashboard(), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
