from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
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
    log_lines = [line for line in read_text(LOG_PATH).splitlines() if line.strip()]
    brief = json.loads(read_text(BRIEF_PATH))
    log_entries = [parse_log_line(line) for line in log_lines]
    log_entries = [entry for entry in log_entries if isinstance(entry.get("timestamp"), datetime)]
    log_entries.sort(key=lambda item: item["timestamp"])

    if not log_entries:
        raise RuntimeError("No parsable log entries found in scheduled demo log.")

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
    teams = brief.get("team_status", {})
    online_count = teams.get("online_count", 0)
    agent_count = teams.get("agent_count", 0)
    signal_counts = brief.get("inbox", {}).get("signal_counts", {})
    top_items = brief.get("inbox", {}).get("top_items", [])
    voice_health = brief.get("voice_health", {})
    summary = brief.get("summary", "")
    generated_at = datetime.now(timezone.utc)

    log_items_html = build_log_list(log_entries)
    team_rows_html = build_team_status(teams)
    top_items_html = build_top_items(top_items)

    hero_summary = summary.replace("; ", " • ")
    interval_label = human_duration(interval_seconds)

    html_doc = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <meta http-equiv=\"refresh\" content=\"60\" />
  <title>Schedules Dashboard</title>
  <meta name=\"description\" content=\"Live schedules dashboard for the Schedules feature\" />
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

    .stack {{ display: grid; gap: 14px; }}

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
      .hero__grid, .layout {{ grid-template-columns: 1fr 1fr; }}
    }}

    @media (max-width: 780px) {{
      .page {{ padding: 18px 14px 28px; }}
      .hero, .panel {{ border-radius: 18px; }}
      .hero__grid, .layout, .stat-grid {{ grid-template-columns: 1fr; }}
      .header {{ margin-bottom: 16px; }}
      .panel__head, .panel__body {{ padding-left: 16px; padding-right: 16px; }}
      .team-row {{ flex-direction: column; }}
      .team-meta {{ justify-items: start; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <header class="header">
      <div>
        <div class="eyebrow">Schedules feature</div>
        <h1>Real schedules dashboard</h1>
        <p class="subtitle">
          Live operational view for the <strong>scheduled-demo</strong> workflow, built from the current demo log and brief snapshot.
          The dashboard refreshes every 60 seconds and is intended for a GitHub Pages deployment.
        </p>
      </div>
      <aside class="header-card">
        <div>
          <div class="header-card__label">Dashboard status</div>
          <div class="header-card__value"><span class="{badge_class_for_status(freshness)}">{html.escape(freshness)}</span> <span class="muted">/ schedules ready</span></div>
        </div>
        <div>
          <div class="header-card__label">Generated at</div>
          <div class="header-card__meta js-local-time" datetime="{generated_at.astimezone(timezone.utc).isoformat()}" data-iso="{generated_at.astimezone(timezone.utc).isoformat()}">{html.escape(format_dt(generated_at))}</div>
        </div>
        <div>
          <div class="header-card__label">Data sources</div>
          <div class="header-card__meta">{html.escape(str(LOG_PATH))}<br />{html.escape(str(BRIEF_PATH))}</div>
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
          {html.escape(interval_label)} observed median cadence across the recent log set.
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
            <h2 class="panel__title">Brief snapshot</h2>
            <p class="panel__description">Pulled from the latest .scheduled-demo-brief.json payload.</p>
          </div>
          <span class="badge badge--neutral">{html.escape(str(online_count))}/{html.escape(str(agent_count))} online</span>
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
            <h2 class="panel__title">Recent log entries</h2>
            <p class="panel__description">The last {recent_count} lines from .scheduled-demo.log, parsed into structured cards.</p>
          </div>
          <span class="badge badge--neutral">{html.escape(human_duration(interval_seconds))} cadence</span>
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
