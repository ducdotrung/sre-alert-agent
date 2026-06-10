#!/usr/bin/env python3
"""Generate a static HTML dashboard from monitoring files."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alert_agent.core.config_loader import load_agent_config
from alert_agent.core.health_monitor import read_json_file
from alert_agent.core.usage_metrics import filter_records_for_date, iter_month_records, summarize_records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent_config.yaml', help='Config file path')
    parser.add_argument('--output', help='Override output HTML path')
    return parser.parse_args()


def now_utc() -> dt.datetime:
    """Current UTC time."""
    return dt.datetime.now(dt.timezone.utc)


def queue_count(directory: Path, pattern: str) -> int:
    """Count queue files for a directory."""
    if not directory.exists():
        return 0
    return len(list(directory.glob(pattern)))


def oldest_file_info(directory: Path, pattern: str) -> str:
    """Return oldest file name and age for a queue."""
    if not directory.exists():
        return "none"
    files = list(directory.glob(pattern))
    if not files:
        return "none"
    oldest = min(files, key=lambda path: path.stat().st_mtime)
    modified_at = dt.datetime.fromtimestamp(oldest.stat().st_mtime, tz=dt.timezone.utc)
    age_hours = (now_utc() - modified_at).total_seconds() / 3600
    return f"{oldest.name} ({age_hours:.1f}h old)"


def render_kpi(title: str, value: str, tone: str = "neutral") -> str:
    """Render one dashboard KPI block."""
    return (
        f'<div class="kpi {tone}">'
        f'<div class="kpi-title">{html.escape(title)}</div>'
        f'<div class="kpi-value">{html.escape(value)}</div>'
        '</div>'
    )


def render_table(title: str, headers: list[str], rows: list[list[str]]) -> str:
    """Render a simple HTML table section."""
    header_html = ''.join(f'<th>{html.escape(header)}</th>' for header in headers)
    if rows:
        row_html = ''.join(
            '<tr>' + ''.join(f'<td>{html.escape(cell)}</td>' for cell in row) + '</tr>'
            for row in rows
        )
    else:
        row_html = f'<tr><td colspan="{len(headers)}">No data</td></tr>'

    return (
        '<section class="panel">'
        f'<h2>{html.escape(title)}</h2>'
        '<div class="table-wrap">'
        '<table>'
        f'<thead><tr>{header_html}</tr></thead>'
        f'<tbody>{row_html}</tbody>'
        '</table>'
        '</div>'
        '</section>'
    )


def render_fact_panel(title: str, facts: list[tuple[str, str]]) -> str:
    """Render a compact fact grid panel."""
    fact_html = ''.join(
        '<div class="fact">'
        f'<div class="fact-label">{html.escape(label)}</div>'
        f'<div class="fact-value">{html.escape(value)}</div>'
        '</div>'
        for label, value in facts
    )
    return (
        '<section class="panel">'
        f'<h2>{html.escape(title)}</h2>'
        f'<div class="facts-grid">{fact_html}</div>'
        '</section>'
    )


def render_queue_panel(queue_summary: dict[str, str]) -> str:
    """Render queue snapshot as cards instead of a wide table."""
    items = [
        ('Pending', queue_summary['pending'], queue_summary['pending_oldest']),
        ('Approved', queue_summary['approved'], queue_summary['approved_oldest']),
        ('Recommendations', queue_summary['recommendations'], queue_summary['recommendations_oldest']),
        ('Sent', queue_summary['sent'], queue_summary['sent_oldest']),
    ]
    cards = ''.join(
        '<div class="queue-card">'
        f'<div class="queue-name">{html.escape(name)}</div>'
        f'<div class="queue-count">{html.escape(count)}</div>'
        f'<div class="queue-meta">{html.escape(oldest)}</div>'
        '</div>'
        for name, count, oldest in items
    )
    return (
        '<section class="panel">'
        '<h2>Queue Snapshot</h2>'
        f'<div class="queue-grid">{cards}</div>'
        '</section>'
    )


def build_dashboard_html(
    generated_at: dt.datetime,
    usage_summary: dict[str, Any],
    pipeline_state: dict[str, Any],
    queue_summary: dict[str, str],
    alert_states: dict[str, dict[str, Any]],
) -> str:
    """Build the final static dashboard HTML."""
    pipeline_status = str(pipeline_state.get('status') or 'unknown')
    status_tone = 'ok' if pipeline_status == 'completed' else 'warn'
    kpis = ''.join([
        render_kpi('Pipeline Status', pipeline_status, status_tone),
        render_kpi('Daily AI Cost', f"${float(usage_summary['total_cost']):.6f}", 'neutral'),
        render_kpi('Daily AI Calls', str(int(usage_summary['total_calls'])), 'neutral'),
        render_kpi('Daily Tokens', str(int(usage_summary['total_tokens'])), 'neutral'),
        render_kpi('Pending Queue', queue_summary['pending'], 'warn' if int(queue_summary['pending']) > 0 else 'ok'),
        render_kpi('Approved Queue', queue_summary['approved'], 'warn' if int(queue_summary['approved']) > 0 else 'ok'),
    ])

    by_agent_rows = [
        [agent, str(stats['calls']), f"${stats['cost']:.6f}"]
        for agent, stats in sorted(
            dict(usage_summary.get('by_agent', {})).items(),
            key=lambda item: item[1]['cost'],
            reverse=True,
        )
    ]

    by_operation_rows = [
        [operation, str(count)]
        for operation, count in sorted(
            dict(usage_summary.get('by_operation', {})).items(),
            key=lambda item: item[1],
            reverse=True,
        )[:10]
    ]

    pipeline_facts = [
        ('Run ID', str(pipeline_state.get('run_id') or 'unknown')),
        ('Status', pipeline_status),
        ('Updated', str(pipeline_state.get('updated_at') or 'unknown')),
        ('Failure Stage', str(pipeline_state.get('failure_stage') or '-')),
        ('Triaged', str(pipeline_state.get('triaged', 0))),
        ('Approved', str(pipeline_state.get('approved', 0))),
        ('Pending', str(pipeline_state.get('pending', 0))),
        ('Recommendations', str(pipeline_state.get('recommendations', 0))),
        ('Sent', str(pipeline_state.get('sent', 0))),
    ]

    alert_rows: list[list[str]] = []
    for state_name, payload in alert_states.items():
        if not payload:
            alert_rows.append([state_name, 'none', 'none'])
            continue
        for key, value in payload.items():
            if not isinstance(value, dict):
                continue
            alert_rows.append([
                f'{state_name}:{key}',
                str(value.get('marker') or value.get('period') or 'n/a'),
                str(value.get('last_alert_at') or value.get('sent_at') or 'n/a'),
            ])

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SRE Alert Agent Dashboard</title>
  <style>
    :root {{
      --bg: #f2efe8;
      --panel: #fffdf8;
      --ink: #1e2228;
      --muted: #6d737c;
      --accent: #0b6e4f;
      --warn: #b5521f;
      --border: #d9d1c3;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background:
        radial-gradient(circle at top right, rgba(11, 110, 79, 0.12), transparent 28%),
        linear-gradient(180deg, #f8f4ec 0%, var(--bg) 100%);
      color: var(--ink);
    }}
    .shell {{
      max-width: 1360px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}
    header {{
      margin-bottom: 24px;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--border);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 2.2rem;
      line-height: 1.1;
    }}
    .sub {{
      color: var(--muted);
      font-size: 1rem;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }}
    .kpi {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 16px;
      min-height: 120px;
      box-shadow: 0 10px 24px rgba(21, 24, 29, 0.04);
    }}
    .kpi.ok {{ border-color: rgba(11, 110, 79, 0.25); }}
    .kpi.warn {{ border-color: rgba(181, 82, 31, 0.25); }}
    .kpi-title {{
      color: var(--muted);
      font-size: 0.95rem;
      margin-bottom: 10px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .kpi-value {{
      font-size: 1.75rem;
      line-height: 1.1;
      font-weight: 600;
      overflow-wrap: anywhere;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(320px, 0.95fr);
      gap: 18px;
      align-items: start;
    }}
    .stack {{
      display: grid;
      gap: 18px;
      min-width: 0;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 10px 24px rgba(21, 24, 29, 0.04);
    }}
    .panel h2 {{
      margin: 0 0 14px;
      font-size: 1.2rem;
    }}
    .table-wrap {{
      width: 100%;
      overflow-x: auto;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
      min-width: 0;
    }}
    th, td {{
      text-align: left;
      padding: 10px 8px;
      border-bottom: 1px solid rgba(217, 209, 195, 0.7);
      vertical-align: top;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    th {{
      color: var(--muted);
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      font-size: 0.8rem;
    }}
    .facts-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .fact {{
      padding: 12px 14px;
      border: 1px solid rgba(217, 209, 195, 0.8);
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.35);
      min-width: 0;
    }}
    .fact-label {{
      color: var(--muted);
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 8px;
    }}
    .fact-value {{
      font-size: 1rem;
      line-height: 1.35;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .queue-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .queue-card {{
      padding: 14px;
      border: 1px solid rgba(217, 209, 195, 0.8);
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.35);
      min-width: 0;
    }}
    .queue-name {{
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 8px;
    }}
    .queue-count {{
      font-size: 1.5rem;
      font-weight: 600;
      margin-bottom: 8px;
    }}
    .queue-meta {{
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.35;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    footer {{
      margin-top: 24px;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    @media (max-width: 1200px) {{
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .facts-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 900px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .grid {{ grid-template-columns: 1fr; }}
      .facts-grid {{ grid-template-columns: 1fr; }}
      .queue-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <h1>Monitoring Dashboard</h1>
      <div class="sub">Generated at {html.escape(generated_at.isoformat())} UTC</div>
    </header>
    <div class="grid">{kpis}</div>
    <div class="layout">
      <div class="stack">
        {render_fact_panel('Pipeline State', pipeline_facts)}
        {render_queue_panel(queue_summary)}
        {render_table('Top Agents', ['Agent', 'Calls', 'Cost'], by_agent_rows)}
      </div>
      <div class="stack">
        {render_table('Top Operations', ['Operation', 'Calls'], by_operation_rows)}
        {render_table('Alert State', ['State', 'Marker', 'Last Alert'], alert_rows)}
      </div>
    </div>
    <footer>
      Static file generated from `output/metrics/` and `output/alerts/`. Refresh by re-running `python3 scripts/generate_dashboard.py`.
    </footer>
  </div>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    config = load_agent_config('daily_summary', args.config)
    metrics_dir = Path(config.get('metrics_dir', './output/metrics'))
    output_dir = Path(config.get('output_dir', './output'))
    output_path = Path(args.output) if args.output else metrics_dir / 'dashboard.html'

    current = now_utc()
    month_records = iter_month_records(metrics_dir, current.strftime('%Y-%m'))
    day_records = filter_records_for_date(month_records, current.date())
    usage_summary = summarize_records(day_records)

    pipeline_state = read_json_file(metrics_dir / 'pipeline_state.json')
    queue_summary = {
        'pending': str(queue_count(output_dir / 'alerts' / 'pending', '*.json')),
        'approved': str(queue_count(output_dir / 'alerts' / 'approved', '*.json')),
        'recommendations': str(queue_count(output_dir / 'alerts' / 'recommendations', '*.md')),
        'sent': str(queue_count(output_dir / 'alerts' / 'sent', '*.md')),
        'pending_oldest': oldest_file_info(output_dir / 'alerts' / 'pending', '*.json'),
        'approved_oldest': oldest_file_info(output_dir / 'alerts' / 'approved', '*.json'),
        'recommendations_oldest': oldest_file_info(output_dir / 'alerts' / 'recommendations', '*.md'),
        'sent_oldest': oldest_file_info(output_dir / 'alerts' / 'sent', '*.md'),
    }
    alert_states = {
        'budget': read_json_file(metrics_dir / 'budget_alert_state.json'),
        'health': read_json_file(metrics_dir / 'health_alert_state.json'),
        'queue': read_json_file(metrics_dir / 'queue_alert_state.json'),
        'daily_summary': read_json_file(metrics_dir / 'daily_summary_state.json'),
    }

    dashboard_html = build_dashboard_html(current, usage_summary, pipeline_state, queue_summary, alert_states)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dashboard_html, encoding='utf-8')
    print(output_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
