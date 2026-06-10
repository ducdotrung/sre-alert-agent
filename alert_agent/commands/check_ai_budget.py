"""Check AI spend against configured budgets and optionally send Teams alerts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Any, Sequence, TextIO

from alert_agent.core.config_loader import load_agent_config
from alert_agent.core.teams import send_to_teams
from alert_agent.core.usage_metrics import filter_records_for_date, iter_month_records, summarize_records
from alert_agent.monitoring.common import is_enabled, print_payload


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [BudgetMonitor] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent_config.yaml', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Print alerts without sending')
    return parser.parse_args(argv)


def parse_thresholds(value: Any) -> list[float]:
    """Parse comma-separated or list thresholds into sorted percentages."""
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = str(value or "").split(",")

    thresholds: list[float] = []
    for raw in raw_values:
        try:
            threshold = float(str(raw).strip())
        except ValueError:
            continue
        if threshold <= 0:
            continue
        thresholds.append(threshold)

    return sorted(set(thresholds))


def read_state(path: Path) -> dict[str, Any]:
    """Load alert deduplication state."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return {}


def write_state(path: Path, state: dict[str, Any]) -> None:
    """Persist alert deduplication state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding='utf-8')


def highest_crossed_threshold(total_cost: float, budget_usd: float, thresholds: list[float]) -> float | None:
    """Return the highest threshold reached for the given cost/budget pair."""
    if budget_usd <= 0:
        return None

    ratio = (total_cost / budget_usd) * 100
    crossed = [threshold for threshold in thresholds if ratio >= threshold]
    return crossed[-1] if crossed else None


def top_agents_text(summary: dict[str, Any]) -> str:
    """Build a compact top-agent string."""
    by_agent = dict(summary.get("by_agent", {}))
    if not by_agent:
        return "No AI calls recorded."

    agents = sorted(by_agent.items(), key=lambda item: item[1]["cost"], reverse=True)
    parts = [f"{agent}: ${stats['cost']:.4f} ({stats['calls']} calls)" for agent, stats in agents[:3]]
    return "; ".join(parts)


def top_operations_text(summary: dict[str, Any]) -> str:
    """Build a compact operation summary."""
    by_operation = dict(summary.get("by_operation", {}))
    if not by_operation:
        return "No operations recorded."

    operations = sorted(by_operation.items(), key=lambda item: item[1], reverse=True)
    parts = [f"{operation}: {count}" for operation, count in operations[:3]]
    return "; ".join(parts)


def build_budget_message_card(period_name: str, period_key: str, threshold: float, budget_usd: float, summary: dict[str, Any]) -> dict[str, Any]:
    """Build a Teams MessageCard for a budget threshold alert."""
    total_cost = float(summary["total_cost"])
    total_calls = int(summary["total_calls"])
    total_tokens = int(summary["total_tokens"])
    usage_percent = (total_cost / budget_usd) * 100 if budget_usd > 0 else 0.0

    severity = "warning"
    color = "FFB900"
    if usage_percent >= 100:
        severity = "critical"
        color = "E81123"
    elif usage_percent >= 80:
        severity = "high"
        color = "F7630C"

    summary_text = (
        f"AI {period_name} budget reached {usage_percent:.1f}% "
        f"(${total_cost:.6f} of ${budget_usd:.2f})"
    )

    return {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": summary_text,
        "themeColor": color,
        "title": f"AI Budget Alert [{severity.upper()}] {period_name.title()} {threshold:.0f}%",
        "sections": [
            {
                "activityTitle": "Budget Status",
                "text": summary_text,
                "markdown": True,
            },
            {
                "facts": [
                    {"name": "Period", "value": f"{period_name} ({period_key})"},
                    {"name": "Threshold", "value": f"{threshold:.0f}%"},
                    {"name": "Budget", "value": f"${budget_usd:.2f}"},
                    {"name": "Current Spend", "value": f"${total_cost:.6f}"},
                    {"name": "AI Calls", "value": str(total_calls)},
                    {"name": "Tokens", "value": str(total_tokens)},
                    {"name": "Cost Source", "value": ", ".join(sorted(dict(summary.get("by_source", {})).keys())) or "unknown"},
                ]
            },
            {
                "activityTitle": "Top Agents",
                "text": top_agents_text(summary),
                "markdown": True,
            },
            {
                "activityTitle": "Top Operations",
                "text": top_operations_text(summary),
                "markdown": True,
            },
        ],
    }


def print_budget_status(
    period_name: str,
    period_key: str,
    budget_usd: float,
    threshold: float | None,
    summary: dict[str, Any],
) -> None:
    """Print a compact human-readable budget summary."""
    total_cost = float(summary['total_cost'])
    usage_percent = (total_cost / budget_usd) * 100 if budget_usd > 0 else 0.0
    threshold_text = "no threshold crossed" if threshold is None else f"threshold {threshold:.0f}% reached"
    logger.info(
        "%s budget %s: $%.6f / $%.2f (%.1f%%)",
        period_name.title(),
        threshold_text,
        total_cost,
        budget_usd,
        usage_percent,
    )
    logger.info(
        "%s summary [%s]: calls=%s tokens=%s top_agents=%s top_ops=%s",
        period_name.title(),
        period_key,
        summary['total_calls'],
        summary['total_tokens'],
        top_agents_text(summary),
        top_operations_text(summary),
    )


def maybe_send_budget_alert(
    state: dict[str, Any],
    state_key: str,
    period_key: str,
    budget_usd: float,
    threshold: float | None,
    summary: dict[str, Any],
    config: dict[str, Any],
    dry_run: bool,
    stdout: TextIO | None = None,
) -> bool:
    """Emit a budget alert when a new threshold is crossed."""
    if threshold is None:
        state.pop(state_key, None)
        return False

    previous = state.get(state_key, {})
    previous_period = str(previous.get("period") or "")
    previous_threshold = previous.get("last_threshold")
    if previous_period == period_key and previous_threshold == threshold:
        logger.info(
            "Budget alert already sent for %s at %.0f%% in %s",
            state_key,
            threshold,
            period_key,
        )
        return False

    card = build_budget_message_card(state_key, period_key, threshold, budget_usd, summary)
    webhook_url = str(config.get('teams_webhook_url') or "")
    timeout = int(config.get('timeout', 15))

    if dry_run:
        logger.info("Budget alert would fire for %s at %.0f%%", state_key, threshold)
        print_payload(card, stdout)
        return True

    if not webhook_url:
        logger.warning("Budget alert reached %.0f%% for %s, but no Teams webhook is configured", threshold, state_key)
        return False

    response = send_to_teams(webhook_url, card, timeout)
    logger.info("Budget alert sent for %s at %.0f%% (%s)", state_key, threshold, response[:120])

    state[state_key] = {
        "period": period_key,
        "last_threshold": threshold,
        "last_alert_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "current_cost": summary["total_cost"],
        "budget_usd": budget_usd,
    }
    return True


def run(config: dict[str, Any], *, dry_run: bool = False, stdout: TextIO | None = None) -> int:
    """Execute the budget monitor using a resolved config dict."""
    if not is_enabled(config.get('enabled', 'true')):
        logger.info("Budget monitor disabled")
        return 0

    metrics_dir = Path(config.get('metrics_dir', './output/metrics'))
    state_file = str(config.get('state_file') or "").strip()
    state_path = Path(state_file) if state_file else metrics_dir / 'budget_alert_state.json'
    thresholds = parse_thresholds(config.get('thresholds_percent', '50,80,100'))

    today = dt.datetime.now(dt.timezone.utc).date()
    month_key = today.strftime('%Y-%m')
    month_records = iter_month_records(metrics_dir, month_key)
    day_records = filter_records_for_date(month_records, today)

    monthly_summary = summarize_records(month_records)
    daily_summary = summarize_records(day_records)

    monthly_budget = float(config.get('monthly_budget_usd', 0) or 0)
    daily_budget = float(config.get('daily_budget_usd', 0) or 0)

    monthly_threshold = highest_crossed_threshold(float(monthly_summary['total_cost']), monthly_budget, thresholds)
    daily_threshold = highest_crossed_threshold(float(daily_summary['total_cost']), daily_budget, thresholds)

    print_budget_status('monthly', month_key, monthly_budget, monthly_threshold, monthly_summary)
    print_budget_status('daily', today.isoformat(), daily_budget, daily_threshold, daily_summary)

    state = read_state(state_path)
    sent_any = False
    sent_any = maybe_send_budget_alert(
        state,
        'monthly',
        month_key,
        monthly_budget,
        monthly_threshold,
        monthly_summary,
        config,
        dry_run,
        stdout,
    ) or sent_any
    sent_any = maybe_send_budget_alert(
        state,
        'daily',
        today.isoformat(),
        daily_budget,
        daily_threshold,
        daily_summary,
        config,
        dry_run,
        stdout,
    ) or sent_any

    if not dry_run:
        write_state(state_path, state)
    return 2 if sent_any else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_agent_config('monitor', args.config)
    return run(config, dry_run=args.dry_run)


if __name__ == '__main__':
    raise SystemExit(main())
