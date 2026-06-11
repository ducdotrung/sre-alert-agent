from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from alert_agent.core.manual_review import ensure_dirs, list_issues, record_action


def sample_issue() -> dict[str, object]:
    return {
        "issue_id": "SENTRY-123",
        "sentry_id": "123",
        "metadata": {
            "title": "Unhandled exception",
            "project": "backend-api",
            "count": 12,
            "users": 3,
            "last_seen": "2026-06-08T00:00:00+00:00",
            "link": "https://sentry.example.com/issues/123",
        },
        "final": {
            "priority": "P1",
            "class": "server-error",
            "danger": "high",
        },
        "review": {
            "decision": "review",
            "confidence": 0.74,
            "reasoning": "Needs human confirmation",
        },
    }


class ManualReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.paths = {
            "repo_root": root,
            "output_dir": root / "output",
            "alerts_dir": root / "output" / "alerts",
            "metrics_dir": root / "output" / "metrics",
            "audit_log": root / "output" / "metrics" / "manual_review_actions.jsonl",
        }
        ensure_dirs(self.paths)
        pending_file = self.paths["alerts_dir"] / "pending" / "SENTRY-123.json"
        pending_file.write_text(json.dumps(sample_issue(), indent=2), encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_record_action_moves_issue_and_writes_audit_log(self) -> None:
        result = record_action(
            self.paths,
            issue_id="SENTRY-123",
            action="approve",
            reviewer="reviewer-a",
            note="Confirmed customer impact",
            priority="P0",
        )

        approved_path = self.paths["alerts_dir"] / "approved" / "SENTRY-123.json"
        pending_path = self.paths["alerts_dir"] / "pending" / "SENTRY-123.json"

        self.assertFalse(pending_path.exists())
        self.assertTrue(approved_path.exists())
        self.assertEqual(result["target_status"], "approved")

        updated = json.loads(approved_path.read_text(encoding="utf-8"))
        self.assertEqual(updated["review"]["decision"], "send")
        self.assertTrue(updated["review"]["manual_override"])
        self.assertEqual(updated["final"]["priority"], "P0")
        self.assertEqual(updated["manual_review"]["reviewer"], "reviewer-a")

        audit_lines = self.paths["audit_log"].read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(audit_lines), 1)
        audit_event = json.loads(audit_lines[0])
        self.assertEqual(audit_event["action"], "approve")
        self.assertEqual(audit_event["review_team"], "backend-team")

    def test_list_issues_reports_review_team(self) -> None:
        summaries = list_issues(self.paths, "pending", limit=10)
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["review_team"], "backend-team")


if __name__ == "__main__":
    unittest.main()
