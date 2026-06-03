#!/usr/bin/env python3
"""
Recommendation Agent: Generate actionable remediation recommendations.

This agent:
1. Reads approved issues (from review agent)
2. Uses AI to generate detailed, actionable recommendations
3. Formats rich Markdown for Teams notification
4. Outputs recommendation files for sender
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from shared.ai_client import PiAIClient, format_prompt, load_prompt_template
from shared.config_loader import get_repo_root, load_agent_config


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [RecommendationAgent] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def calculate_time_window(first_seen: str, last_seen: str) -> str:
    """Calculate human-readable time window."""
    try:
        first = dt.datetime.fromisoformat(first_seen.replace('Z', '+00:00'))
        last = dt.datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
        delta = last - first

        if delta.total_seconds() < 3600:
            return f"{int(delta.total_seconds() / 60)} minutes"
        elif delta.total_seconds() < 86400:
            return f"{int(delta.total_seconds() / 3600)} hours"
        else:
            return f"{int(delta.total_seconds() / 86400)} days"
    except Exception:
        return "unknown"


def generate_recommendation(
    approved_issue: dict[str, Any],
    ai_client: PiAIClient,
    repo_root: Path
) -> str:
    """
    Use AI to generate actionable recommendations.

    Returns:
        Markdown-formatted recommendation text
    """
    metadata = approved_issue['metadata']
    final_classification = approved_issue['final']
    review = approved_issue.get('review', {})

    try:
        # Load prompt template
        template = load_prompt_template('recommendation_generate.md', repo_root)

        # Calculate time window
        time_window = calculate_time_window(
            metadata['first_seen'],
            metadata['last_seen']
        )

        # Format user_impact and urgency as JSON strings
        user_impact_str = json.dumps(review.get('user_impact', {}), indent=2)
        urgency_str = json.dumps(review.get('urgency', {}), indent=2)

        # Format prompt
        prompt = format_prompt(
            template,
            issue_id=approved_issue['issue_id'],
            title=metadata['title'],
            project=metadata['project'],
            classification=final_classification['class'],
            priority=final_classification['priority'],
            danger=final_classification['danger'],
            count=metadata['count'],
            users=metadata['users'],
            time_window=time_window,
            first_seen=metadata['first_seen'],
            last_seen=metadata['last_seen'],
            culprit=metadata['culprit'],
            platform=metadata['platform'],
            level=metadata['level'],
            link=metadata['link'],
            review_decision=review.get('decision', 'send'),
            review_confidence=review.get('confidence', 0.0),
            user_impact=user_impact_str,
            urgency=urgency_str
        )

        # Query AI (returns markdown, not JSON)
        markdown = ai_client.query(prompt)

        return markdown

    except Exception as e:
        logger.warning(f"AI recommendation generation failed for {approved_issue['issue_id']}: {e}")

        # Fallback: generate basic recommendation
        return generate_fallback_recommendation(approved_issue, str(e))


def generate_fallback_recommendation(approved_issue: dict[str, Any], error: str) -> str:
    """Generate basic recommendation when AI fails."""
    metadata = approved_issue['metadata']
    final = approved_issue['final']
    review = approved_issue.get('review', {})

    return f"""---
issue_id: {approved_issue['issue_id']}
priority: {final['priority']}
confidence: {review.get('confidence', 0.0)}
ai_error: true
---

# {final['priority']}: {metadata['title']}

**AI recommendation generation failed**: {error}

## Issue Details

- **Project**: {metadata['project']}
- **Classification**: {final['class']}
- **Count**: {metadata['count']} errors
- **Affected Users**: {metadata['users']}
- **Last Seen**: {metadata['last_seen']}

## Manual Investigation Required

1. Open Sentry issue: {metadata['link']}
2. Review stack traces and event samples
3. Check recent deployments and config changes
4. Correlate with metrics/logs in monitoring dashboards

## Classification Reasoning

{final.get('reasoning', 'No reasoning provided')}

---
_Fallback recommendation due to AI error. Manual investigation required._
"""


def build_markdown_with_frontmatter(
    approved_issue: dict[str, Any],
    recommendation_markdown: str
) -> str:
    """
    Build final markdown with front matter for sender.

    Front matter format expected by Teams sender.
    """
    metadata = approved_issue['metadata']
    final = approved_issue['final']
    review = approved_issue.get('review', {})

    # Extract front matter from AI response if present
    if recommendation_markdown.startswith('---'):
        # AI already included front matter, just ensure critical fields
        return recommendation_markdown

    # Add front matter
    front_matter = f"""---
issue_id: {approved_issue['issue_id']}
sentry_id: {approved_issue['sentry_id']}
priority: {final['priority']}
danger: {final['danger']}
project: {metadata['project']}
send_status: send
confidence: {review.get('confidence', 0.0)}
ai_generated: true
timestamp: {dt.datetime.now(dt.timezone.utc).isoformat()}
---

"""
    return front_matter + recommendation_markdown


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent_config.yaml', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Test mode, no AI calls')
    args = parser.parse_args()

    try:
        repo_root = get_repo_root()
        config = load_agent_config('recommendation_agent', args.config)

        logger.info("=== Recommendation Agent Starting ===")

        # Setup paths
        output_dir = Path(config.get('output_dir', './output'))
        approved_dir = output_dir / 'alerts' / 'approved'
        recommendations_dir = output_dir / 'alerts' / 'recommendations'

        recommendations_dir.mkdir(parents=True, exist_ok=True)

        # Find approved issues
        approved_files = list(approved_dir.glob('*.json'))

        if not approved_files:
            logger.info("No approved issues to generate recommendations for")
            return 0

        logger.info(f"Found {len(approved_files)} approved issues")

        # Initialize AI client
        if config.get('ai', {}).get('enabled', False) and not args.dry_run:
            ai_config = config['ai']
            ai_client = PiAIClient(
                provider=ai_config['provider'],
                model=ai_config.get('model'),
                api_key=ai_config.get('api_key')
            )
            logger.info(f"AI client initialized (provider={ai_config['provider']})")
        else:
            logger.error("Recommendation agent requires AI to be enabled")
            return 1

        # Generate recommendations
        generated_count = 0

        for idx, approved_file in enumerate(approved_files, 1):
            with approved_file.open('r', encoding='utf-8') as f:
                approved_issue = json.load(f)

            issue_id = approved_issue['issue_id']
            logger.info(f"[{idx}/{len(approved_files)}] Generating recommendation for {issue_id}")

            # Generate with AI
            recommendation_md = generate_recommendation(approved_issue, ai_client, repo_root)

            # Add front matter
            final_md = build_markdown_with_frontmatter(approved_issue, recommendation_md)

            # Save to file
            output_file = recommendations_dir / f"{issue_id}.md"
            output_file.write_text(final_md, encoding='utf-8')

            logger.info(f"  Saved: {output_file}")
            generated_count += 1

        logger.info(f"=== Recommendation Generation Complete: {generated_count} recommendations ===")

        # Return exit code 2 if recommendations generated (signals sender to run)
        return 2 if generated_count > 0 else 0

    except Exception as e:
        logger.error(f"Recommendation agent failed: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
