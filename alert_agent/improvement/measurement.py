from __future__ import annotations

import datetime as dt
from typing import Any


def _parse_timestamp(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _event_matches_proposal(proposal: dict[str, Any], event: dict[str, Any]) -> bool:
    if proposal.get("source") and str(event.get("source") or "") != str(proposal.get("source") or ""):
        return False
    if proposal.get("project") and str(event.get("project") or "") != str(proposal.get("project") or ""):
        return False

    proposal_type = str(proposal.get("type") or "")
    classification = str(proposal.get("classification") or proposal.get("source_classification") or "")
    event_classification = str(event.get("classification") or "")
    if classification and event_classification != classification:
        return False

    if proposal_type == "priority_threshold":
        priority = str(proposal.get("priority") or "")
        if priority and str(event.get("priority") or "") != priority:
            return False

    return str(event.get("target_status") or "") in {"rejected", "ignored"}


def measure_applied_proposal_effect(
    proposal: dict[str, Any],
    audit_events: list[dict[str, Any]],
    window_days: int = 14,
) -> dict[str, Any]:
    applied = dict(proposal.get("applied") or {})
    applied_at = _parse_timestamp(str(applied.get("timestamp") or ""))
    if applied_at is None:
        raise ValueError("Applied proposal is missing applied.timestamp")

    window = dt.timedelta(days=window_days)
    before_start = applied_at - window
    after_end = applied_at + window

    before_count = 0
    after_count = 0
    for event in audit_events:
        if not _event_matches_proposal(proposal, event):
            continue
        timestamp = _parse_timestamp(str(event.get("timestamp") or ""))
        if timestamp is None:
            continue
        if before_start <= timestamp < applied_at:
            before_count += 1
        elif applied_at <= timestamp <= after_end:
            after_count += 1

    delta = after_count - before_count
    if before_count > 0:
        percent_reduction = round(((before_count - after_count) / before_count) * 100.0, 1)
    elif after_count == 0:
        percent_reduction = 100.0
    else:
        percent_reduction = 0.0

    if after_count < before_count:
        outcome = "reduced"
    elif after_count == before_count:
        outcome = "no_change"
    else:
        outcome = "regressed"

    return {
        "proposal_id": proposal.get("proposal_id"),
        "before_count": before_count,
        "after_count": after_count,
        "delta": delta,
        "percent_reduction": percent_reduction,
        "outcome": outcome,
        "window_days": window_days,
    }
