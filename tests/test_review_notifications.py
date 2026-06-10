from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
import io

from agents.sender import build_teams_message_card
from alert_agent.core.pending_review_notifications import (
    build_pending_review_card,
    load_notification_state,
    notify_pending_issue,
    save_notification_state,
)
from alert_agent.core.review_links import build_review_issue_url, build_review_queue_url


SAMPLE_ISSUE = {
    "issue_id": "BACKEND-123",
    "final": {
        "priority": "P1",
        "class": "dependency",
        "danger": "high",
        "reasoning": "Database dependency issue",
    },
    "metadata": {
        "project": "backend",
        "count": 42,
        "users": 3,
        "link": "https://sentry.example.com/issues/123",
        "title": "Database timeout",
    },
    "review": {
        "decision": "review",
        "confidence": 0.82,
        "reasoning": "Needs backend confirmation before customer escalation.",
    },
}


class ReviewNotificationTests(unittest.TestCase):
    def test_build_review_issue_url(self) -> None:
        self.assertEqual(
            build_review_issue_url("http://10.0.0.1:8088/", "BACKEND-123", "pending"),
            "http://10.0.0.1:8088/issue/BACKEND-123?status=pending",
        )

    def test_build_review_queue_url(self) -> None:
        self.assertEqual(
            build_review_queue_url("http://10.0.0.1:8088/", "pending"),
            "http://10.0.0.1:8088/?status=pending",
        )

    def test_sender_card_adds_review_action(self) -> None:
        card = build_teams_message_card(
            {
                "issue_id": "BACKEND-123",
                "priority": "P1",
                "confidence": "0.92",
                "project": "backend",
                "danger": "high",
                "link": "https://sentry.example.com/issues/123",
                "review_status": "approved",
            },
            "## Executive Summary\nDatabase timeout\n\n## Immediate Action\nRestart the dependency",
            "http://10.0.0.1:8088",
        )

        actions = card.get("potentialAction", [])
        names = [action.get("name") for action in actions]
        self.assertIn("Open Review", names)
        self.assertIn("Open in Sentry", names)

    def test_pending_review_card_contains_review_links(self) -> None:
        card = build_pending_review_card(
            SAMPLE_ISSUE,
            {
                "review_web_base_url": "http://10.0.0.1:8088",
            },
        )
        actions = card.get("potentialAction", [])
        names = [action.get("name") for action in actions]
        self.assertIn("Open Review", names)
        self.assertIn("Open Queue", names)
        self.assertIn("Open in Sentry", names)

    def test_pending_notification_is_deduplicated_by_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "pending_review_notification_enabled": True,
                "pending_review_webhook_url": "https://example.invalid/webhook",
                "pending_review_notify_teams": "backend-team",
                "pending_review_notification_state_file": str(Path(tmpdir) / "pending-state.json"),
                "review_web_base_url": "http://10.0.0.1:8088",
            }

            state = load_notification_state(config)
            with redirect_stdout(io.StringIO()):
                first = notify_pending_issue(SAMPLE_ISSUE, config, state, dry_run=True)
            state[SAMPLE_ISSUE["issue_id"]] = "notified"
            save_notification_state(config, state)
            reloaded = load_notification_state(config)
            with redirect_stdout(io.StringIO()):
                second = notify_pending_issue(SAMPLE_ISSUE, config, reloaded, dry_run=True)

            self.assertTrue(first)
            self.assertFalse(second)


if __name__ == "__main__":
    unittest.main()
