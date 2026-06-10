#!/usr/bin/env python3
"""Helpers for reading and summarizing AI usage ledgers."""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def iter_month_records(metrics_dir: Path, month: str) -> list[dict[str, Any]]:
    """Load all usage records for a YYYY-MM ledger."""
    ledger_path = metrics_dir / f"ai_usage-{month}.jsonl"
    if not ledger_path.exists():
        return []

    records: list[dict[str, Any]] = []
    with ledger_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def parse_timestamp(value: Any) -> dt.datetime | None:
    """Parse an ISO8601 timestamp with a best-effort fallback."""
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None


def filter_records_last_days(records: list[dict[str, Any]], days: int | None) -> list[dict[str, Any]]:
    """Keep only records from the last N days."""
    if not days:
        return records

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    filtered: list[dict[str, Any]] = []
    for record in records:
        timestamp = parse_timestamp(record.get("timestamp"))
        if timestamp and timestamp >= cutoff:
            filtered.append(record)
    return filtered


def filter_records_for_date(records: list[dict[str, Any]], day: dt.date) -> list[dict[str, Any]]:
    """Keep only records matching a UTC calendar day."""
    filtered: list[dict[str, Any]] = []
    for record in records:
        timestamp = parse_timestamp(record.get("timestamp"))
        if timestamp and timestamp.date() == day:
            filtered.append(record)
    return filtered


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Build aggregate usage statistics from ledger rows."""
    total_cost = 0.0
    missing_cost = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_tokens = 0
    total_calls = len(records)
    success_count = 0
    by_agent: dict[str, dict[str, float]] = defaultdict(lambda: {"calls": 0.0, "cost": 0.0})
    by_operation: Counter[str] = Counter()
    by_source: Counter[str] = Counter()

    for record in records:
        success = bool(record.get("success"))
        cost_value = record.get("cost_usd")
        agent = str(record.get("agent") or "unknown")
        operation = str(record.get("operation") or "unknown")
        cost_source = str(record.get("cost_source") or "missing")

        if success:
            success_count += 1

        prompt_tokens = int(record.get("prompt_tokens") or 0)
        completion_tokens = int(record.get("completion_tokens") or 0)
        record_total_tokens = int(record.get("total_tokens") or 0)

        total_prompt_tokens += prompt_tokens
        total_completion_tokens += completion_tokens
        total_tokens += record_total_tokens or (prompt_tokens + completion_tokens)
        by_operation[operation] += 1
        by_source[cost_source] += 1
        by_agent[agent]["calls"] += 1

        if cost_value is None:
            missing_cost += 1
            continue

        total_cost += float(cost_value)
        by_agent[agent]["cost"] += float(cost_value)

    return {
        "total_cost": total_cost,
        "missing_cost": missing_cost,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_tokens": total_tokens,
        "total_calls": total_calls,
        "success_count": success_count,
        "by_agent": {agent: {"calls": int(stats["calls"]), "cost": stats["cost"]} for agent, stats in by_agent.items()},
        "by_operation": dict(by_operation),
        "by_source": dict(by_source),
    }
