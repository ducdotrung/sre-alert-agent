from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from alert_agent.core.health_monitor import read_json_file
from alert_agent.core.manual_review import load_paths


def read_audit_events(paths: dict[str, Path]) -> list[dict[str, Any]]:
    """Read manual review audit events."""
    audit_path = paths["audit_log"]
    if not audit_path.exists():
        return []

    events: list[dict[str, Any]] = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def load_issue_documents(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    """Load issue documents from review queues keyed by issue id."""
    documents: dict[str, dict[str, Any]] = {}
    alerts_dir = paths["alerts_dir"]
    for status in ("pending", "approved", "rejected", "ignored"):
        directory = alerts_dir / status
        if not directory.exists():
            continue
        for path in directory.glob("*.json"):
            payload = read_json_file(path)
            issue_id = str(payload.get("issue_id") or path.stem)
            if issue_id:
                payload["_status"] = status
                payload["_path"] = str(path)
                documents[issue_id] = payload
    return documents


def title_signature(issue: dict[str, Any]) -> str:
    """Build a simple stable grouping key for similar issues."""
    metadata = issue.get("metadata", {})
    metadata_type = str(metadata.get("metadata_type") or "").strip().lower()
    if metadata_type:
        return metadata_type

    title = str(metadata.get("title") or "").lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", title)
    tokens = [token for token in cleaned.split() if token and not token.isdigit()]
    return " ".join(tokens[:8]) or "unknown-title"


def build_review_cases(config_file: str) -> list[dict[str, Any]]:
    """Build normalized review cases from audit events plus current issue documents."""
    paths = load_paths(config_file)
    audit_events = read_audit_events(paths)
    issue_docs = load_issue_documents(paths)
    grouped_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in audit_events:
        issue_id = str(event.get("issue_id") or "")
        if issue_id:
            grouped_events[issue_id].append(event)

    cases: list[dict[str, Any]] = []
    for issue_id, events in grouped_events.items():
        issue = issue_docs.get(issue_id, {})
        metadata = issue.get("metadata", {})
        final = issue.get("final", {})
        review = issue.get("review", {})
        notes = [str(event.get("note") or "").strip() for event in events if str(event.get("note") or "").strip()]
        manual_history = issue.get("manual_review_history", [])
        cases.append(
            {
                "issue_id": issue_id,
                "alert_id": str(issue.get("alert_id") or ""),
                "source": str(issue.get("source") or events[-1].get("source") or ""),
                "policy_pack": str(issue.get("policy_pack") or events[-1].get("policy_pack") or ""),
                "project": str(metadata.get("project") or events[-1].get("project") or ""),
                "title": str(metadata.get("title") or ""),
                "title_signature": title_signature(issue),
                "classification": str(final.get("class") or events[-1].get("classification") or "unknown"),
                "priority": str(final.get("priority") or events[-1].get("priority") or "unknown"),
                "danger": str(final.get("danger") or events[-1].get("danger") or "unknown"),
                "count": int(metadata.get("count") or 0),
                "users": int(metadata.get("users") or 0),
                "review_decision": str(review.get("decision") or ""),
                "review_confidence": float(review.get("confidence") or 0),
                "notes": notes,
                "events": events,
                "manual_history": manual_history,
                "issue": issue,
                "status": str(issue.get("_status") or events[-1].get("target_status") or ""),
            }
        )

    cases.sort(key=lambda case: (case["project"], case["title_signature"], case["issue_id"]))
    return cases
