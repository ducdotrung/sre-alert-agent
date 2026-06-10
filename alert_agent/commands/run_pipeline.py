"""Run the shared alert pipeline for one source."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from alert_agent.pipeline.recommendation import run as run_recommendation
from alert_agent.pipeline.review import run as run_review
from alert_agent.pipeline.sender import run as run_sender
from alert_agent.pipeline.triage import run as run_triage


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/agent_config.yaml", help="Config file path")
    parser.add_argument("--source", default="sentry", help="Source plugin name")
    parser.add_argument("--hours", type=int, help="Lookback window in hours")
    parser.add_argument("--minutes", type=int, help="Lookback window in minutes")
    parser.add_argument("--triage-dry-run", action="store_true", help="Disable AI during triage")
    parser.add_argument("--recommendation-dry-run", action="store_true", help="Disable AI during recommendations")
    parser.add_argument("--sender-dry-run", action="store_true", help="Print Teams payloads instead of sending")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    triage_exit = run_triage(
        config_file=args.config,
        source_name=args.source,
        hours=args.hours,
        minutes=args.minutes,
        dry_run=args.triage_dry_run,
    )
    if triage_exit != 2:
        return triage_exit

    review_exit = run_review(config_file=args.config)
    if review_exit != 2:
        return review_exit

    recommendation_exit = run_recommendation(
        config_file=args.config,
        dry_run=args.recommendation_dry_run,
    )
    if recommendation_exit != 2:
        return recommendation_exit

    return run_sender(config_file=args.config, dry_run=args.sender_dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
