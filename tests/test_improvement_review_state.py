from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from alert_agent.improvement.analyzer import analyze_review_cases
from alert_agent.improvement.proposer import build_proposals, write_proposal_bundle
from alert_agent.improvement.review_state import (
    flatten_proposals,
    load_improvement_runs,
    load_review_state,
    review_proposal,
)
from tests.test_self_improve import SAMPLE_CASES


class ImprovementReviewStateTests(unittest.TestCase):
    def test_review_proposal_persists_status_and_note(self) -> None:
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
            updated = review_proposal(
                paths,
                proposal_id=target,
                status="accepted",
                reviewer="danny",
                note="Good candidate",
            )

            state = load_review_state(paths)
            flattened = flatten_proposals(load_improvement_runs(paths), state)
            matching = next(item for item in flattened if item["proposal_id"] == target)

            self.assertEqual(updated["status"], "accepted")
            self.assertEqual(state[target]["status"], "accepted")
            self.assertEqual(matching["reviewer"], "danny")
            self.assertEqual(matching["review_note"], "Good candidate")
            decision_events = (output_dir / "metrics" / "proposal_decisions.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(json.loads(decision_events[-1])["status"], "accepted")

    def test_review_proposal_supports_deferred_status(self) -> None:
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
            updated = review_proposal(
                paths,
                proposal_id=target,
                status="deferred",
                reviewer="danny",
                note="Need human runbook review first",
            )

            self.assertEqual(updated["status"], "deferred")
            flattened = flatten_proposals(load_improvement_runs(paths), load_review_state(paths))
            matching = next(item for item in flattened if item["proposal_id"] == target)
            self.assertEqual(matching["status"], "deferred")


if __name__ == "__main__":
    unittest.main()
