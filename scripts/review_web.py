#!/usr/bin/env python3
"""Local review web UI for pending alerts."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import sys
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlencode, urlparse


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alert_agent.core.config_loader import load_agent_config  # noqa: E402
from alert_agent.core.health_monitor import parse_timestamp, read_json_file  # noqa: E402
from alert_agent.core.manual_review import (  # noqa: E402
    ACTION_TO_QUEUE,
    dispatch_approved,
    ensure_dirs,
    find_issue,
    issue_summary,
    list_issues,
    load_issue,
    load_paths,
    queue_path,
    recent_audit_events,
    record_action,
)
from alert_agent.core.usage_metrics import filter_records_for_date, iter_month_records, summarize_records  # noqa: E402
from alert_agent.improvement.collector import read_audit_events  # noqa: E402
from alert_agent.improvement.measurement import measure_applied_proposal_effect  # noqa: E402
from alert_agent.improvement.review_state import (  # noqa: E402
    flatten_proposals as flatten_review_proposals,
    get_proposal as get_review_proposal,
    load_improvement_runs as load_review_runs,
    load_review_state,
    review_proposal as review_improvement_proposal,
)


STATUSES = ["pending", "approved", "rejected", "ignored"]
PRIORITIES = ["P0", "P1", "P2", "P3"]
DANGERS = ["critical", "high", "medium", "low"]
IMPROVEMENT_TYPES = ["ignore_rule", "classification_rule", "priority_threshold", "prompt_improvement"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/agent_config.yaml", help="Config file path")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8088, help="Bind port")
    return parser.parse_args()


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def page_shell(title: str, body: str, message: str = "", error: str = "", active_page: str = "queue") -> bytes:
    banner = ""
    if message:
        banner += f'<div class="banner ok">{esc(message)}</div>'
    if error:
        banner += f'<div class="banner err">{esc(error)}</div>'

    nav_items = [
        ("queue", "/", "Review Queue"),
        ("metrics", "/metrics", "Metrics"),
        ("improvements", "/improvements", "Improvements"),
    ]
    nav_links = "".join(
        f'<a class="nav-link{" active" if name == active_page else ""}" href="{href}">{esc(label)}</a>'
        for name, href, label in nav_items
    )

    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <style>
    :root {{
      --bg: #f5efe6;
      --panel: #fffaf2;
      --panel-strong: #fff;
      --ink: #1b1c1d;
      --muted: #5c5f63;
      --line: #d9c8b0;
      --accent: #b75e2b;
      --accent-2: #1f6f78;
      --ok: #2d7d46;
      --warn: #b26a00;
      --bad: #b42318;
      --shadow: 0 14px 40px rgba(77, 53, 24, 0.08);
      --radius: 18px;
      --mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      --sans: "Segoe UI", "Helvetica Neue", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: var(--sans);
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(183, 94, 43, 0.16), transparent 24rem),
        radial-gradient(circle at top right, rgba(31, 111, 120, 0.14), transparent 22rem),
        linear-gradient(180deg, #f9f4ed 0%, var(--bg) 100%);
    }}
    a {{ color: inherit; }}
    .wrap {{
      width: min(1380px, calc(100vw - 2rem));
      margin: 0 auto;
      padding: 1rem 0 2rem;
    }}
    .hero {{
      display: grid;
      gap: 0.75rem;
      padding: 1rem 0 1.5rem;
    }}
    .nav {{
      display: flex;
      gap: 0.55rem;
      flex-wrap: wrap;
    }}
    .nav-link {{
      display: inline-flex;
      align-items: center;
      padding: 0.55rem 0.85rem;
      border-radius: 999px;
      text-decoration: none;
      border: 1px solid rgba(217, 200, 176, 0.85);
      background: rgba(255,255,255,0.55);
      color: var(--muted);
      font-weight: 700;
      font-size: 0.9rem;
    }}
    .nav-link.active {{
      background: linear-gradient(135deg, rgba(183, 94, 43, 0.14), rgba(31, 111, 120, 0.18));
      color: var(--ink);
      border-color: rgba(183, 94, 43, 0.5);
    }}
    .eyebrow {{
      font-size: 0.78rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--accent-2);
      font-weight: 700;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(1.8rem, 4vw, 3rem);
      line-height: 0.95;
    }}
    .sub {{
      max-width: 62rem;
      color: var(--muted);
      font-size: 1rem;
    }}
    .banner {{
      border-radius: 14px;
      padding: 0.8rem 1rem;
      margin-bottom: 1rem;
      box-shadow: var(--shadow);
      border: 1px solid var(--line);
      background: var(--panel-strong);
    }}
    .banner.ok {{
      border-color: rgba(45, 125, 70, 0.35);
      background: rgba(45, 125, 70, 0.08);
    }}
    .banner.err {{
      border-color: rgba(180, 35, 24, 0.35);
      background: rgba(180, 35, 24, 0.08);
    }}
    .grid {{
      display: grid;
      gap: 1rem;
      grid-template-columns: minmax(0, 2.2fr) minmax(320px, 1fr);
      align-items: start;
    }}
    .panel {{
      background: rgba(255, 250, 242, 0.9);
      border: 1px solid rgba(217, 200, 176, 0.85);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow: hidden;
      backdrop-filter: blur(12px);
    }}
    .panel-header {{
      padding: 1rem 1.1rem 0.75rem;
      border-bottom: 1px solid rgba(217, 200, 176, 0.65);
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      align-items: end;
      flex-wrap: wrap;
    }}
    .panel-header h2 {{
      margin: 0;
      font-size: 1rem;
    }}
    .panel-body {{
      padding: 1rem 1.1rem 1.1rem;
    }}
    .tabs {{
      display: flex;
      gap: 0.45rem;
      flex-wrap: wrap;
    }}
    .tab {{
      display: inline-flex;
      align-items: center;
      padding: 0.55rem 0.8rem;
      border-radius: 999px;
      text-decoration: none;
      border: 1px solid rgba(217, 200, 176, 0.85);
      background: rgba(255,255,255,0.55);
      color: var(--muted);
      font-weight: 600;
      font-size: 0.92rem;
    }}
    .tab.active {{
      background: linear-gradient(135deg, rgba(183, 94, 43, 0.14), rgba(31, 111, 120, 0.18));
      color: var(--ink);
      border-color: rgba(183, 94, 43, 0.5);
    }}
    .toolbar {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 0.75rem;
      margin-bottom: 1rem;
    }}
    label {{
      display: grid;
      gap: 0.35rem;
      font-size: 0.82rem;
      color: var(--muted);
      font-weight: 600;
    }}
    input, select, textarea, button {{
      font: inherit;
    }}
    input, select, textarea {{
      width: 100%;
      border: 1px solid rgba(217, 200, 176, 0.95);
      border-radius: 12px;
      padding: 0.7rem 0.8rem;
      background: rgba(255,255,255,0.88);
      color: var(--ink);
    }}
    textarea {{
      min-height: 7rem;
      resize: vertical;
    }}
    .actions {{
      display: flex;
      gap: 0.5rem;
      flex-wrap: wrap;
    }}
    button, .button-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.4rem;
      border: 0;
      border-radius: 999px;
      padding: 0.72rem 1rem;
      text-decoration: none;
      cursor: pointer;
      color: #fff;
      background: linear-gradient(135deg, var(--accent), #8f441d);
      box-shadow: 0 10px 22px rgba(183, 94, 43, 0.18);
      font-weight: 700;
    }}
    button.alt, .button-link.alt {{
      background: linear-gradient(135deg, var(--accent-2), #174f55);
    }}
    button.ghost, .button-link.ghost {{
      background: #fff;
      color: var(--ink);
      border: 1px solid rgba(217, 200, 176, 0.95);
      box-shadow: none;
    }}
    button.warn {{
      background: linear-gradient(135deg, #d06b1d, #9a4d12);
    }}
    button.bad {{
      background: linear-gradient(135deg, #b42318, #7a190f);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.94rem;
    }}
    th, td {{
      padding: 0.75rem 0.55rem;
      border-bottom: 1px solid rgba(217, 200, 176, 0.6);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }}
    .mono {{
      font-family: var(--mono);
      font-size: 0.85rem;
    }}
    .pill {{
      display: inline-block;
      padding: 0.25rem 0.55rem;
      border-radius: 999px;
      font-size: 0.78rem;
      font-weight: 700;
      background: rgba(31, 111, 120, 0.12);
      color: var(--accent-2);
    }}
    .pill.p0 {{ background: rgba(180, 35, 24, 0.12); color: var(--bad); }}
    .pill.p1 {{ background: rgba(208, 107, 29, 0.12); color: #a55211; }}
    .pill.p2 {{ background: rgba(178, 106, 0, 0.12); color: var(--warn); }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.8rem;
    }}
    .meta-box {{
      border: 1px solid rgba(217, 200, 176, 0.75);
      border-radius: 14px;
      padding: 0.85rem;
      background: rgba(255,255,255,0.6);
    }}
    .meta-box h3 {{
      margin: 0 0 0.35rem;
      font-size: 0.83rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }}
    .muted {{ color: var(--muted); }}
    .reasoning {{
      white-space: pre-wrap;
      line-height: 1.45;
    }}
    .stack {{
      display: grid;
      gap: 1rem;
    }}
    .event {{
      border: 1px solid rgba(217, 200, 176, 0.75);
      border-radius: 14px;
      padding: 0.8rem;
      background: rgba(255,255,255,0.66);
    }}
    .event strong {{
      display: block;
      margin-bottom: 0.25rem;
    }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 0.8rem;
      margin-bottom: 1rem;
    }}
    .kpi-card {{
      border: 1px solid rgba(217, 200, 176, 0.75);
      border-radius: 14px;
      padding: 0.9rem;
      background: rgba(255,255,255,0.62);
    }}
    .kpi-card.ok {{ border-color: rgba(45, 125, 70, 0.35); }}
    .kpi-card.warn {{ border-color: rgba(178, 106, 0, 0.35); }}
    .kpi-card.bad {{ border-color: rgba(180, 35, 24, 0.35); }}
    .kpi-label {{
      color: var(--muted);
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 0.4rem;
    }}
    .kpi-value {{
      font-size: 1.55rem;
      font-weight: 700;
      line-height: 1.05;
    }}
    .kpi-meta {{
      margin-top: 0.45rem;
      color: var(--muted);
      font-size: 0.88rem;
    }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.8rem;
    }}
    .stats-list {{
      display: grid;
      gap: 0.55rem;
    }}
    .stat-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 0.8rem;
      align-items: center;
      padding-bottom: 0.55rem;
      border-bottom: 1px solid rgba(217, 200, 176, 0.5);
    }}
    .stat-row:last-child {{
      border-bottom: 0;
      padding-bottom: 0;
    }}
    .stat-name {{
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .stat-value {{
      font-weight: 700;
      text-align: right;
    }}
    .empty {{
      padding: 2rem 1rem;
      text-align: center;
      color: var(--muted);
    }}
    @media (max-width: 1080px) {{
      .grid {{ grid-template-columns: 1fr; }}
      .toolbar {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .kpi-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 680px) {{
      .wrap {{ width: min(100vw - 1rem, 100%); }}
      .toolbar, .meta-grid, .stats-grid, .kpi-grid {{ grid-template-columns: 1fr; }}
      th:nth-child(5), td:nth-child(5),
      th:nth-child(6), td:nth-child(6) {{ display: none; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="eyebrow">Local Review Console</div>
      <h1>{esc(title)}</h1>
      <div class="sub">File-first review workflow for assigned teams. Queue actions write the same JSON and audit log as the CLI, so this stays consistent with the workstation pipeline.</div>
      <nav class="nav">{nav_links}</nav>
    </section>
    {banner}
    {body}
  </div>
</body>
</html>"""
    return document.encode("utf-8")


def queue_counts(paths: dict[str, Path]) -> dict[str, int]:
    return {status: len(list(queue_path(paths, status).glob("*.json"))) for status in STATUSES}


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def queue_count(directory: Path, pattern: str) -> int:
    if not directory.exists():
        return 0
    return len(list(directory.glob(pattern)))


def queue_oldest_age(directory: Path, pattern: str) -> str:
    if not directory.exists():
        return "none"
    files = list(directory.glob(pattern))
    if not files:
        return "none"
    oldest = min(files, key=lambda item: item.stat().st_mtime)
    modified = dt.datetime.fromtimestamp(oldest.stat().st_mtime, tz=dt.timezone.utc)
    return f"{oldest.name} ({format_age(modified)})"


def recent_file_count(directory: Path, pattern: str, since_hours: int) -> int:
    if not directory.exists():
        return 0
    cutoff = now_utc() - dt.timedelta(hours=since_hours)
    count = 0
    for path in directory.glob(pattern):
        modified = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
        if modified >= cutoff:
            count += 1
    return count


def format_age(timestamp: dt.datetime | None) -> str:
    if timestamp is None:
        return "unknown"
    delta = now_utc() - timestamp
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def format_timestamp(value: Any) -> str:
    timestamp = parse_timestamp(value)
    if timestamp is None:
        return "unknown"
    return f"{timestamp.isoformat()} ({format_age(timestamp)})"


def format_duration(start: Any, end: Any) -> str:
    started = parse_timestamp(start)
    finished = parse_timestamp(end)
    if started is None or finished is None:
        return "unknown"
    total_seconds = max(int((finished - started).total_seconds()), 0)
    minutes, seconds = divmod(total_seconds, 60)
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def kpi_card(label: str, value: str, meta: str, tone: str = "neutral") -> str:
    return (
        f'<div class="kpi-card {tone}">'
        f'<div class="kpi-label">{esc(label)}</div>'
        f'<div class="kpi-value">{esc(value)}</div>'
        f'<div class="kpi-meta">{esc(meta)}</div>'
        '</div>'
    )


def render_stats_list(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return '<div class="empty">No data available.</div>'
    return '<div class="stats-list">' + "".join(
        f'<div class="stat-row"><div class="stat-name">{esc(name)}</div><div class="stat-value">{esc(value)}</div></div>'
        for name, value in rows
    ) + '</div>'


def render_metrics_panel(title: str, description: str, rows: list[tuple[str, str]]) -> str:
    return f"""
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>{esc(title)}</h2>
          <div class="muted">{esc(description)}</div>
        </div>
      </div>
      <div class="panel-body">
        {render_stats_list(rows)}
      </div>
    </section>
    """


def load_issue_documents(directory: Path) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    if not directory.exists():
        return documents
    for path in sorted(directory.glob("*.json")):
        try:
            documents.append(load_issue(path))
        except json.JSONDecodeError:
            continue
    return documents


def load_improvement_runs(paths: dict[str, Path]) -> list[dict[str, Any]]:
    return load_review_runs(paths)


def flatten_proposals(
    runs: list[dict[str, Any]],
    review_state: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return flatten_review_proposals(runs, review_state)


def summarize_issue_dimensions(issue_sets: list[list[dict[str, Any]]]) -> tuple[Counter[str], Counter[str], Counter[str]]:
    priorities: Counter[str] = Counter()
    classes: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    for issues in issue_sets:
        for issue in issues:
            final = issue.get("final", {})
            review = issue.get("review", {})
            priority = str(final.get("priority") or "unknown")
            classification = str(final.get("class") or "unknown")
            decision = str(review.get("decision") or "unreviewed")
            priorities[priority] += 1
            classes[classification] += 1
            decisions[decision] += 1
    return priorities, classes, decisions


def top_counter_rows(counter: Counter[str], limit: int = 6) -> list[tuple[str, str]]:
    if not counter:
        return []
    return [(name, str(count)) for name, count in counter.most_common(limit)]


def top_summary_agent(summary: dict[str, Any]) -> str:
    by_agent = dict(summary.get("by_agent", {}))
    if not by_agent:
        return "none"
    top_agent, stats = max(by_agent.items(), key=lambda item: item[1]["cost"])
    return f"{top_agent} ({int(stats['calls'])} calls)"


def top_summary_operation(summary: dict[str, Any]) -> str:
    by_operation = dict(summary.get("by_operation", {}))
    if not by_operation:
        return "none"
    top_operation, count = max(by_operation.items(), key=lambda item: item[1])
    return f"{top_operation} ({count})"


def latest_alert_timestamp(payload: dict[str, Any]) -> dt.datetime | None:
    latest: dt.datetime | None = None
    for value in payload.values():
        if not isinstance(value, dict):
            continue
        candidate = parse_timestamp(value.get("last_alert_at") or value.get("sent_at"))
        if candidate is not None and (latest is None or candidate > latest):
            latest = candidate
    return latest


def build_metrics_snapshot(paths: dict[str, Path], config_file: str) -> dict[str, Any]:
    common_config = load_agent_config("common", config_file)
    health_config = load_agent_config("health_monitor", config_file)
    monitor_config = load_agent_config("monitor", config_file)

    metrics_dir = paths["metrics_dir"]
    output_dir = paths["output_dir"]
    current = now_utc()
    month_key = current.strftime("%Y-%m")
    month_records = iter_month_records(metrics_dir, month_key)
    day_records = filter_records_for_date(month_records, current.date())
    monthly_usage = summarize_records(month_records)
    daily_usage = summarize_records(day_records)

    pipeline_state = read_json_file(metrics_dir / "pipeline_state.json")
    updated_at = parse_timestamp(pipeline_state.get("updated_at"))
    stale_after_minutes = int(health_config.get("stale_run_after_minutes", 120) or 120)
    pipeline_age_minutes = None if updated_at is None else int((current - updated_at).total_seconds() // 60)
    pipeline_status = str(pipeline_state.get("status") or "unknown")
    pipeline_health = "ok"
    if pipeline_status == "failed":
        pipeline_health = "bad"
    elif pipeline_age_minutes is None or pipeline_age_minutes >= stale_after_minutes:
        pipeline_health = "warn"

    lock_file = str(pipeline_state.get("lock_file") or health_config.get("lock_file") or "").strip()
    lock_path = Path(lock_file) if lock_file else None
    lock_exists = bool(lock_path and lock_path.exists())
    lock_age = None
    if lock_exists and lock_path is not None:
        lock_age = dt.datetime.fromtimestamp(lock_path.stat().st_mtime, tz=dt.timezone.utc)

    queue_summary = {
        "pending": queue_count(output_dir / "alerts" / "pending", "*.json"),
        "approved": queue_count(output_dir / "alerts" / "approved", "*.json"),
        "recommendations": queue_count(output_dir / "alerts" / "recommendations", "*.md"),
        "sent": queue_count(output_dir / "alerts" / "sent", "*.md"),
        "pending_oldest": queue_oldest_age(output_dir / "alerts" / "pending", "*.json"),
        "approved_oldest": queue_oldest_age(output_dir / "alerts" / "approved", "*.json"),
        "recommendations_oldest": queue_oldest_age(output_dir / "alerts" / "recommendations", "*.md"),
        "sent_oldest": queue_oldest_age(output_dir / "alerts" / "sent", "*.md"),
        "sent_last_24h": recent_file_count(output_dir / "alerts" / "sent", "*.md", 24),
    }

    triage_docs = load_issue_documents(output_dir / "alerts" / "triage")
    pending_docs = load_issue_documents(output_dir / "alerts" / "pending")
    approved_docs = load_issue_documents(output_dir / "alerts" / "approved")
    rejected_docs = load_issue_documents(output_dir / "alerts" / "rejected")
    ignored_docs = load_issue_documents(output_dir / "alerts" / "ignored")
    priorities, classes, _ = summarize_issue_dimensions([triage_docs])
    _, _, decisions = summarize_issue_dimensions([pending_docs, approved_docs, rejected_docs, ignored_docs])

    alert_states = {
        "budget": read_json_file(metrics_dir / "budget_alert_state.json"),
        "health": read_json_file(metrics_dir / "health_alert_state.json"),
        "queue": read_json_file(metrics_dir / "queue_alert_state.json"),
        "daily_summary": read_json_file(metrics_dir / "daily_summary_state.json"),
        "budget_enforcement": read_json_file(metrics_dir / "budget_enforcement_state.json"),
    }

    return {
        "common_config": common_config,
        "monitor_config": monitor_config,
        "health_config": health_config,
        "daily_usage": daily_usage,
        "monthly_usage": monthly_usage,
        "pipeline_state": pipeline_state,
        "pipeline_health": pipeline_health,
        "stale_after_minutes": stale_after_minutes,
        "pipeline_age_minutes": pipeline_age_minutes,
        "lock_exists": lock_exists,
        "lock_age": lock_age,
        "queue_summary": queue_summary,
        "triage_docs": triage_docs,
        "priority_counts": priorities,
        "class_counts": classes,
        "decision_counts": decisions,
        "alert_states": alert_states,
    }


def render_tabs(active_status: str, filters: dict[str, str], counts: dict[str, int]) -> str:
    links: list[str] = []
    for status in STATUSES:
        query = dict(filters)
        query["status"] = status
        href = "/?" + urlencode(query)
        classes = "tab active" if status == active_status else "tab"
        links.append(f'<a class="{classes}" href="{href}">{esc(status.title())} ({counts[status]})</a>')
    return '<div class="tabs">' + "".join(links) + "</div>"


def render_filter_toolbar(filters: dict[str, str], projects: list[str], teams: list[str]) -> str:
    def select_options(current: str, values: list[str], label_all: str = "all") -> str:
        options = [f'<option value="">{esc(label_all)}</option>']
        for value in values:
            selected = ' selected' if current == value else ''
            options.append(f'<option value="{esc(value)}"{selected}>{esc(value)}</option>')
        return "".join(options)

    status_options = []
    current_status = filters.get("status", "pending")
    for value in STATUSES:
        selected = ' selected' if current_status == value else ''
        status_options.append(f'<option value="{esc(value)}"{selected}>{esc(value)}</option>')

    return f"""
    <form method="get" class="toolbar">
      <label>Status
        <select name="status">{''.join(status_options)}</select>
      </label>
      <label>Project
        <select name="project">{select_options(filters.get("project", ""), projects)}</select>
      </label>
      <label>Priority
        <select name="priority">{select_options(filters.get("priority", ""), PRIORITIES)}</select>
      </label>
      <label>Review Team
        <select name="team">{select_options(filters.get("team", ""), teams)}</select>
      </label>
      <div class="actions">
        <button type="submit" class="ghost">Apply Filters</button>
        <a class="button-link ghost" href="/">Reset</a>
      </div>
    </form>
    """


def render_queue_table(status: str, summaries: list[dict[str, object]], filters: dict[str, str]) -> str:
    if not summaries:
        return '<div class="empty">No issues match the current filters.</div>'

    rows: list[str] = []
    for summary in summaries:
        issue_id = str(summary["issue_id"])
        priority = str(summary["priority"] or "")
        query = urlencode({"status": status})
        detail_href = f"/issue/{issue_id}?{query}"
        rows.append(
            "<tr>"
            f'<td><a href="{detail_href}"><strong>{esc(issue_id)}</strong></a><div class="muted">{esc(summary["title"])}</div></td>'
            f'<td><span class="pill {esc(priority.lower())}">{esc(priority)}</span></td>'
            f"<td>{esc(summary['classification'])}</td>"
            f"<td>{esc(summary['project'])}<div class=\"muted\">{esc(summary['review_team'])}</div></td>"
            f"<td>{esc(summary['count'])}</td>"
            f"<td>{esc(summary['users'])}</td>"
            f"<td>{esc(summary['review_decision'])}<div class=\"muted\">{esc(summary['review_confidence'])}</div></td>"
            "</tr>"
        )
    return (
        "<table>"
        "<thead><tr><th>Issue</th><th>Priority</th><th>Class</th><th>Project / Team</th><th>Count</th><th>Users</th><th>Review</th></tr></thead>"
        "<tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_recent_events(events: list[dict[str, object]]) -> str:
    if not events:
        return '<div class="empty">No manual review actions yet.</div>'
    blocks: list[str] = []
    for event in events:
        blocks.append(
            '<div class="event">'
            f"<strong>{esc(event.get('issue_id'))} • {esc(event.get('action'))}</strong>"
            f"<div class=\"muted\">{esc(event.get('timestamp'))} • reviewer={esc(event.get('reviewer'))} • team={esc(event.get('review_team'))}</div>"
            f"<div>{esc(event.get('note') or '')}</div>"
            "</div>"
        )
    return '<div class="stack">' + "".join(blocks) + "</div>"


def render_home(paths: dict[str, Path], filters: dict[str, str], message: str = "", error: str = "") -> bytes:
    status = filters.get("status") or "pending"
    counts = queue_counts(paths)
    statuses_for_discovery = [list_issues(paths, item, limit=200) for item in STATUSES]
    all_summaries = [summary for batch in statuses_for_discovery for summary in batch]
    projects = sorted({str(summary.get("project") or "") for summary in all_summaries if summary.get("project")})
    teams = sorted({str(summary.get("review_team") or "") for summary in all_summaries if summary.get("review_team")})
    summaries = list_issues(
        paths,
        status,
        limit=200,
        project=filters.get("project") or None,
        priority=filters.get("priority") or None,
        team=filters.get("team") or None,
    )
    events = recent_audit_events(paths, limit=12)

    body = f"""
    <div class="grid">
      <section class="panel">
        <div class="panel-header">
          <div>
            <h2>Review Queue</h2>
            <div class="muted">Review lanes for assigned teams. Filters stay file-first and safe to run on the workstation.</div>
          </div>
          {render_tabs(status, filters, counts)}
        </div>
        <div class="panel-body">
          {render_filter_toolbar(filters, projects, teams)}
          <div class="actions" style="margin-bottom:1rem;">
            <form method="post" action="/dispatch">
              <input type="hidden" name="send" value="0">
              <button type="submit" class="alt">Dispatch Approved Dry Run</button>
            </form>
            <form method="post" action="/dispatch">
              <input type="hidden" name="send" value="1">
              <button type="submit">Dispatch Approved To Teams</button>
            </form>
          </div>
          {render_queue_table(status, summaries, filters)}
        </div>
      </section>
      <aside class="panel">
        <div class="panel-header">
          <div>
            <h2>Recent Decisions</h2>
            <div class="muted">Latest manual review actions from the audit log.</div>
          </div>
        </div>
        <div class="panel-body">
          {render_recent_events(events)}
        </div>
      </aside>
    </div>
    """
    return page_shell("Review Queue", body, message=message, error=error, active_page="queue")


def render_metrics(paths: dict[str, Path], config_file: str, message: str = "", error: str = "") -> bytes:
    snapshot = build_metrics_snapshot(paths, config_file)
    pipeline_state = snapshot["pipeline_state"]
    queue_summary = snapshot["queue_summary"]
    daily_usage = snapshot["daily_usage"]
    monthly_usage = snapshot["monthly_usage"]
    pipeline_health = snapshot["pipeline_health"]
    alert_states = snapshot["alert_states"]
    monthly_budget = float(snapshot["monitor_config"].get("monthly_budget_usd", 0) or 0)
    daily_budget = float(snapshot["monitor_config"].get("daily_budget_usd", 0) or 0)

    critical_now = int(snapshot["priority_counts"].get("P0", 0) + snapshot["priority_counts"].get("P1", 0))
    pipeline_updated = parse_timestamp(pipeline_state.get("updated_at"))
    daily_cost = float(daily_usage["total_cost"])
    monthly_cost = float(monthly_usage["total_cost"])
    sent_last_24h = int(queue_summary["sent_last_24h"])

    kpis = "".join([
        kpi_card(
            "Pipeline",
            str(pipeline_state.get("status") or "unknown"),
            f"Last update {format_age(pipeline_updated)}",
            tone=pipeline_health,
        ),
        kpi_card(
            "Daily AI Spend",
            f"${daily_cost:.4f}",
            f"{int(daily_usage['total_calls'])} calls • {int(daily_usage['total_tokens'])} tokens",
            tone="warn" if daily_budget > 0 and daily_cost >= daily_budget else "neutral",
        ),
        kpi_card(
            "Monthly AI Spend",
            f"${monthly_cost:.4f}",
            f"Budget ${monthly_budget:.2f}" if monthly_budget > 0 else "Budget not set",
            tone="warn" if monthly_budget > 0 and monthly_cost >= monthly_budget * 0.8 else "neutral",
        ),
        kpi_card(
            "Critical Snapshot",
            str(critical_now),
            f"P0/P1 across triage and review queues • sent last 24h: {sent_last_24h}",
            tone="warn" if critical_now > 0 else "ok",
        ),
    ])

    pipeline_rows = [
        ("Run ID", str(pipeline_state.get("run_id") or "unknown")),
        ("Updated", format_timestamp(pipeline_state.get("updated_at"))),
        ("Started", format_timestamp(pipeline_state.get("started_at"))),
        ("Finished", format_timestamp(pipeline_state.get("finished_at"))),
        ("Duration", format_duration(pipeline_state.get("started_at"), pipeline_state.get("finished_at"))),
        ("Stale Threshold", f"{snapshot['stale_after_minutes']} minutes"),
        ("Triaged Last Run", str(pipeline_state.get("triaged", 0))),
        ("Approved Last Run", str(pipeline_state.get("approved", 0))),
        ("Pending Last Run", str(pipeline_state.get("pending", 0))),
        ("Recommendations Last Run", str(pipeline_state.get("recommendations", 0))),
        ("Sent Last Run", str(pipeline_state.get("sent", 0))),
        ("Host", str(pipeline_state.get("host") or "unknown")),
        ("Lock File", "present" if snapshot["lock_exists"] else "not present"),
        ("Lock Age", format_age(snapshot["lock_age"]) if snapshot["lock_age"] else "n/a"),
    ]

    usage_rows = [
        ("Daily Cost", f"${daily_cost:.6f}" + (f" / ${daily_budget:.2f}" if daily_budget > 0 else "")),
        ("Monthly Cost", f"${monthly_cost:.6f}" + (f" / ${monthly_budget:.2f}" if monthly_budget > 0 else "")),
        ("Daily Calls", str(int(daily_usage["total_calls"]))),
        ("Monthly Calls", str(int(monthly_usage["total_calls"]))),
        ("Daily Tokens", str(int(daily_usage["total_tokens"]))),
        ("Monthly Tokens", str(int(monthly_usage["total_tokens"]))),
        ("Top Agent Today", top_summary_agent(daily_usage)),
        ("Top Operation Today", top_summary_operation(daily_usage)),
        ("Cost Sources", ", ".join(sorted(dict(monthly_usage.get("by_source", {})).keys())) or "none"),
    ]

    queue_rows = [
        ("Pending", f"{queue_summary['pending']} • oldest {queue_summary['pending_oldest']}"),
        ("Approved", f"{queue_summary['approved']} • oldest {queue_summary['approved_oldest']}"),
        ("Recommendations", f"{queue_summary['recommendations']} • oldest {queue_summary['recommendations_oldest']}"),
        ("Sent", f"{queue_summary['sent']} • oldest {queue_summary['sent_oldest']}"),
        ("Sent Last 24h", str(sent_last_24h)),
        ("Current Triage Files", str(len(snapshot["triage_docs"]))),
    ]

    monitor_rows = [
        ("Budget Alerts", format_age(latest_alert_timestamp(alert_states["budget"])) if latest_alert_timestamp(alert_states["budget"]) else "none yet"),
        ("Health Alerts", format_age(latest_alert_timestamp(alert_states["health"])) if latest_alert_timestamp(alert_states["health"]) else "none yet"),
        ("Queue Alerts", format_age(latest_alert_timestamp(alert_states["queue"])) if latest_alert_timestamp(alert_states["queue"]) else "none yet"),
        ("Daily Summary", format_timestamp(alert_states["daily_summary"].get("sent_at")) if alert_states["daily_summary"] else "not sent yet"),
        ("Budget Enforcement", str(alert_states["budget_enforcement"].get("reason") or "inactive") if alert_states["budget_enforcement"] else "inactive"),
    ]

    breakdown_panel = f"""
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>Alert Breakdown</h2>
          <div class="muted">Current file-backed distribution from triage and review queues.</div>
        </div>
      </div>
      <div class="panel-body">
        <div class="stats-grid">
          <div class="meta-box">
            <h3>Priority Mix</h3>
            {render_stats_list(top_counter_rows(snapshot["priority_counts"], 8))}
          </div>
          <div class="meta-box">
            <h3>Review Decisions</h3>
            {render_stats_list(top_counter_rows(snapshot["decision_counts"], 8))}
          </div>
          <div class="meta-box" style="grid-column: 1 / -1;">
            <h3>Top Classes</h3>
            {render_stats_list(top_counter_rows(snapshot["class_counts"], 10))}
          </div>
        </div>
      </div>
    </section>
    """

    body = f"""
    <div class="panel" style="margin-bottom:1rem;">
      <div class="panel-body">
        <div class="kpi-grid">{kpis}</div>
      </div>
    </div>
    <div class="grid">
      <section class="stack">
        {render_metrics_panel('Pipeline Health', 'Use this to prove the workstation is alive even when Teams is quiet.', pipeline_rows)}
        {render_metrics_panel('AI Usage', 'Current UTC day and month usage from the AI ledger.', usage_rows)}
        {breakdown_panel}
      </section>
      <aside class="stack">
        {render_metrics_panel('Queue Snapshot', 'Counts and oldest files from the alert workflow directories.', queue_rows)}
        {render_metrics_panel('Monitor State', 'Most recent alert and summary timestamps from the monitor state files.', monitor_rows)}
      </aside>
    </div>
    """
    return page_shell("Operations Metrics", body, message=message, error=error, active_page="metrics")


def render_improvement_filters(filters: dict[str, str]) -> str:
    def options(values: list[str], current: str) -> str:
        rendered = ['<option value="">all</option>']
        for value in values:
            selected = ' selected' if current == value else ''
            rendered.append(f'<option value="{esc(value)}"{selected}>{esc(value)}</option>')
        return "".join(rendered)

    return f"""
    <form method="get" class="toolbar">
      <label>Type
        <select name="type">{options(IMPROVEMENT_TYPES, filters.get("type", ""))}</select>
      </label>
      <label>Project
        <input name="project" value="{esc(filters.get('project', ''))}" placeholder="backend">
      </label>
      <label>Status
        <select name="status">{options(['proposed', 'accepted', 'rejected', 'deferred', 'applied', 'superseded'], filters.get('status', ''))}</select>
      </label>
      <label>Risk
        <select name="risk">{options(['low', 'medium', 'high'], filters.get('risk', ''))}</select>
      </label>
      <div class="actions">
        <button type="submit" class="ghost">Apply Filters</button>
        <a class="button-link ghost" href="/improvements">Reset</a>
      </div>
    </form>
    """


def proposal_matches_filters(proposal: dict[str, Any], filters: dict[str, str]) -> bool:
    if filters.get("type") and str(proposal.get("type") or "") != filters["type"]:
        return False
    if filters.get("project") and str(proposal.get("project") or "") != filters["project"]:
        return False
    if filters.get("status") and str(proposal.get("status") or "") != filters["status"]:
        return False
    if filters.get("risk") and str(proposal.get("risk") or "") != filters["risk"]:
        return False
    return True


def render_improvements_table(proposals: list[dict[str, Any]]) -> str:
    if not proposals:
        return '<div class="empty">No improvement proposals available for the current filters.</div>'

    rows: list[str] = []
    for proposal in proposals:
        evidence = proposal.get("evidence", {})
        notes = [str(note) for note in evidence.get("notes", [])[:2]]
        target_files = ", ".join(str(item) for item in proposal.get("target_files", [])[:2])
        proposal_id = str(proposal.get("proposal_id") or "")
        detail_href = f"/improvements/{quote_plus(proposal_id)}"
        reviewed_by = str(proposal.get("reviewer") or "")
        review_note = str(proposal.get("review_note") or "")
        row_actions = (
            f'<form method="post" action="/improvements/action" class="inline-form">'
            f'<input type="hidden" name="proposal_id" value="{esc(proposal_id)}">'
            '<input type="hidden" name="reviewer" value="manual">'
            '<input type="hidden" name="note" value="">'
            '<button type="submit" name="action" value="accept">Accept</button>'
            '<button type="submit" name="action" value="defer" class="alt">Defer</button>'
            '<button type="submit" name="action" value="reject" class="bad">Reject</button>'
            '</form>'
        )
        rows.append(
            "<tr>"
            f"<td><a href=\"{detail_href}\"><strong>{esc(proposal_id)}</strong></a><div class=\"muted\">{esc(proposal.get('summary'))}</div></td>"
            f"<td><span class=\"pill\">{esc(proposal.get('type'))}</span></td>"
            f"<td>{esc(proposal.get('project') or 'all')}</td>"
            f"<td>{esc(proposal.get('status') or 'proposed')}<div class=\"muted\">{esc(reviewed_by or 'pending review')}</div></td>"
            f"<td>{esc(proposal.get('risk'))}<div class=\"muted\">confidence {esc(proposal.get('confidence'))}</div></td>"
            f"<td>{esc(evidence.get('sample_size'))}<div class=\"muted\">{esc(json.dumps(evidence.get('manual_actions', {}), ensure_ascii=True))}</div></td>"
            f"<td>{esc(target_files)}<div class=\"muted\">{esc(' | '.join(notes) or review_note)}</div>{row_actions}</td>"
            "</tr>"
        )
    return (
        "<table>"
        "<thead><tr><th>Proposal</th><th>Type</th><th>Project</th><th>Status</th><th>Risk</th><th>Evidence</th><th>Targets / Notes</th></tr></thead>"
        "<tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_applied_impact_table(proposals: list[dict[str, Any]], paths: dict[str, Path]) -> str:
    applied = [proposal for proposal in proposals if str(proposal.get("status") or "") == "applied"]
    if not applied:
        return '<div class="empty">No applied proposals recorded yet.</div>'

    audit_events = read_audit_events(paths)
    rows: list[str] = []
    for proposal in applied[:10]:
        result = measure_applied_proposal_effect(proposal, audit_events)
        tone = "ok" if result["outcome"] == "reduced" else "warn" if result["outcome"] == "no_change" else "bad"
        label = "reduced" if result["outcome"] == "reduced" else "no change" if result["outcome"] == "no_change" else "regressed"
        rows.append(
            "<tr>"
            f"<td><a href=\"/improvements/{quote_plus(str(proposal.get('proposal_id') or ''))}\">{esc(proposal.get('proposal_id'))}</a></td>"
            f"<td>{esc(proposal.get('type'))}</td>"
            f"<td>{esc(result['before_count'])}</td>"
            f"<td>{esc(result['after_count'])}</td>"
            f"<td>{esc(result['delta'])}</td>"
            f"<td><span class=\"pill {tone}\">{esc(label)}</span></td>"
            "</tr>"
        )
    return (
        "<table>"
        "<thead><tr><th>Proposal</th><th>Type</th><th>Before</th><th>After</th><th>Delta</th><th>Effect</th></tr></thead>"
        "<tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_improvements(paths: dict[str, Path], message: str = "", error: str = "", filters: dict[str, str] | None = None) -> bytes:
    active_filters = filters or {}
    runs = load_improvement_runs(paths)
    proposals = flatten_proposals(runs, load_review_state(paths))
    filtered = [proposal for proposal in proposals if proposal_matches_filters(proposal, active_filters)]

    type_counts = Counter(str(proposal.get("type") or "unknown") for proposal in proposals)
    latest_generated = proposals[0].get("_generated_at") if proposals else None
    kpis = "".join([
        kpi_card("Total Proposals", str(len(proposals)), f"Latest run {format_timestamp(latest_generated)}" if latest_generated else "No proposal runs yet", tone="ok" if proposals else "neutral"),
        kpi_card("Visible", str(len(filtered)), "After current filters", tone="neutral"),
        kpi_card("Low Risk", str(sum(1 for proposal in proposals if proposal.get("risk") == "low")), "Candidates easiest to adopt", tone="ok"),
        kpi_card("Prompt Ideas", str(int(type_counts.get("prompt_improvement", 0))), "Reviewer-note driven prompt candidates", tone="warn" if type_counts.get("prompt_improvement", 0) else "neutral"),
    ])

    summary_rows = [
        ("Proposal Runs", str(len(runs))),
        ("Ignore Rule Ideas", str(int(type_counts.get("ignore_rule", 0)))),
        ("Classification Ideas", str(int(type_counts.get("classification_rule", 0)))),
        ("Priority Ideas", str(int(type_counts.get("priority_threshold", 0)))),
        ("Prompt Ideas", str(int(type_counts.get("prompt_improvement", 0)))),
    ]

    body = f"""
    <section class="panel" style="margin-bottom:1rem;">
      <div class="panel-header">
        <div>
          <h2>Applied Proposal Impact</h2>
          <div class="muted">Manual-review volume in the 14 days before and after each applied proposal.</div>
        </div>
      </div>
      <div class="panel-body">
        {render_applied_impact_table(proposals, paths)}
      </div>
    </section>
    <div class="panel" style="margin-bottom:1rem;">
      <div class="panel-body">
        <div class="kpi-grid">{kpis}</div>
      </div>
    </div>
    <div class="grid">
      <section class="panel">
        <div class="panel-header">
          <div>
            <h2>Improvement Proposals</h2>
            <div class="muted">Read-only proposals generated from manual review history, reviewer notes, and repeated queue outcomes.</div>
          </div>
        </div>
        <div class="panel-body">
          {render_improvement_filters(active_filters)}
          {render_improvements_table(filtered)}
        </div>
      </section>
      <aside class="stack">
        {render_metrics_panel('Proposal Mix', 'Current proposal distribution by type.', summary_rows)}
      </aside>
    </div>
    """
    return page_shell("Improvement Proposals", body, message=message, error=error, active_page="improvements")


def render_improvement_detail(paths: dict[str, Path], proposal_id: str, message: str = "", error: str = "") -> bytes:
    proposal = get_review_proposal(paths, proposal_id)
    target_files = proposal.get("target_files", [])
    evidence = proposal.get("evidence", {})
    related_issue_ids = proposal.get("related_issue_ids", [])
    review_note = str(proposal.get("review_note") or "")

    related_html = "".join(f'<span class="pill">{esc(item)}</span>' for item in related_issue_ids[:12])
    target_html = "".join(f'<div class="mono">{esc(item)}</div>' for item in target_files)

    review_event = '<div class="empty">No reviewer decision yet.</div>'
    if proposal.get("status") in {"accepted", "rejected", "deferred"}:
        review_event = (
            '<div class="event">'
            f"<strong>{esc(proposal.get('status'))} by {esc(proposal.get('reviewer') or 'unknown')}</strong>"
            f"<div class=\"muted\">{esc(proposal.get('reviewed_at') or '')}</div>"
            f"<div>{esc(review_note or 'No note provided.')}</div>"
            "</div>"
        )
    if proposal.get("status") == "applied":
        applied = dict(proposal.get("applied") or {})
        review_event = (
            '<div class="event">'
            f"<strong>applied in {esc(applied.get('commit_sha') or 'unknown')}</strong>"
            f"<div class=\"muted\">{esc(applied.get('timestamp') or '')}</div>"
            f"<div>{esc(applied.get('change_summary') or 'No change summary recorded.')}</div>"
            "</div>"
        )

    body = f"""
    <div class="actions" style="margin-bottom:1rem;">
      <a class="button-link ghost" href="/improvements">Back to proposals</a>
    </div>
    <div class="grid">
      <section class="stack">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>{esc(proposal.get('proposal_id'))}</h2>
              <div class="muted">{esc(proposal.get('summary'))}</div>
            </div>
            <div class="actions">
              <span class="pill">{esc(proposal.get('type'))}</span>
              <span class="pill">{esc(proposal.get('status') or 'proposed')}</span>
            </div>
          </div>
          <div class="panel-body stack">
            <div class="meta-grid">
              <div class="meta-box"><h3>Project</h3><div>{esc(proposal.get('project') or 'all')}</div></div>
              <div class="meta-box"><h3>Source</h3><div>{esc(proposal.get('source') or 'unknown')}</div></div>
              <div class="meta-box"><h3>Risk</h3><div>{esc(proposal.get('risk') or 'n/a')}</div></div>
              <div class="meta-box"><h3>Confidence</h3><div>{esc(proposal.get('confidence') or 'n/a')}</div></div>
              <div class="meta-box"><h3>Policy Pack</h3><div>{esc(proposal.get('policy_pack') or 'default')}</div></div>
              <div class="meta-box"><h3>Generated</h3><div class="mono">{esc(proposal.get('_generated_at') or '')}</div></div>
            </div>
            <div class="meta-box">
              <h3>Target Files</h3>
              {target_html or '<div class="empty">No target files recorded.</div>'}
            </div>
            <div class="meta-box">
              <h3>Evidence</h3>
              <pre class="mono">{esc(json.dumps(evidence, indent=2, ensure_ascii=True))}</pre>
            </div>
            <div class="meta-box">
              <h3>Suggested Change</h3>
              <pre class="mono">{esc(json.dumps(proposal.get('suggested_change', {}), indent=2, ensure_ascii=True))}</pre>
            </div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>Review Decision</h2>
              <div class="muted">Review this proposal before any config or prompt change is applied.</div>
            </div>
          </div>
          <div class="panel-body">
            <form method="post" action="/improvements/action" class="stack">
              <input type="hidden" name="proposal_id" value="{esc(proposal_id)}">
              <label>Reviewer
                <input name="reviewer" value="{esc(proposal.get('reviewer') or 'manual')}">
              </label>
              <label>Note
                <textarea name="note" placeholder="Why this proposal should be accepted, deferred, or rejected">{esc(review_note)}</textarea>
              </label>
              <div class="actions">
                <button type="submit" name="action" value="accept">Accept</button>
                <button type="submit" name="action" value="defer" class="alt">Defer</button>
                <button type="submit" name="action" value="reject" class="bad">Reject</button>
              </div>
            </form>
          </div>
        </section>
      </section>
      <aside class="stack">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>Current Review State</h2>
              <div class="muted">Latest reviewer decision for this proposal.</div>
            </div>
          </div>
          <div class="panel-body">
            {review_event}
          </div>
        </section>
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>Related Issues</h2>
              <div class="muted">Examples used to support the proposal.</div>
            </div>
          </div>
          <div class="panel-body">
            {related_html or '<div class="empty">No related issue IDs recorded.</div>'}
          </div>
        </section>
      </aside>
    </div>
    """
    return page_shell(f"Improvement {proposal_id}", body, message=message, error=error, active_page="improvements")


def render_select(name: str, values: list[str], current: str | None, allow_blank: bool = True) -> str:
    options: list[str] = []
    if allow_blank:
        options.append('<option value="">keep current</option>')
    for value in values:
        selected = " selected" if current == value else ""
        options.append(f'<option value="{esc(value)}"{selected}>{esc(value)}</option>')
    return f'<select name="{esc(name)}">{"".join(options)}</select>'


def render_issue_detail(paths: dict[str, Path], issue_id: str, status: str | None, message: str = "", error: str = "") -> bytes:
    resolved_status, path = find_issue(paths, issue_id, status)
    issue = load_issue(path)
    summary = issue_summary(issue, resolved_status)
    metadata = issue.get("metadata", {})
    review = issue.get("review", {})
    manual_history = issue.get("manual_review_history", [])
    pending_actions = ""
    if resolved_status == "pending":
        pending_actions = f"""
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>Review Action</h2>
              <div class="muted">Approve, reject, or ignore without moving files by hand.</div>
            </div>
          </div>
          <div class="panel-body">
            <form method="post" action="/action" class="stack">
              <input type="hidden" name="issue_id" value="{esc(issue_id)}">
              <input type="hidden" name="status" value="{esc(resolved_status)}">
              <label>Reviewer
                <input name="reviewer" value="manual">
              </label>
              <label>Note
                <textarea name="note" placeholder="Why you approved / rejected / ignored this alert"></textarea>
              </label>
              <div class="meta-grid">
                <label>Priority Override
                  {render_select("priority", PRIORITIES, None)}
                </label>
                <label>Danger Override
                  {render_select("danger", DANGERS, None)}
                </label>
              </div>
              <label>Classification Override
                <input name="classification" placeholder="Keep current unless you need to correct it">
              </label>
              <div class="actions">
                <button type="submit" name="action" value="approve">Approve</button>
                <button type="submit" name="action" value="reject" class="warn">Reject</button>
                <button type="submit" name="action" value="ignore" class="bad">Ignore</button>
              </div>
            </form>
          </div>
        </section>
        """

    history_blocks = []
    for entry in reversed(manual_history[-12:]):
        history_blocks.append(
            '<div class="event">'
            f"<strong>{esc(entry.get('action'))} by {esc(entry.get('reviewer'))}</strong>"
            f"<div class=\"muted\">{esc(entry.get('timestamp'))}</div>"
            f"<div>{esc(entry.get('note') or '')}</div>"
            "</div>"
        )

    body = f"""
    <div class="actions" style="margin-bottom:1rem;">
      <a class="button-link ghost" href="/?status={esc(resolved_status)}">Back to {esc(resolved_status)}</a>
      <a class="button-link alt" href="{esc(metadata.get('link', '#'))}" target="_blank" rel="noreferrer">Open in Sentry</a>
    </div>
    <div class="grid">
      <section class="stack">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>{esc(issue.get('issue_id'))}</h2>
              <div class="muted">{esc(metadata.get('title'))}</div>
            </div>
            <div class="actions">
              <span class="pill {esc(str(summary.get('priority') or '').lower())}">{esc(summary.get('priority'))}</span>
              <span class="pill">{esc(summary.get('classification'))}</span>
            </div>
          </div>
          <div class="panel-body stack">
            <div class="meta-grid">
              <div class="meta-box"><h3>Status</h3><div>{esc(resolved_status)}</div></div>
              <div class="meta-box"><h3>Suggested Team</h3><div>{esc(summary.get('review_team'))}</div></div>
              <div class="meta-box"><h3>Project</h3><div>{esc(summary.get('project'))}</div></div>
              <div class="meta-box"><h3>Danger</h3><div>{esc(summary.get('danger'))}</div></div>
              <div class="meta-box"><h3>Count / Users</h3><div>{esc(summary.get('count'))} / {esc(summary.get('users'))}</div></div>
              <div class="meta-box"><h3>Last Seen</h3><div class="mono">{esc(summary.get('last_seen'))}</div></div>
            </div>
            <div class="meta-box">
              <h3>AI Review</h3>
              <div>Decision: <strong>{esc(review.get('decision'))}</strong> · Confidence: {esc(review.get('confidence'))}</div>
              <div class="reasoning" style="margin-top:0.6rem;">{esc(review.get('reasoning'))}</div>
            </div>
            <div class="meta-box">
              <h3>Raw Paths</h3>
              <div class="mono">{esc(path)}</div>
            </div>
          </div>
        </section>
        {pending_actions}
      </section>
      <aside class="stack">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>Manual History</h2>
              <div class="muted">Recent overrides and notes for this issue.</div>
            </div>
          </div>
          <div class="panel-body">
            {'<div class="stack">' + ''.join(history_blocks) + '</div>' if history_blocks else '<div class="empty">No manual review history yet.</div>'}
          </div>
        </section>
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>Impact Snapshot</h2>
              <div class="muted">Key fields from the review result.</div>
            </div>
          </div>
          <div class="panel-body stack">
            <div class="meta-box"><h3>User Impact</h3><pre class="mono">{esc(json.dumps(review.get('user_impact', {}), indent=2))}</pre></div>
            <div class="meta-box"><h3>Urgency</h3><pre class="mono">{esc(json.dumps(review.get('urgency', {}), indent=2))}</pre></div>
          </div>
        </section>
      </aside>
    </div>
    """
    return page_shell(f"Issue {issue_id}", body, message=message, error=error, active_page="queue")


class ReviewWebHandler(BaseHTTPRequestHandler):
    server: "ReviewWebServer"

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_html(self, content: bytes, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def parse_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        parsed = parse_qs(raw, keep_blank_values=True)
        return {key: values[-1] if values else "" for key, values in parsed.items()}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
        message = query.get("message", "")
        error = query.get("error", "")

        if parsed.path == "/":
            filters = {
                "status": query.get("status", "pending"),
                "project": query.get("project", ""),
                "priority": query.get("priority", ""),
                "team": query.get("team", ""),
            }
            content = render_home(self.server.paths, filters, message=message, error=error)
            self.send_html(content)
            return

        if parsed.path == "/metrics":
            content = render_metrics(self.server.paths, self.server.config_file, message=message, error=error)
            self.send_html(content)
            return

        if parsed.path == "/improvements":
            filters = {
                "type": query.get("type", ""),
                "project": query.get("project", ""),
                "status": query.get("status", ""),
                "risk": query.get("risk", ""),
            }
            content = render_improvements(self.server.paths, message=message, error=error, filters=filters)
            self.send_html(content)
            return

        if parsed.path.startswith("/improvements/"):
            proposal_id = parsed.path.rsplit("/", 1)[-1]
            try:
                content = render_improvement_detail(self.server.paths, proposal_id, message=message, error=error)
            except FileNotFoundError as exc:
                content = page_shell("Not Found", '<div class="panel"><div class="panel-body empty">Proposal not found.</div></div>', error=str(exc), active_page="improvements")
                self.send_html(content, status=HTTPStatus.NOT_FOUND)
                return
            self.send_html(content)
            return

        if parsed.path.startswith("/issue/"):
            issue_id = parsed.path.rsplit("/", 1)[-1]
            status = query.get("status")
            try:
                content = render_issue_detail(self.server.paths, issue_id, status, message=message, error=error)
            except FileNotFoundError as exc:
                content = page_shell("Not Found", '<div class="panel"><div class="panel-body empty">Issue not found.</div></div>', error=str(exc), active_page="queue")
                self.send_html(content, status=HTTPStatus.NOT_FOUND)
                return
            self.send_html(content)
            return

        content = page_shell("Not Found", '<div class="panel"><div class="panel-body empty">Page not found.</div></div>', active_page="queue")
        self.send_html(content, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        form = self.parse_form()

        if parsed.path == "/action":
            issue_id = form.get("issue_id", "")
            status = form.get("status", "pending")
            action = form.get("action", "")
            if action not in ACTION_TO_QUEUE:
                self.redirect(f"/issue/{issue_id}?status={status}&error={quote_plus('Invalid action')}")
                return
            try:
                record_action(
                    self.server.paths,
                    issue_id=issue_id,
                    action=action,
                    reviewer=form.get("reviewer", "manual") or "manual",
                    note=form.get("note", ""),
                    priority=form.get("priority") or None,
                    classification=form.get("classification") or None,
                    danger=form.get("danger") or None,
                )
                target_status = ACTION_TO_QUEUE[action]
                self.redirect(f"/?status={target_status}&message={quote_plus(f'{action.title()}d {issue_id}')}")
            except Exception as exc:
                self.redirect(f"/issue/{issue_id}?status={status}&error={quote_plus(str(exc))}")
            return

        if parsed.path == "/dispatch":
            send = form.get("send", "0") == "1"
            exit_code = dispatch_approved(self.server.paths, self.server.config_file, dry_run=not send, send=send)
            if exit_code == 0:
                mode = "sent to Teams" if send else "dry-run complete"
                self.redirect("/?status=approved&message=" + quote_plus(f"Dispatch {mode}"))
            else:
                self.redirect("/?status=approved&error=" + quote_plus(f"Dispatch failed with exit code {exit_code}"))
            return

        if parsed.path == "/improvements/action":
            proposal_id = form.get("proposal_id", "")
            action = form.get("action", "")
            status = (
                "accepted" if action == "accept"
                else "rejected" if action == "reject"
                else "deferred" if action == "defer"
                else ""
            )
            if not proposal_id or not status:
                self.redirect("/improvements?error=" + quote_plus("Invalid proposal action"))
                return
            try:
                review_improvement_proposal(
                    self.server.paths,
                    proposal_id=proposal_id,
                    status=status,
                    reviewer=form.get("reviewer", "manual") or "manual",
                    note=form.get("note", ""),
                )
                self.redirect(
                    f"/improvements/{quote_plus(proposal_id)}?message="
                    + quote_plus(f"{status.title()} {proposal_id}")
                )
            except Exception as exc:
                self.redirect(f"/improvements/{quote_plus(proposal_id)}?error={quote_plus(str(exc))}")
            return

        self.redirect("/?error=" + quote_plus("Unsupported action"))


class ReviewWebServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler], *, paths: dict[str, Path], config_file: str) -> None:
        super().__init__(server_address, handler_class)
        self.paths = paths
        self.config_file = config_file


def main() -> int:
    args = parse_args()
    paths = load_paths(args.config)
    ensure_dirs(paths)

    server = ReviewWebServer((args.host, args.port), ReviewWebHandler, paths=paths, config_file=args.config)
    print(f"Review UI listening on http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
