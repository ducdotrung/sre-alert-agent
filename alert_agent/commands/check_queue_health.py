"""Check queue/workflow state and optionally send Teams alerts."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
from pathlib import Path
from typing import Any, Sequence, TextIO

from alert_agent.core.config_loader import load_agent_config
from alert_agent.core.health_monitor import read_json_file, write_json_file
from alert_agent.monitoring.common import build_message_card, emit_deduplicated_alert, is_enabled


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [QueueMonitor] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent_config.yaml', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Print alerts without sending')
    return parser.parse_args(argv)


def now_utc() -> dt.datetime:
    """Current UTC timestamp."""
    return dt.datetime.now(dt.timezone.utc)


def queue_files(directory: Path, pattern: str) -> list[Path]:
    """Return sorted queue files for a directory."""
    if not directory.exists():
        return []
    return sorted(directory.glob(pattern))


def oldest_age_hours(files: list[Path], now: dt.datetime) -> float:
    """Age in hours of the oldest file in a queue."""
    if not files:
        return 0.0
    oldest_mtime = min(file.stat().st_mtime for file in files)
    oldest = dt.datetime.fromtimestamp(oldest_mtime, tz=dt.timezone.utc)
    return (now - oldest).total_seconds() / 3600


def check_pending_backlog(
    pending_files: list[Path],
    alert_state: dict[str, Any],
    config: dict[str, Any],
    *,
    dry_run: bool,
    stdout: TextIO | None = None,
) -> bool:
    """Alert when the pending queue exceeds the configured size."""
    threshold = int(config.get('pending_threshold', 10) or 10)
    if threshold <= 0 or len(pending_files) < threshold:
        return False

    marker = f"count:{len(pending_files)}"
    facts = [
        {"name": "Queue", "value": "pending"},
        {"name": "Count", "value": str(len(pending_files))},
        {"name": "Threshold", "value": str(threshold)},
    ]
    details = "Pending review queue has exceeded the configured threshold."
    card = build_message_card(
        "Queue Alert [HIGH] Pending Backlog",
        f"Pending review queue size is {len(pending_files)} (threshold {threshold}).",
        "F7630C",
        facts,
        details,
        activity_title="Queue Status",
    )
    return emit_deduplicated_alert(
        alert_state,
        'pending_backlog',
        marker,
        card,
        config,
        dry_run=dry_run,
        logger=logger,
        log_label="Queue alert",
        stdout=stdout,
    )


def check_stale_queue(
    queue_name: str,
    files: list[Path],
    threshold_hours: float,
    alert_key: str,
    title: str,
    summary_template: str,
    alert_state: dict[str, Any],
    config: dict[str, Any],
    *,
    dry_run: bool,
    stdout: TextIO | None = None,
) -> bool:
    """Alert when the oldest file in a queue is older than the configured threshold."""
    if threshold_hours <= 0 or not files:
        return False

    now = now_utc()
    oldest_file = min(files, key=lambda file: file.stat().st_mtime)
    oldest_age = oldest_age_hours(files, now)
    if oldest_age < threshold_hours:
        return False

    modified_at = dt.datetime.fromtimestamp(oldest_file.stat().st_mtime, tz=dt.timezone.utc)
    marker = f"{oldest_file.name}:{modified_at.isoformat()}"
    facts = [
        {"name": "Queue", "value": queue_name},
        {"name": "Count", "value": str(len(files))},
        {"name": "Oldest File", "value": oldest_file.name},
        {"name": "Age", "value": f"{oldest_age:.1f} hours"},
        {"name": "Threshold", "value": f"{threshold_hours:.1f} hours"},
    ]
    card = build_message_card(
        title,
        summary_template.format(count=len(files), age=oldest_age),
        "FFB900",
        facts,
        f"Oldest file timestamp: `{modified_at.isoformat()}`",
        activity_title="Queue Status",
    )
    return emit_deduplicated_alert(
        alert_state,
        alert_key,
        marker,
        card,
        config,
        dry_run=dry_run,
        logger=logger,
        log_label="Queue alert",
        stdout=stdout,
    )


def run(config: dict[str, Any], *, dry_run: bool = False, stdout: TextIO | None = None) -> int:
    """Execute the queue monitor using a resolved config dict."""
    if not is_enabled(config.get('enabled', 'true')):
        logger.info("Queue monitor disabled")
        return 0

    output_dir = Path(config.get('output_dir', './output'))
    metrics_dir = Path(config.get('metrics_dir', './output/metrics'))
    state_file = str(config.get('state_file') or '').strip()
    state_path = Path(state_file) if state_file else metrics_dir / 'queue_alert_state.json'
    alert_state = read_json_file(state_path)

    pending_files = queue_files(output_dir / 'alerts' / 'pending', '*.json')
    approved_files = queue_files(output_dir / 'alerts' / 'approved', '*.json')
    recommendation_files = queue_files(output_dir / 'alerts' / 'recommendations', '*.md')

    sent_any = False
    sent_any = check_pending_backlog(pending_files, alert_state, config, dry_run=dry_run, stdout=stdout) or sent_any
    sent_any = check_stale_queue(
        'approved',
        approved_files,
        float(config.get('approved_stale_hours', 4) or 4),
        'approved_stale',
        'Queue Alert [HIGH] Approved Queue Stale',
        'Approved queue contains {count} files and the oldest is {age:.1f} hours old.',
        alert_state,
        config,
        dry_run=dry_run,
        stdout=stdout,
    ) or sent_any
    sent_any = check_stale_queue(
        'recommendations',
        recommendation_files,
        float(config.get('recommendation_stale_hours', 2) or 2),
        'recommendation_stale',
        'Queue Alert [HIGH] Recommendation Queue Stale',
        'Recommendation queue contains {count} files and the oldest is {age:.1f} hours old.',
        alert_state,
        config,
        dry_run=dry_run,
        stdout=stdout,
    ) or sent_any

    if not dry_run:
        write_json_file(state_path, alert_state)
    return 2 if sent_any else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_agent_config('queue_monitor', args.config)
    return run(config, dry_run=args.dry_run)


if __name__ == '__main__':
    raise SystemExit(main())
