#!/usr/bin/env python3
"""Update the shared pipeline run state file."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alert_agent.core.config_loader import load_agent_config
from alert_agent.core.health_monitor import read_json_file, utc_now_iso, write_json_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent_config.yaml', help='Config file path')
    parser.add_argument('--status', required=True, choices=['running', 'completed', 'failed'])
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--lock-file')
    parser.add_argument('--exit-code', type=int)
    parser.add_argument('--failure-stage')
    parser.add_argument('--triaged', type=int)
    parser.add_argument('--approved', type=int)
    parser.add_argument('--pending', type=int)
    parser.add_argument('--recommendations', type=int)
    parser.add_argument('--sent', type=int)
    return parser.parse_args()


def count_value(new_value: int | None, existing: dict[str, Any], key: str) -> int:
    """Return an explicit count if provided, else reuse the previous stored value."""
    if new_value is not None:
        return new_value
    try:
        return int(existing.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def main() -> int:
    args = parse_args()
    config = load_agent_config('health_monitor', args.config)
    metrics_dir = Path(config.get('metrics_dir', './output/metrics'))
    state_file = str(config.get('pipeline_state_file') or '').strip()
    state_path = Path(state_file) if state_file else metrics_dir / 'pipeline_state.json'

    state = read_json_file(state_path)
    now = utc_now_iso()
    lock_file = args.lock_file or str(config.get('lock_file') or '')

    counts = {
        'triaged': count_value(args.triaged, state, 'triaged'),
        'approved': count_value(args.approved, state, 'approved'),
        'pending': count_value(args.pending, state, 'pending'),
        'recommendations': count_value(args.recommendations, state, 'recommendations'),
        'sent': count_value(args.sent, state, 'sent'),
    }

    payload: dict[str, Any] = {
        **state,
        **counts,
        'run_id': args.run_id,
        'status': args.status,
        'lock_file': lock_file,
        'updated_at': now,
        'host': os.uname().nodename if hasattr(os, 'uname') else '',
    }

    if args.status == 'running':
        payload.update({
            'started_at': now,
            'finished_at': None,
            'exit_code': None,
            'failure_stage': None,
        })
    else:
        payload.update({
            'finished_at': now,
            'exit_code': args.exit_code,
            'failure_stage': args.failure_stage,
        })

    write_json_file(state_path, payload)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
