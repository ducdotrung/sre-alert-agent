from __future__ import annotations

import unittest

from alert_agent.sources.sentry.normalizer import normalize_sentry_issue


class SentryNormalizerTests(unittest.TestCase):
    def test_normalizes_raw_issue_to_alert_record(self) -> None:
        raw = {
            "id": "42",
            "shortId": "BACKEND-42",
            "title": "Database timeout",
            "culprit": "sync_worker",
            "level": "error",
            "count": "12",
            "userCount": 3,
            "firstSeen": "2026-06-10T00:00:00Z",
            "lastSeen": "2026-06-10T01:00:00Z",
            "permalink": "https://sentry.example/issue/42",
            "project": {"slug": "backend", "platform": "python"},
            "metadata": {"type": "TimeoutError", "value": "query exceeded 30s"},
        }

        alert = normalize_sentry_issue(raw)

        self.assertEqual(alert.alert_id, "sentry:BACKEND-42")
        self.assertEqual(alert.source, "sentry")
        self.assertEqual(alert.source_alert_id, "BACKEND-42")
        self.assertEqual(alert.project, "backend")
        self.assertEqual(alert.count, 12)
        self.assertEqual(alert.affected_users, 3)
        self.assertEqual(alert.labels["metadata_type"], "TimeoutError")


if __name__ == "__main__":
    unittest.main()
