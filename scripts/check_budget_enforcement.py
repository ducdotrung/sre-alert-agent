#!/usr/bin/env python3
"""Evaluate whether budget enforcement should activate for the current period."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alert_agent.core.config_loader import load_agent_config
from alert_agent.core.teams import send_to_teams
from alert_agent.core.usage_metrics import filter_records_for_date, iter_month_records, summarize_records


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [BudgetEnforcement] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


VALID_MODES = {
    'warn_only',
    'disable_recommendation_ai',
    'disable_all_ai',
}

VALID_PERIODS = {
    'monthly',
    'daily',
    'either',
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent_config.yaml', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Print state-change alerts without sending')
    return parser.parse_args()


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return {}


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding='utf-8')


def reason_text(reason: str) -> str:
    mapping = {
        'disabled': 'Budget enforcement is disabled.',
        'monthly_exceeded': 'Monthly budget has been exceeded.',
        'daily_exceeded': 'Daily budget has been exceeded.',
        'daily_and_monthly_exceeded': 'Daily and monthly budgets have both been exceeded.',
        'within_budget': 'Spend is within budget.',
        'daily_ok': 'Daily spend is within budget.',
        'monthly_ok': 'Monthly spend is within budget.',
    }
    return mapping.get(reason, reason.replace('_', ' '))


def build_state_change_card(payload: dict[str, Any], transition: str) -> dict[str, Any]:
    active = bool(payload.get('active'))
    mode = str(payload.get('mode') or 'warn_only')
    reason = str(payload.get('reason') or 'unknown')
    period = str(payload.get('period') or 'either')
    daily_cost = float(payload.get('daily_cost_usd') or 0)
    daily_budget = float(payload.get('daily_budget_usd') or 0)
    monthly_cost = float(payload.get('monthly_cost_usd') or 0)
    monthly_budget = float(payload.get('monthly_budget_usd') or 0)

    if active:
        title = f"Budget Enforcement Activated [{mode}]"
        summary = f"{reason_text(reason)} Enforcement mode `{mode}` is active."
        color = "E81123" if mode == "disable_all_ai" else "F7630C"
    else:
        title = "Budget Enforcement Cleared"
        summary = "Budget enforcement is no longer active. Normal pipeline behavior has resumed."
        color = "107C10"

    return {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": summary,
        "themeColor": color,
        "title": title,
        "sections": [
            {
                "activityTitle": "Enforcement Status",
                "text": summary,
                "markdown": True,
            },
            {
                "facts": [
                    {"name": "Transition", "value": transition},
                    {"name": "Mode", "value": mode},
                    {"name": "Reason", "value": reason},
                    {"name": "Period Rule", "value": period},
                    {"name": "Daily Spend", "value": f"${daily_cost:.6f} / ${daily_budget:.2f}"},
                    {"name": "Monthly Spend", "value": f"${monthly_cost:.6f} / ${monthly_budget:.2f}"},
                ]
            },
        ],
    }


def maybe_notify_state_change(
    payload: dict[str, Any],
    previous_state: dict[str, Any],
    webhook_url: str,
    timeout: int,
    dry_run: bool,
) -> bool:
    active = bool(payload.get('active'))
    previous_active = bool(previous_state.get('active', False))
    previous_marker = str(previous_state.get('marker') or '')
    current_marker = (
        f"active:{active}|mode:{payload.get('mode')}|reason:{payload.get('reason')}|"
        f"period:{payload.get('period')}"
    )

    transition = None
    if active and (not previous_active or previous_marker != current_marker):
        transition = 'activated'
    elif previous_active and not active:
        transition = 'cleared'

    if transition is None:
        return False

    card = build_state_change_card(payload, transition)
    if dry_run:
        logger.info("Budget enforcement notification would fire for %s", transition)
        print(json.dumps(card, indent=2))
        return True

    if not webhook_url:
        logger.warning("Budget enforcement state changed to %s, but no Teams webhook is configured", transition)
        return False

    try:
        response = send_to_teams(webhook_url, card, timeout)
    except Exception as exc:
        logger.warning("Budget enforcement notification failed for %s: %s", transition, exc)
        return False

    logger.info("Budget enforcement notification sent for %s (%s)", transition, response[:120])
    return True


def main() -> int:
    args = parse_args()
    monitor_config = load_agent_config('monitor', args.config)
    enforcement_config = load_agent_config('budget_enforcement', args.config)

    enabled = str(enforcement_config.get('enabled', 'false')).lower() in {'1', 'true', 'yes', 'on'}
    mode = str(enforcement_config.get('mode', 'warn_only') or 'warn_only')
    period = str(enforcement_config.get('period', 'either') or 'either')

    if mode not in VALID_MODES:
        mode = 'warn_only'
    if period not in VALID_PERIODS:
        period = 'either'

    metrics_dir = Path(monitor_config.get('metrics_dir', './output/metrics'))
    today = dt.datetime.now(dt.timezone.utc).date()
    month_key = today.strftime('%Y-%m')
    month_records = iter_month_records(metrics_dir, month_key)
    day_records = filter_records_for_date(month_records, today)

    monthly_summary = summarize_records(month_records)
    daily_summary = summarize_records(day_records)
    monthly_budget = float(monitor_config.get('monthly_budget_usd', 0) or 0)
    daily_budget = float(monitor_config.get('daily_budget_usd', 0) or 0)
    monthly_exceeded = monthly_budget > 0 and float(monthly_summary['total_cost']) >= monthly_budget
    daily_exceeded = daily_budget > 0 and float(daily_summary['total_cost']) >= daily_budget

    active = False
    reason = 'disabled'
    if enabled:
        if period == 'monthly':
            active = monthly_exceeded
            reason = 'monthly_exceeded' if active else 'monthly_ok'
        elif period == 'daily':
            active = daily_exceeded
            reason = 'daily_exceeded' if active else 'daily_ok'
        else:
            active = monthly_exceeded or daily_exceeded
            if monthly_exceeded and daily_exceeded:
                reason = 'daily_and_monthly_exceeded'
            elif monthly_exceeded:
                reason = 'monthly_exceeded'
            elif daily_exceeded:
                reason = 'daily_exceeded'
            else:
                reason = 'within_budget'

    payload: dict[str, Any] = {
        'enabled': enabled,
        'active': active,
        'mode': mode,
        'period': period,
        'reason': reason,
        'monthly_budget_usd': monthly_budget,
        'monthly_cost_usd': float(monthly_summary['total_cost']),
        'daily_budget_usd': daily_budget,
        'daily_cost_usd': float(daily_summary['total_cost']),
    }

    metrics_dir = Path(monitor_config.get('metrics_dir', './output/metrics'))
    state_file = str(enforcement_config.get('state_file') or '').strip()
    state_path = Path(state_file) if state_file else metrics_dir / 'budget_enforcement_state.json'
    state = read_state(state_path)
    webhook_url = str(enforcement_config.get('teams_webhook_url') or monitor_config.get('teams_webhook_url') or '')
    timeout = int(enforcement_config.get('timeout') or monitor_config.get('timeout') or 15)

    notified = maybe_notify_state_change(payload, state, webhook_url, timeout, args.dry_run)
    payload['notified'] = notified

    if not args.dry_run:
        write_state(
            state_path,
            {
                'active': active,
                'enabled': enabled,
                'mode': mode,
                'reason': reason,
                'period': period,
                'marker': (
                    f"active:{active}|mode:{mode}|reason:{reason}|period:{period}"
                ),
                'updated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                'last_notified_at': dt.datetime.now(dt.timezone.utc).isoformat() if notified else state.get('last_notified_at'),
            },
        )

    print(json.dumps(payload))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
