"""Normalize raw Sentry issues into the canonical alert model."""

from __future__ import annotations

from typing import Any

from alert_agent.core.models import AlertRecord


def normalize_sentry_issue(raw_issue: dict[str, Any]) -> AlertRecord:
    project = raw_issue.get("project", {}) or {}
    metadata = raw_issue.get("metadata", {}) or {}
    source_alert_id = str(raw_issue.get("shortId", "") or raw_issue.get("id", ""))

    labels = {
        "metadata_type": str(metadata.get("type") or ""),
        "metadata_value": str(metadata.get("value") or ""),
        "level": str(raw_issue.get("level") or ""),
        "platform": str(project.get("platform") or ""),
        "project": str(project.get("slug") or ""),
    }

    return AlertRecord(
        alert_id=f"sentry:{source_alert_id}",
        source="sentry",
        source_type="error_tracking",
        source_alert_id=source_alert_id,
        title=str(raw_issue.get("title") or ""),
        summary=str(metadata.get("value") or raw_issue.get("culprit") or ""),
        project=str(project.get("slug") or ""),
        service=str(project.get("slug") or ""),
        platform=str(project.get("platform") or ""),
        environment=str(raw_issue.get("environment") or ""),
        severity=str(raw_issue.get("level") or ""),
        status=str(raw_issue.get("status") or "active"),
        count=int(raw_issue.get("count", 0) or 0),
        affected_users=int(raw_issue.get("userCount", 0) or raw_issue.get("users", 0) or 0),
        first_seen=str(raw_issue.get("firstSeen") or ""),
        last_seen=str(raw_issue.get("lastSeen") or ""),
        culprit=str(raw_issue.get("culprit") or ""),
        link=str(raw_issue.get("permalink") or ""),
        labels={key: value for key, value in labels.items() if value},
        raw_ref={
            "external_id": str(raw_issue.get("id") or ""),
            "short_id": source_alert_id,
            "url": str(raw_issue.get("permalink") or ""),
        },
        raw_payload=raw_issue,
    )
