from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alert_agent.improvement.analyzer import analyze_review_cases
from alert_agent.improvement.patcher import generate_patch_for_proposal
from alert_agent.improvement.proposer import build_proposals, write_proposal_bundle
from alert_agent.improvement.review_state import review_proposal
from tests.test_self_improve import SAMPLE_CASES


class ImprovementPatcherTests(unittest.TestCase):
    def _repo_fixture(self, root: Path) -> None:
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "prompts").mkdir(parents=True, exist_ok=True)
        source_root = Path(__file__).resolve().parent.parent
        for relative_path in (
            "config/ignore_rules.json",
            "config/classification_rules.yaml",
            "config/priority_thresholds.yaml",
            "prompts/review_decision.md",
        ):
            target = root / relative_path
            target.write_text((source_root / relative_path).read_text(encoding="utf-8"), encoding="utf-8")

    def test_generate_patch_for_each_supported_proposal_type(self) -> None:
        patterns = analyze_review_cases(SAMPLE_CASES, min_cases=2)
        proposals = build_proposals(patterns, ai_client=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            output_dir = repo_root / "output"
            self._repo_fixture(repo_root)
            write_proposal_bundle(output_dir / "improvement" / "proposals", proposals)
            paths = {
                "output_dir": output_dir,
                "metrics_dir": output_dir / "metrics",
                "alerts_dir": output_dir / "alerts",
                "audit_log": output_dir / "metrics" / "manual_review_actions.jsonl",
                "repo_root": repo_root,
            }

            for proposal in proposals:
                review_proposal(
                    paths,
                    proposal_id=proposal["proposal_id"],
                    status="accepted",
                    reviewer="tester",
                    note="Generate patch",
                )
                patch = generate_patch_for_proposal(paths, proposal["proposal_id"], config_file="config/agent_config.yaml")
                content = patch.read_text(encoding="utf-8")
                self.assertTrue(content.startswith("--- "))
                self.assertIn("+++ b/", content)


if __name__ == "__main__":
    unittest.main()
