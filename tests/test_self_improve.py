from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alert_agent.improvement.analyzer import analyze_review_cases
from alert_agent.improvement.proposer import build_proposals, write_proposal_bundle
from scripts.review_web import flatten_proposals, load_improvement_runs, render_improvements


SAMPLE_CASES = [
    {
        "issue_id": "BACKEND-1",
        "project": "backend",
        "title": "Database timeout",
        "title_signature": "database timeout",
        "classification": "dependency",
        "priority": "P1",
        "danger": "high",
        "count": 22,
        "users": 0,
        "review_decision": "review",
        "review_confidence": 0.81,
        "notes": ["known noise during nightly backup", "review only if customer-facing"],
        "events": [
            {"action": "ignore", "note": "known noise during nightly backup", "overrides": {}},
        ],
        "manual_history": [],
        "issue": {},
        "status": "ignored",
    },
    {
        "issue_id": "BACKEND-2",
        "project": "backend",
        "title": "Database timeout while sync job runs",
        "title_signature": "database timeout",
        "classification": "dependency",
        "priority": "P1",
        "danger": "high",
        "count": 18,
        "users": 0,
        "review_decision": "review",
        "review_confidence": 0.77,
        "notes": ["known noise during nightly backup"],
        "events": [
            {"action": "ignore", "note": "known noise during nightly backup", "overrides": {}},
        ],
        "manual_history": [],
        "issue": {},
        "status": "ignored",
    },
    {
        "issue_id": "BACKEND-3",
        "project": "backend",
        "title": "Connection reset by peer",
        "title_signature": "connection reset by peer",
        "classification": "unknown",
        "priority": "P1",
        "danger": "medium",
        "count": 9,
        "users": 1,
        "review_decision": "review",
        "review_confidence": 0.69,
        "notes": ["should be dependency, not unknown"],
        "events": [
            {"action": "approve", "note": "should be dependency, not unknown", "overrides": {"classification": "dependency"}},
        ],
        "manual_history": [],
        "issue": {},
        "status": "approved",
    },
    {
        "issue_id": "BACKEND-4",
        "project": "backend",
        "title": "Connection reset by peer on db pool",
        "title_signature": "connection reset by peer",
        "classification": "unknown",
        "priority": "P1",
        "danger": "medium",
        "count": 11,
        "users": 1,
        "review_decision": "review",
        "review_confidence": 0.71,
        "notes": ["should be dependency, not unknown"],
        "events": [
            {"action": "approve", "note": "should be dependency, not unknown", "overrides": {"classification": "dependency"}},
        ],
        "manual_history": [],
        "issue": {},
        "status": "approved",
    },
    {
        "issue_id": "BACKEND-5",
        "project": "backend",
        "title": "Cache warmup alert",
        "title_signature": "cache warmup alert",
        "classification": "availability",
        "priority": "P1",
        "danger": "medium",
        "count": 17,
        "users": 0,
        "review_decision": "review",
        "review_confidence": 0.8,
        "notes": ["only alert if users > 0 or request path is checkout"],
        "events": [
            {"action": "reject", "note": "only alert if users > 0 or request path is checkout", "overrides": {}},
        ],
        "manual_history": [],
        "issue": {},
        "status": "rejected",
    },
    {
        "issue_id": "BACKEND-6",
        "project": "backend",
        "title": "Cache warmup alert secondary",
        "title_signature": "cache warmup alert",
        "classification": "availability",
        "priority": "P1",
        "danger": "medium",
        "count": 13,
        "users": 0,
        "review_decision": "review",
        "review_confidence": 0.83,
        "notes": ["only alert if users > 0 or request path is checkout"],
        "events": [
            {"action": "reject", "note": "only alert if users > 0 or request path is checkout", "overrides": {}},
        ],
        "manual_history": [],
        "issue": {},
        "status": "rejected",
    },
]


class SelfImproveTests(unittest.TestCase):
    def test_analyze_review_cases_detects_patterns(self) -> None:
        patterns = analyze_review_cases(SAMPLE_CASES, min_cases=2)
        kinds = {pattern["kind"] for pattern in patterns}
        self.assertIn("ignore_rule", kinds)
        self.assertIn("classification_rule", kinds)
        self.assertIn("priority_threshold", kinds)
        self.assertIn("prompt_improvement", kinds)

    def test_build_proposals_generates_target_files(self) -> None:
        patterns = analyze_review_cases(SAMPLE_CASES, min_cases=2)
        proposals = build_proposals(patterns, ai_client=None)
        self.assertTrue(proposals)
        by_type = {proposal["type"]: proposal for proposal in proposals}
        self.assertIn("config/ignore_rules.json", by_type["ignore_rule"]["target_files"])
        self.assertIn("config/classification_rules.yaml", by_type["classification_rule"]["target_files"])

    def test_review_web_renders_improvement_bundle(self) -> None:
        patterns = analyze_review_cases(SAMPLE_CASES, min_cases=2)
        proposals = build_proposals(patterns, ai_client=None)
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            bundle_path = write_proposal_bundle(output_dir / "improvement" / "proposals", proposals)
            self.assertTrue(bundle_path.exists())

            paths = {
                "output_dir": output_dir,
                "metrics_dir": output_dir / "metrics",
                "alerts_dir": output_dir / "alerts",
                "audit_log": output_dir / "metrics" / "manual_review_actions.jsonl",
                "repo_root": Path(tmpdir),
            }
            runs = load_improvement_runs(paths)
            flattened = flatten_proposals(runs)
            content = render_improvements(paths)

            self.assertTrue(flattened)
            self.assertIn(b"Improvement Proposals", content)
            self.assertIn(b"ignore_rule", content)


if __name__ == "__main__":
    unittest.main()
