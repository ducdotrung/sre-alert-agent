from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from alert_agent.commands.run_self_improve import run as run_self_improve
from alert_agent.improvement.analyzer import analyze_review_cases
from alert_agent.improvement.proposer import build_proposals, write_proposal_bundle
from alert_agent.improvement.review_state import review_proposal
from scripts.review_web import (
    flatten_proposals,
    load_improvement_runs,
    render_improvement_detail,
    render_improvements,
)


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
            proposal_path = write_proposal_bundle(output_dir / "improvement" / "proposals", proposals)
            self.assertTrue(proposal_path.exists())
            manifest = json.loads((output_dir / "improvement" / "proposals" / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["proposal_ids"]), len(proposals))

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

    def test_review_web_uses_review_state_and_detail_view(self) -> None:
        patterns = analyze_review_cases(SAMPLE_CASES, min_cases=2)
        proposals = build_proposals(patterns, ai_client=None)
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            write_proposal_bundle(output_dir / "improvement" / "proposals", proposals)

            paths = {
                "output_dir": output_dir,
                "metrics_dir": output_dir / "metrics",
                "alerts_dir": output_dir / "alerts",
                "audit_log": output_dir / "metrics" / "manual_review_actions.jsonl",
                "repo_root": Path(tmpdir),
            }
            target = proposals[0]["proposal_id"]
            review_proposal(
                paths,
                proposal_id=target,
                status="accepted",
                reviewer="danny",
                note="Safe to land as config-only follow-up",
            )

            runs = load_improvement_runs(paths)
            flattened = flatten_proposals(runs, None)
            listed = render_improvements(paths)
            detail = render_improvement_detail(paths, target)

            matching = next(item for item in flattened if item["proposal_id"] == target)
            self.assertEqual(matching["status"], "accepted")
            self.assertIn(b"accepted", listed)
            self.assertIn(b"danny", listed)
            self.assertIn(b"Current Review State", detail)
            self.assertIn(b"Safe to land as config-only follow-up", detail)

    def test_run_self_improve_skips_patterns_already_marked_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            output_dir = repo_root / "output"
            metrics_dir = output_dir / "metrics"
            alerts_dir = output_dir / "alerts"
            metrics_dir.mkdir(parents=True, exist_ok=True)
            for status in ("pending", "approved", "rejected", "ignored"):
                (alerts_dir / status).mkdir(parents=True, exist_ok=True)

            config_path = repo_root / "agent_config.yaml"
            config_path.write_text(
                f"""
common:
  output_dir: {output_dir}
  metrics_dir: {metrics_dir}
self_improve:
  enabled: true
  output_dir: {output_dir / "improvement"}
  min_review_events: 2
  max_proposals: 12
  ai:
    enabled: false
""",
                encoding="utf-8",
            )

            issue_doc = {
                "source": "sentry",
                "policy_pack": "sentry-default",
                "metadata": {
                    "project": "backend",
                    "title": "Database timeout",
                    "count": 22,
                    "users": 0,
                },
                "final": {
                    "class": "dependency",
                    "priority": "P1",
                    "danger": "high",
                },
                "review": {"decision": "review", "confidence": 0.8},
            }
            (alerts_dir / "ignored" / "BACKEND-1.json").write_text(json.dumps({"issue_id": "BACKEND-1", **issue_doc}, indent=2), encoding="utf-8")
            (alerts_dir / "ignored" / "BACKEND-2.json").write_text(json.dumps({"issue_id": "BACKEND-2", **issue_doc}, indent=2), encoding="utf-8")
            audit_events = [
                {
                    "timestamp": "2026-06-11T00:00:00+00:00",
                    "issue_id": "BACKEND-1",
                    "source": "sentry",
                    "policy_pack": "sentry-default",
                    "action": "ignore",
                    "note": "known noise during nightly backup",
                    "target_status": "ignored",
                    "classification": "dependency",
                    "priority": "P1",
                    "danger": "high",
                    "project": "backend",
                },
                {
                    "timestamp": "2026-06-11T00:05:00+00:00",
                    "issue_id": "BACKEND-2",
                    "source": "sentry",
                    "policy_pack": "sentry-default",
                    "action": "ignore",
                    "note": "known noise during nightly backup",
                    "target_status": "ignored",
                    "classification": "dependency",
                    "priority": "P1",
                    "danger": "high",
                    "project": "backend",
                },
            ]
            (metrics_dir / "manual_review_actions.jsonl").write_text(
                "\n".join(json.dumps(item) for item in audit_events) + "\n",
                encoding="utf-8",
            )

            config = {
                "enabled": True,
                "output_dir": str(output_dir / "improvement"),
                "metrics_dir": str(metrics_dir),
                "min_review_events": 2,
                "max_proposals": 12,
                "ai": {"enabled": False},
            }
            first_exit = run_self_improve(str(config_path), config, force=True, dry_run=False)
            self.assertEqual(first_exit, 2)

            proposal_dir = output_dir / "improvement" / "proposals"
            proposal_ids = json.loads((proposal_dir / "latest.json").read_text(encoding="utf-8"))["proposal_ids"]
            from alert_agent.improvement.decisions import record_proposal_applied

            paths = {
                "output_dir": output_dir,
                "metrics_dir": metrics_dir,
                "alerts_dir": alerts_dir,
                "audit_log": metrics_dir / "manual_review_actions.jsonl",
                "repo_root": repo_root,
            }
            for proposal_id in proposal_ids:
                review_proposal(
                    paths,
                    proposal_id=proposal_id,
                    status="accepted",
                    reviewer="tester",
                    note="landed",
                )
                record_proposal_applied(
                    paths,
                    proposal_id=proposal_id,
                    commit_sha="abc1234",
                )

            second_exit = run_self_improve(str(config_path), config, force=True, dry_run=False)
            self.assertEqual(second_exit, 0)
            latest_ids = json.loads((proposal_dir / "latest.json").read_text(encoding="utf-8"))["proposal_ids"]
            self.assertEqual(latest_ids, [])


if __name__ == "__main__":
    unittest.main()
