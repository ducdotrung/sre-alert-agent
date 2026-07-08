from __future__ import annotations

import datetime as dt
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from alert_agent.core.pending_review_notifications import (
    build_pending_review_card,
    load_notification_state,
    notify_pending_issue,
    save_notification_state,
)
from alert_agent.core.review_links import build_review_issue_url, build_review_queue_url
from alert_agent.pipeline.sender import build_teams_message_card, is_recent_enough
from alert_agent.pipeline.sender import run as run_sender

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

    def test_build_review_issue_url_with_path_prefix(self) -> None:
        self.assertEqual(
            build_review_issue_url(
                "https://sre-alert-review/", "BACKEND-ZY2", "pending"
            ),
            "https://sre-alert-review/issue/BACKEND-ZY2?status=pending",
        )

    def test_sender_card_adds_review_action(self) -> None:
        card = build_teams_message_card(
            {
                "issue_id": "BACKEND-123",
                "priority": "P1",
                "confidence": "0.92",
                "project": "backend",
                "danger": "high",
                "source": "sentry",
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
        section_text = card["sections"][0]["text"]
        self.assertIn(
            "[Open review](http://10.0.0.1:8088/issue/BACKEND-123?status=pending)",
            section_text,
        )
        self.assertIn(
            "[Open queue](http://10.0.0.1:8088/?status=pending)", section_text
        )
        self.assertIn(
            "[Open in Sentry](https://sentry.example.com/issues/123)", section_text
        )
        facts = {item["name"]: item["value"] for item in card["sections"][1]["facts"]}
        self.assertEqual(
            facts["Review URL"], "http://10.0.0.1:8088/issue/BACKEND-123?status=pending"
        )
        self.assertEqual(facts["Queue URL"], "http://10.0.0.1:8088/?status=pending")
        self.assertEqual(facts["Source URL"], "https://sentry.example.com/issues/123")

    def test_pending_notification_is_deduplicated_by_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "pending_review_notification_enabled": True,
                "pending_review_webhook_url": "https://example.invalid/webhook",
                "pending_review_notify_teams": "backend-team",
                "pending_review_notification_state_file": str(
                    Path(tmpdir) / "pending-state.json"
                ),
                "review_web_base_url": "http://10.0.0.1:8088",
            }

            state = load_notification_state(config)
            with redirect_stdout(io.StringIO()):
                first = notify_pending_issue(SAMPLE_ISSUE, config, state, dry_run=True)
            state[SAMPLE_ISSUE["issue_id"]] = "notified"
            save_notification_state(config, state)
            reloaded = load_notification_state(config)
            with redirect_stdout(io.StringIO()):
                second = notify_pending_issue(
                    SAMPLE_ISSUE, config, reloaded, dry_run=True
                )

            self.assertTrue(first)
            self.assertFalse(second)

    def test_is_recent_enough_rejects_stale_last_seen(self) -> None:
        recent, reason = is_recent_enough({"last_seen": "2026-05-01T00:00:00Z"}, 48)
        self.assertFalse(recent)
        self.assertIn("older than 48h", reason)

    def test_sender_skips_missing_sentry_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            now = dt.datetime.now(dt.timezone.utc)
            fresh_first_seen = (
                (now - dt.timedelta(hours=2)).isoformat().replace("+00:00", "Z")
            )
            fresh_last_seen = (
                (now - dt.timedelta(hours=1)).isoformat().replace("+00:00", "Z")
            )
            recommendations_dir = root / "output" / "alerts" / "recommendations"
            triage_dir = root / "output" / "alerts" / "triage"
            recommendations_dir.mkdir(parents=True)
            triage_dir.mkdir(parents=True)
            (root / "config").mkdir()

            (root / "config" / "agent_config.yaml").write_text(
                f"""
sources:
  sentry:
    enabled: true
    kind: sentry
    config:
      base_url: https://sentry.example.com
      auth_token: token
pipeline:
  sender:
    teams_webhook_url: https://example.invalid/webhook
    timeout: 15
common:
  output_dir: {root / "output"}
  review_web_base_url: https://sre-alert-review
""".strip(),
                encoding="utf-8",
            )

            (recommendations_dir / "BACKEND-123.md").write_text(
                """---
issue_id: BACKEND-123
source: sentry
sentry_id: 123
priority: P0
danger: critical
project: backend
send_status: send
confidence: 0.92
review_status: approved
link: https://sentry.example.com/organizations/sentry/issues/123/
first_seen: {fresh_first_seen}
last_seen: {fresh_last_seen}
---

## Executive Summary
Summary

## Immediate Action
Action
""".format(fresh_first_seen=fresh_first_seen, fresh_last_seen=fresh_last_seen),
                encoding="utf-8",
            )

            (triage_dir / "BACKEND-123.json").write_text(
                f"""{{
  "issue_id": "BACKEND-123",
  "sentry_id": "123",
  "source": "sentry",
  "metadata": {{
    "project": "backend",
    "link": "https://sentry.example.com/organizations/sentry/issues/123/",
    "first_seen": "{fresh_first_seen}",
    "last_seen": "{fresh_last_seen}"
  }}
}}""",
                encoding="utf-8",
            )

            with patch(
                "alert_agent.pipeline.sender.sentry_issue_exists", return_value=False
            ):
                exit_code = run_sender(
                    config_file=str(root / "config" / "agent_config.yaml"),
                    dry_run=False,
                )

            self.assertEqual(exit_code, 0)
            self.assertFalse((recommendations_dir / "BACKEND-123.md").exists())
            self.assertTrue(
                (root / "output" / "alerts" / "skipped" / "BACKEND-123.md").exists()
            )
            self.assertTrue(
                (
                    root / "output" / "alerts" / "skipped" / "BACKEND-123.md.skip.json"
                ).exists()
            )

    def test_sender_skips_stale_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            recommendations_dir = root / "output" / "alerts" / "recommendations"
            recommendations_dir.mkdir(parents=True)
            (root / "config").mkdir()

            (root / "config" / "agent_config.yaml").write_text(
                f"""
sources:
  sentry:
    enabled: true
    kind: sentry
    config:
      base_url: https://sentry.example.com
      auth_token: token
pipeline:
  sender:
    teams_webhook_url: https://example.invalid/webhook
    timeout: 15
    max_last_seen_age_hours: 48
common:
  output_dir: {root / "output"}
""".strip(),
                encoding="utf-8",
            )

            (recommendations_dir / "BACKEND-124.md").write_text(
                """---
issue_id: BACKEND-124
source: sentry
sentry_id: 124
priority: P0
danger: critical
project: backend
send_status: send
confidence: 0.92
review_status: approved
link: https://sentry.example.com/organizations/sentry/issues/124/
last_seen: 2026-05-01T00:00:00Z
---

## Executive Summary
Summary

## Immediate Action
Action
""",
                encoding="utf-8",
            )

            exit_code = run_sender(
                config_file=str(root / "config" / "agent_config.yaml"), dry_run=False
            )

            self.assertEqual(exit_code, 0)
            self.assertFalse((recommendations_dir / "BACKEND-124.md").exists())
            self.assertTrue(
                (root / "output" / "alerts" / "skipped" / "BACKEND-124.md").exists()
            )
            self.assertTrue(
                (
                    root / "output" / "alerts" / "skipped" / "BACKEND-124.md.skip.json"
                ).exists()
            )


if __name__ == "__main__":
    unittest.main()
