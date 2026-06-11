from __future__ import annotations

import unittest

from alert_agent.improvement.measurement import measure_applied_proposal_effect


class ImprovementMeasurementTests(unittest.TestCase):
    def test_measure_applied_proposal_effect_reports_reduction(self) -> None:
        proposal = {
            "proposal_id": "ignore-rule-1",
            "type": "ignore_rule",
            "source": "sentry",
            "project": "backend",
            "classification": "dependency",
            "applied": {
                "timestamp": "2026-06-10T00:00:00+00:00",
                "commit_sha": "abc1234",
                "target_file": "config/ignore_rules.json",
                "change_summary": "Added noise suppression",
            },
        }
        audit_events = [
            {"timestamp": "2026-06-01T00:00:00+00:00", "source": "sentry", "project": "backend", "classification": "dependency", "target_status": "ignored"},
            {"timestamp": "2026-06-05T00:00:00+00:00", "source": "sentry", "project": "backend", "classification": "dependency", "target_status": "ignored"},
            {"timestamp": "2026-06-12T00:00:00+00:00", "source": "sentry", "project": "backend", "classification": "dependency", "target_status": "ignored"},
        ]

        result = measure_applied_proposal_effect(proposal, audit_events)

        self.assertEqual(result["before_count"], 2)
        self.assertEqual(result["after_count"], 1)
        self.assertEqual(result["outcome"], "reduced")


if __name__ == "__main__":
    unittest.main()
