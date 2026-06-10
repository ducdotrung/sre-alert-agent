from __future__ import annotations

import datetime as dt
import json
import logging
import sys
from typing import Any, TextIO

from alert_agent.core.teams import send_to_teams


ENABLED_VALUES = {"1", "true", "yes", "on"}


def is_enabled(value: Any, default: bool = True) -> bool:
    """Interpret config flags consistently across monitor commands."""
    if value is None:
        return default
    return str(value).lower() in ENABLED_VALUES


def now_utc() -> dt.datetime:
    """Return the current UTC time."""
    return dt.datetime.now(dt.timezone.utc)


def print_payload(payload: dict[str, Any], stdout: TextIO | None = None) -> None:
    """Print a JSON payload for dry-run mode."""
    stream = stdout or sys.stdout
    print(json.dumps(payload, indent=2), file=stream)


def build_message_card(
    title: str,
    summary: str,
    color: str,
    facts: list[dict[str, str]],
    details: str,
    *,
    activity_title: str,
) -> dict[str, Any]:
    """Build a Teams MessageCard with a common shape."""
    return {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": summary,
        "themeColor": color,
        "title": title,
        "sections": [
            {
                "activityTitle": activity_title,
                "text": summary,
                "markdown": True,
            },
            {
                "facts": facts,
            },
            {
                "activityTitle": "Details",
                "text": details,
                "markdown": True,
            },
        ],
    }


def emit_deduplicated_alert(
    state: dict[str, Any],
    issue_key: str,
    marker: str,
    card: dict[str, Any],
    config: dict[str, Any],
    *,
    dry_run: bool,
    logger: logging.Logger,
    log_label: str,
    stdout: TextIO | None = None,
) -> bool:
    """Send or print a deduplicated alert and update state on success."""
    current = state.get(issue_key, {})
    if str(current.get("marker") or "") == marker:
        logger.info("%s already alerted for marker %s", issue_key, marker)
        return False

    webhook_url = str(config.get("teams_webhook_url") or "")
    timeout = int(config.get("timeout", 15))

    if dry_run:
        logger.info("%s would fire for %s", log_label, issue_key)
        print_payload(card, stdout)
        return True

    if not webhook_url:
        logger.warning("%s detected for %s, but no Teams webhook is configured", log_label, issue_key)
        return False

    response = send_to_teams(webhook_url, card, timeout)
    logger.info("%s sent for %s (%s)", log_label, issue_key, response[:120])
    state[issue_key] = {
        "marker": marker,
        "last_alert_at": now_utc().isoformat(),
    }
    return True
