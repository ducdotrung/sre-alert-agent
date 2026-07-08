"""Pending-review Teams notification helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .health_monitor import read_json_file, write_json_file
from .manual_review import classify_review_team
from .review_links import build_review_issue_url, build_review_queue_url
from .teams import send_to_teams


def parse_notify_teams(value: Any) -> set[str]:
    """Normalize configured review-team filters."""
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = str(value or "").split(",")

    teams = {str(raw).strip() for raw in raw_values if str(raw).strip()}
    return teams or {"backend-team"}


def notification_state_path(config: dict[str, Any]) -> Path:
    """Resolve the notification state path from config."""
    state_file = str(config.get("pending_review_notification_state_file") or "").strip()
    if state_file:
        return Path(state_file)
    metrics_dir = Path(config.get("metrics_dir", "./output/metrics"))
    return metrics_dir / "pending_review_notification_state.json"


def load_notification_state(config: dict[str, Any]) -> dict[str, Any]:
    """Load notification dedupe state."""
    return read_json_file(notification_state_path(config))


def save_notification_state(config: dict[str, Any], state: dict[str, Any]) -> None:
    """Persist notification dedupe state."""
    write_json_file(notification_state_path(config), state)


def pending_notification_enabled(config: dict[str, Any]) -> bool:
    """Whether pending-review notifications are enabled."""
    return str(config.get("pending_review_notification_enabled", "false")).lower() in {"1", "true", "yes", "on"}


def pending_notification_webhook_url(config: dict[str, Any]) -> str:
    """Webhook used for pending-review notifications."""
    return str(config.get("pending_review_webhook_url") or "").strip()


def should_notify_issue(issue: dict[str, Any], config: dict[str, Any]) -> bool:
    """Check whether this issue belongs to a team that should be notified."""
    if not pending_notification_enabled(config):
        return False
    if not pending_notification_webhook_url(config):
        return False

    metadata = issue.get("metadata", {})
    review_team = classify_review_team(metadata.get("project"))
    configured_teams = parse_notify_teams(config.get("pending_review_notify_teams", "backend-team"))
    return "*" in configured_teams or review_team in configured_teams


def build_pending_review_card(issue: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Build a Teams card for a pending review issue."""
    metadata = issue.get("metadata", {})
    final = issue.get("final", {})
    review = issue.get("review", {})
    issue_id = str(issue.get("issue_id") or "unknown")
    project = str(metadata.get("project") or "")
    review_team = classify_review_team(project)
    priority = str(final.get("priority") or "P3")
    review_url = build_review_issue_url(config.get("review_web_base_url"), issue_id, "pending")
    queue_url = build_review_queue_url(config.get("review_web_base_url"), "pending")
    sentry_url = str(metadata.get("link") or "")
    reasoning = str(review.get("reasoning") or final.get("reasoning") or "Manual review is required.")
    reasoning = reasoning[:700] + "..." if len(reasoning) > 700 else reasoning
    link_lines: list[str] = []
    if review_url:
        link_lines.append(f"[Open review]({review_url})")
    if queue_url:
        link_lines.append(f"[Open queue]({queue_url})")
    if sentry_url:
        link_lines.append(f"[Open in Sentry]({sentry_url})")
    if link_lines:
        reasoning = f"{reasoning}\n\n" + " | ".join(link_lines)

    card: dict[str, Any] = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"Pending review required for {issue_id}",
        "themeColor": {
            "P0": "E81123",
            "P1": "F7630C",
            "P2": "FFB900",
            "P3": "107C10",
        }.get(priority, "666666"),
        "title": f"Manual Review Needed [{priority}] {issue_id}",
        "sections": [
            {
                "activityTitle": "Pending Review",
                "text": reasoning,
                "markdown": True,
            },
            {
                "facts": [
                    {"name": "Issue", "value": issue_id},
                    {"name": "Project", "value": project or "unknown"},
                    {"name": "Review Team", "value": review_team},
                    {"name": "Priority", "value": priority},
                    {"name": "Classification", "value": str(final.get("class") or "unknown")},
                    {"name": "Count", "value": str(metadata.get("count") or 0)},
                    {"name": "Users", "value": str(metadata.get("users") or 0)},
                    {"name": "Review Decision", "value": str(review.get("decision") or "review")},
                    {"name": "AI Confidence", "value": f"{float(review.get('confidence') or 0):.0%}"},
                    {"name": "Review URL", "value": review_url or "not configured"},
                    {"name": "Queue URL", "value": queue_url or "not configured"},
                    {"name": "Source URL", "value": sentry_url or "not available"},
                ],
            },
        ],
    }

    actions: list[dict[str, Any]] = []
    if review_url:
        actions.append(
            {
                "@type": "OpenUri",
                "name": "Open Review",
                "targets": [{"os": "default", "uri": review_url}],
            }
        )
    if queue_url:
        actions.append(
            {
                "@type": "OpenUri",
                "name": "Open Queue",
                "targets": [{"os": "default", "uri": queue_url}],
            }
        )
    if sentry_url:
        actions.append(
            {
                "@type": "OpenUri",
                "name": "Open in Sentry",
                "targets": [{"os": "default", "uri": sentry_url}],
            }
        )
    if actions:
        card["potentialAction"] = actions

    return card


def notify_pending_issue(
    issue: dict[str, Any],
    config: dict[str, Any],
    state: dict[str, Any],
    *,
    dry_run: bool,
) -> bool:
    """Send or preview a pending-review notification once per issue."""
    issue_id = str(issue.get("issue_id") or "")
    if not issue_id or not should_notify_issue(issue, config):
        return False

    marker = str(state.get(issue_id) or "")
    if marker == "notified":
        return False

    card = build_pending_review_card(issue, config)
    if dry_run:
        print(json.dumps(card, indent=2))
        return True

    send_to_teams(pending_notification_webhook_url(config), card, int(config.get("timeout", 15)))
    state[issue_id] = "notified"
    return True
