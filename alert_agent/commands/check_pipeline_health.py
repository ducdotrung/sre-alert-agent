"""Check pipeline health state and optionally send Teams alerts."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
from pathlib import Path
from typing import Any, Sequence, TextIO

from alert_agent.core.config_loader import load_agent_config
from alert_agent.core.health_monitor import parse_timestamp, read_json_file, write_json_file
from alert_agent.monitoring.common import build_message_card, emit_deduplicated_alert, is_enabled


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [HealthMonitor] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent_config.yaml', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Print alerts without sending')
    return parser.parse_args(argv)


def minutes_since(timestamp: dt.datetime, now: dt.datetime) -> int:
    """Return whole minutes elapsed between two timestamps."""
    return int((now - timestamp).total_seconds() // 60)


def pipeline_reference_time(state: dict[str, Any]) -> dt.datetime | None:
    """Pick the best timestamp for stale-run checks."""
    for key in ('finished_at', 'started_at', 'updated_at'):
        stamp = parse_timestamp(state.get(key))
        if stamp is not None:
            return stamp
    return None


def check_failed_run(
    pipeline_state: dict[str, Any],
    alert_state: dict[str, Any],
    config: dict[str, Any],
    *,
    dry_run: bool,
    stdout: TextIO | None = None,
) -> bool:
    """Alert once for each failed run."""
    if str(pipeline_state.get('status') or '') != 'failed':
        return False

    run_id = str(pipeline_state.get('run_id') or '')
    if not run_id:
        return False

    failure_stage = str(pipeline_state.get('failure_stage') or 'unknown')
    exit_code = str(pipeline_state.get('exit_code') or 'unknown')
    finished_at = str(pipeline_state.get('finished_at') or pipeline_state.get('updated_at') or 'unknown')
    facts = [
        {"name": "Run ID", "value": run_id},
        {"name": "Stage", "value": failure_stage},
        {"name": "Exit Code", "value": exit_code},
        {"name": "Finished At", "value": finished_at},
    ]

    details = (
        f"Last pipeline run failed during `{failure_stage}`.\n\n"
        f"Counts: triaged={pipeline_state.get('triaged', 0)}, "
        f"approved={pipeline_state.get('approved', 0)}, "
        f"pending={pipeline_state.get('pending', 0)}, "
        f"recommendations={pipeline_state.get('recommendations', 0)}, "
        f"sent={pipeline_state.get('sent', 0)}"
    )
    card = build_message_card(
        "Pipeline Health Alert [CRITICAL] Failed Run",
        f"Sentry alert pipeline run `{run_id}` failed in stage `{failure_stage}`.",
        "E81123",
        facts,
        details,
        activity_title="Health Status",
    )
    return emit_deduplicated_alert(
        alert_state,
        'failed_run',
        run_id,
        card,
        config,
        dry_run=dry_run,
        logger=logger,
        log_label="Health alert",
        stdout=stdout,
    )


def check_stale_run(
    pipeline_state: dict[str, Any],
    alert_state: dict[str, Any],
    config: dict[str, Any],
    *,
    dry_run: bool,
    stdout: TextIO | None = None,
) -> bool:
    """Alert when the pipeline has not updated within the configured interval."""
    stale_after_minutes = int(config.get('stale_run_after_minutes', 120) or 120)
    reference = pipeline_reference_time(pipeline_state)
    if reference is None:
        return False

    now = dt.datetime.now(dt.timezone.utc)
    age_minutes = minutes_since(reference, now)
    if age_minutes < stale_after_minutes:
        return False

    marker = f"{pipeline_state.get('run_id', 'unknown')}:{reference.isoformat()}"
    facts = [
        {"name": "Last Run ID", "value": str(pipeline_state.get('run_id') or 'unknown')},
        {"name": "Last Status", "value": str(pipeline_state.get('status') or 'unknown')},
        {"name": "Last Update", "value": reference.isoformat()},
        {"name": "Age", "value": f"{age_minutes} minutes"},
        {"name": "Threshold", "value": f"{stale_after_minutes} minutes"},
    ]
    card = build_message_card(
        "Pipeline Health Alert [HIGH] Stale Run",
        f"Pipeline has not updated for {age_minutes} minutes.",
        "F7630C",
        facts,
        "No recent pipeline update was recorded. Check cron, lock file state, and agent logs.",
        activity_title="Health Status",
    )
    return emit_deduplicated_alert(
        alert_state,
        'stale_run',
        marker,
        card,
        config,
        dry_run=dry_run,
        logger=logger,
        log_label="Health alert",
        stdout=stdout,
    )


def check_stuck_lock(
    pipeline_state: dict[str, Any],
    alert_state: dict[str, Any],
    config: dict[str, Any],
    *,
    dry_run: bool,
    stdout: TextIO | None = None,
) -> bool:
    """Alert when the orchestrator lock file has been present too long."""
    lock_file = str(pipeline_state.get('lock_file') or config.get('lock_file') or '').strip()
    if not lock_file:
        return False

    lock_path = Path(lock_file)
    if not lock_path.exists():
        return False

    stuck_after_minutes = int(config.get('stuck_lock_after_minutes', 90) or 90)
    modified_at = dt.datetime.fromtimestamp(lock_path.stat().st_mtime, tz=dt.timezone.utc)
    now = dt.datetime.now(dt.timezone.utc)
    age_minutes = minutes_since(modified_at, now)
    if age_minutes < stuck_after_minutes:
        return False

    marker = f"{lock_path}:{modified_at.isoformat()}"
    facts = [
        {"name": "Lock File", "value": str(lock_path)},
        {"name": "Age", "value": f"{age_minutes} minutes"},
        {"name": "Threshold", "value": f"{stuck_after_minutes} minutes"},
        {"name": "Run ID", "value": str(pipeline_state.get('run_id') or 'unknown')},
    ]
    card = build_message_card(
        "Pipeline Health Alert [HIGH] Lock File Stuck",
        f"Pipeline lock file has existed for {age_minutes} minutes.",
        "F7630C",
        facts,
        "A stale lock usually means the previous run crashed or never cleaned up.",
        activity_title="Health Status",
    )
    return emit_deduplicated_alert(
        alert_state,
        'stuck_lock',
        marker,
        card,
        config,
        dry_run=dry_run,
        logger=logger,
        log_label="Health alert",
        stdout=stdout,
    )


def run(config: dict[str, Any], *, dry_run: bool = False, stdout: TextIO | None = None) -> int:
    """Execute the health monitor using a resolved config dict."""
    if not is_enabled(config.get('enabled', 'true')):
        logger.info("Health monitor disabled")
        return 0

    metrics_dir = Path(config.get('metrics_dir', './output/metrics'))
    pipeline_state_file = str(config.get('pipeline_state_file') or '').strip()
    state_file = str(config.get('state_file') or '').strip()

    pipeline_state_path = Path(pipeline_state_file) if pipeline_state_file else metrics_dir / 'pipeline_state.json'
    alert_state_path = Path(state_file) if state_file else metrics_dir / 'health_alert_state.json'

    pipeline_state = read_json_file(pipeline_state_path)
    if not pipeline_state:
        logger.info("No pipeline state found")
        return 0

    alert_state = read_json_file(alert_state_path)
    sent_any = False
    sent_any = check_failed_run(pipeline_state, alert_state, config, dry_run=dry_run, stdout=stdout) or sent_any
    sent_any = check_stale_run(pipeline_state, alert_state, config, dry_run=dry_run, stdout=stdout) or sent_any
    sent_any = check_stuck_lock(pipeline_state, alert_state, config, dry_run=dry_run, stdout=stdout) or sent_any

    if not dry_run:
        write_json_file(alert_state_path, alert_state)
    return 2 if sent_any else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_agent_config('health_monitor', args.config)
    return run(config, dry_run=args.dry_run)


if __name__ == '__main__':
    raise SystemExit(main())
