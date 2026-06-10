#!/usr/bin/env python3
"""Summarize AI usage and cost records written by the Pi wrapper."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alert_agent.core.usage_metrics import filter_records_last_days, iter_month_records, summarize_records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metrics-dir",
        default="output/metrics",
        help="Directory containing ai_usage-YYYY-MM.jsonl files",
    )
    parser.add_argument(
        "--month",
        help="Month to report in YYYY-MM format (defaults to current UTC month)",
    )
    parser.add_argument(
        "--days",
        type=int,
        help="Only include records from the last N days",
    )
    parser.add_argument(
        "--budget-usd",
        type=float,
        default=0.0,
        help="Optional budget threshold for warning output",
    )
    return parser.parse_args()

def print_summary(records: list[dict[str, object]], budget_usd: float) -> int:
    if not records:
        print("No usage records found for the selected period.")
        return 0

    summary = summarize_records(records)
    total_cost = float(summary["total_cost"])
    total_calls = int(summary["total_calls"])

    print("AI usage summary")
    print(f"Calls: {total_calls}")
    print(f"Successful calls: {int(summary['success_count'])}")
    print(f"Prompt tokens: {int(summary['total_prompt_tokens'])}")
    print(f"Completion tokens: {int(summary['total_completion_tokens'])}")
    print(f"Estimated/actual cost: ${total_cost:.6f}")
    print(f"Calls without cost data: {int(summary['missing_cost'])}")
    print()

    print("Cost source breakdown:")
    for source, count in sorted(dict(summary["by_source"]).items()):
        print(f"  {source}: {count}")
    print()

    print("By agent:")
    for agent, stats in sorted(dict(summary["by_agent"]).items()):
        print(f"  {agent}: {int(stats['calls'])} calls, ${stats['cost']:.6f}")
    print()

    print("Top operations:")
    operations = sorted(
        dict(summary["by_operation"]).items(),
        key=lambda item: item[1],
        reverse=True,
    )
    for operation, count in operations[:10]:
        print(f"  {operation}: {count}")

    if budget_usd > 0:
        print()
        ratio = total_cost / budget_usd if budget_usd else 0.0
        status = "OK"
        if ratio >= 1.0:
            status = "EXCEEDED"
        elif ratio >= 0.8:
            status = "WARNING"
        print(f"Budget: ${budget_usd:.2f} [{status}]")
        print(f"Usage: {ratio * 100:.1f}%")

    return 0


def main() -> int:
    args = parse_args()
    month = args.month or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    metrics_dir = Path(args.metrics_dir)
    records = iter_month_records(metrics_dir, month)
    records = filter_records_last_days(records, args.days)
    return print_summary(records, args.budget_usd)


if __name__ == "__main__":
    raise SystemExit(main())
