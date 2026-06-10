"""Send a compact daily operational summary to Teams."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
from pathlib import Path
from typing import Any, Sequence, TextIO

from alert_agent.core.config_loader import load_agent_config
from alert_agent.core.health_monitor import read_json_file, write_json_file
from alert_agent.core.teams import send_to_teams
from alert_agent.core.usage_metrics import filter_records_for_date, iter_month_records, summarize_records
from alert_agent.monitoring.common import is_enabled, print_payload


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [DailySummary] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent_config.yaml', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Print summary without sending')
    parser.add_argument('--force', action='store_true', help='Ignore send-after-hour and already-sent checks')
    return parser.parse_args(argv)


def now_utc() -> dt.datetime:
    """Current UTC time."""
    return dt.datetime.now(dt.timezone.utc)


def queue_count(directory: Path, pattern: str) -> int:
    """Count queue files."""
    if not directory.exists():
        return 0
    return len(list(directory.glob(pattern)))


def top_agents_text(summary: dict[str, Any]) -> str:
    """Format top agents from usage summary."""
    by_agent = dict(summary.get("by_agent", {}))
    if not by_agent:
        return "No AI calls recorded."
    agents = sorted(by_agent.items(), key=lambda item: item[1]["cost"], reverse=True)
    return "; ".join(
        f"{agent}: ${stats['cost']:.4f} ({stats['calls']} calls)"
        for agent, stats in agents[:3]
    )


def top_operations_text(summary: dict[str, Any]) -> str:
    """Format top operations from usage summary."""
    by_operation = dict(summary.get("by_operation", {}))
    if not by_operation:
        return "No AI operations recorded."
    operations = sorted(by_operation.items(), key=lambda item: item[1], reverse=True)
    return "; ".join(f"{name}: {count}" for name, count in operations[:5])


def build_summary_card(
    summary_date: dt.date,
    usage_summary: dict[str, Any],
    pipeline_state: dict[str, Any],
    queue_summary: dict[str, int],
) -> dict[str, Any]:
    """Build the Teams card for the daily summary."""
    total_cost = float(usage_summary["total_cost"])
    total_calls = int(usage_summary["total_calls"])
    total_tokens = int(usage_summary["total_tokens"])
    pipeline_status = str(pipeline_state.get("status") or "unknown")
    pipeline_updated = str(pipeline_state.get("updated_at") or "unknown")

    summary_text = (
        f"Daily monitoring summary for {summary_date.isoformat()}: "
        f"${total_cost:.6f}, {total_calls} AI calls, status `{pipeline_status}`."
    )

    return {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": summary_text,
        "themeColor": "0078D4",
        "title": f"Daily Monitoring Summary {summary_date.isoformat()}",
        "sections": [
            {
                "activityTitle": "Daily Summary",
                "text": summary_text,
                "markdown": True,
            },
            {
                "facts": [
                    {"name": "Date", "value": summary_date.isoformat()},
                    {"name": "AI Cost", "value": f"${total_cost:.6f}"},
                    {"name": "AI Calls", "value": str(total_calls)},
                    {"name": "Tokens", "value": str(total_tokens)},
                    {"name": "Pipeline Status", "value": pipeline_status},
                    {"name": "Pipeline Updated", "value": pipeline_updated},
                ],
            },
            {
                "activityTitle": "Queue Snapshot",
                "text": (
                    f"pending={queue_summary['pending']}; approved={queue_summary['approved']}; "
                    f"recommendations={queue_summary['recommendations']}; sent={queue_summary['sent']}"
                ),
                "markdown": True,
            },
            {
                "activityTitle": "Top Agents",
                "text": top_agents_text(usage_summary),
                "markdown": True,
            },
            {
                "activityTitle": "Top Operations",
                "text": top_operations_text(usage_summary),
                "markdown": True,
            },
        ],
    }


def run(
    config: dict[str, Any],
    *,
    dry_run: bool = False,
    force: bool = False,
    stdout: TextIO | None = None,
) -> int:
    """Execute the daily summary command using a resolved config dict."""
    if not is_enabled(config.get('enabled', 'true')):
        logger.info("Daily summary disabled")
        return 0

    current = now_utc()
    send_after_hour = int(config.get('send_after_hour_utc', 23) or 23)
    if not force and current.hour < send_after_hour:
        logger.info("Daily summary not due yet (current hour %s < send-after %s UTC)", current.hour, send_after_hour)
        return 0

    metrics_dir = Path(config.get('metrics_dir', './output/metrics'))
    output_dir = Path(config.get('output_dir', './output'))
    state_file = str(config.get('state_file') or '').strip()
    state_path = Path(state_file) if state_file else metrics_dir / 'daily_summary_state.json'
    state = read_json_file(state_path)

    summary_date = current.date()
    summary_key = summary_date.isoformat()
    if not force and str(state.get('sent_for_date') or '') == summary_key:
        logger.info("Daily summary already sent for %s", summary_key)
        return 0

    month_key = current.strftime('%Y-%m')
    month_records = iter_month_records(metrics_dir, month_key)
    day_records = filter_records_for_date(month_records, summary_date)
    usage_summary = summarize_records(day_records)
    pipeline_state = read_json_file(metrics_dir / 'pipeline_state.json')
    queue_summary = {
        'pending': queue_count(output_dir / 'alerts' / 'pending', '*.json'),
        'approved': queue_count(output_dir / 'alerts' / 'approved', '*.json'),
        'recommendations': queue_count(output_dir / 'alerts' / 'recommendations', '*.md'),
        'sent': queue_count(output_dir / 'alerts' / 'sent', '*.md'),
    }

    card = build_summary_card(summary_date, usage_summary, pipeline_state, queue_summary)
    webhook_url = str(config.get('teams_webhook_url') or '')
    timeout = int(config.get('timeout', 15))

    if dry_run:
        print_payload(card, stdout)
        return 2

    if not webhook_url:
        logger.warning("Daily summary skipped because no Teams webhook is configured")
        return 0

    response = send_to_teams(webhook_url, card, timeout)
    logger.info("Daily summary sent (%s)", response[:120])
    write_json_file(
        state_path,
        {
            'sent_for_date': summary_key,
            'sent_at': current.isoformat(),
        },
    )
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_agent_config('daily_summary', args.config)
    return run(config, dry_run=args.dry_run, force=args.force)


if __name__ == '__main__':
    raise SystemExit(main())
