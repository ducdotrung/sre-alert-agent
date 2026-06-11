from __future__ import annotations

import unittest

from alert_agent.pipeline.recommendation import build_markdown_with_frontmatter
from alert_agent.pipeline.sender import build_teams_message_card, parse_front_matter


def approved_issue(manual: bool) -> dict[str, object]:
    issue: dict[str, object] = {
        "issue_id": "SENTRY-321",
        "sentry_id": "321",
        "metadata": {
            "project": "frontend",
            "title": "ReferenceError",
            "link": "https://sentry.example.com/issues/321",
        },
        "final": {
            "priority": "P1",
            "danger": "high",
            "class": "frontend-error",
        },
        "review": {
            "confidence": 0.92,
        },
    }
    if manual:
        issue["manual_review"] = {"action": "approve"}
    return issue


class RecommendationSenderTests(unittest.TestCase):
    def test_frontmatter_marks_manual_approvals(self) -> None:
        markdown = build_markdown_with_frontmatter(approved_issue(manual=True), "# Recommendation")
        metadata, body = parse_front_matter(markdown)

        self.assertEqual(metadata["approval_source"], "manual")
        self.assertEqual(metadata["send_status"], "send")
        self.assertEqual(body.strip(), "# Recommendation")

    def test_sender_card_shows_manual_approval_source(self) -> None:
        markdown = build_markdown_with_frontmatter(approved_issue(manual=True), "## Executive Summary\nHello\n\n## Immediate Action\nAct")
        metadata, body = parse_front_matter(markdown)
        card = build_teams_message_card(metadata, body)

        self.assertNotIn("AI Auto-Approved", card["title"])
        facts = {fact["name"]: fact["value"] for fact in card["sections"][1]["facts"]}
        self.assertEqual(facts["Approval Source"], "manual review")


if __name__ == "__main__":
    unittest.main()
