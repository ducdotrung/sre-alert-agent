#!/usr/bin/env python3
"""Shared recommendation stage."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any

from alert_agent.core.ai_client import PiAIClient, format_prompt
from alert_agent.core.config_loader import get_repo_root, load_pipeline_stage_config, load_policy_pack


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [RecommendationAgent] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def calculate_time_window(first_seen: str, last_seen: str) -> str:
    try:
        first = dt.datetime.fromisoformat(first_seen.replace('Z', '+00:00'))
        last = dt.datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
        delta = last - first
        if delta.total_seconds() < 3600:
            return f"{int(delta.total_seconds() / 60)} minutes"
        if delta.total_seconds() < 86400:
            return f"{int(delta.total_seconds() / 3600)} hours"
        return f"{int(delta.total_seconds() / 86400)} days"
    except Exception:
        return "unknown"


def load_recommendation_prompt(repo_root: Path, config_file: str, pack_name: str) -> str:
    pack = load_policy_pack(pack_name, config_file)
    prompt_path = repo_root / str(dict(pack.get("prompts", {}) or {}).get("recommendation", "prompts/recommendation_generate.md"))
    return prompt_path.read_text(encoding='utf-8')


def generate_recommendation(
    approved_issue: dict[str, Any],
    ai_client: PiAIClient,
    repo_root: Path,
    config_file: str,
) -> str:
    metadata = approved_issue['metadata']
    final_classification = approved_issue['final']
    review = approved_issue.get('review', {})

    try:
        template = load_recommendation_prompt(repo_root, config_file, str(approved_issue.get('policy_pack') or 'sentry-default'))
        time_window = calculate_time_window(metadata['first_seen'], metadata['last_seen'])
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
            user_impact=json.dumps(review.get('user_impact', {}), indent=2),
            urgency=json.dumps(review.get('urgency', {}), indent=2),
        )
        return ai_client.query(
            prompt,
            metadata={
                'issue_id': approved_issue['issue_id'],
                'operation': 'recommendation_generate',
                'project': metadata['project'],
                'source': approved_issue.get('source'),
            }
        )
    except Exception as exc:
        logger.warning("AI recommendation generation failed for %s: %s", approved_issue['issue_id'], exc)
        return generate_fallback_recommendation(approved_issue, str(exc))


def generate_fallback_recommendation(approved_issue: dict[str, Any], error: str) -> str:
    metadata = approved_issue['metadata']
    final = approved_issue['final']
    review = approved_issue.get('review', {})
    approval_source = 'manual' if approved_issue.get('manual_review', {}).get('action') == 'approve' else 'ai_auto'
    return f"""---
issue_id: {approved_issue['issue_id']}
alert_id: {approved_issue.get('alert_id', '')}
source: {approved_issue.get('source', '')}
source_type: {approved_issue.get('source_type', '')}
source_alert_id: {approved_issue.get('source_alert_id', '')}
sentry_id: {approved_issue.get('sentry_id', '')}
policy_pack: {approved_issue.get('policy_pack', '')}
priority: {final['priority']}
danger: {final['danger']}
project: {metadata['project']}
send_status: send
confidence: {review.get('confidence', 0.0)}
ai_error: true
ai_generated: false
approval_source: {approval_source}
review_status: approved
link: {metadata['link']}
timestamp: {dt.datetime.now(dt.timezone.utc).isoformat()}
---

# {final['priority']}: {metadata['title']}

**AI recommendation generation failed**: {error}

## Issue Details

- **Source**: {approved_issue.get('source', 'unknown')}
- **Project**: {metadata['project']}
- **Classification**: {final['class']}
- **Count**: {metadata['count']} errors
- **Affected Users**: {metadata['users']}
- **Last Seen**: {metadata['last_seen']}

## Manual Investigation Required

1. Open source issue: {metadata['link']}
2. Review stack traces and event samples
3. Check recent deployments and config changes
4. Correlate with metrics and logs in monitoring dashboards

## Classification Reasoning

{final.get('reasoning', 'No reasoning provided')}

---
_Fallback recommendation due to AI error. Manual investigation required._
"""


def build_markdown_with_frontmatter(approved_issue: dict[str, Any], recommendation_markdown: str) -> str:
    metadata = approved_issue['metadata']
    final = approved_issue['final']
    review = approved_issue.get('review', {})
    approval_source = 'manual' if approved_issue.get('manual_review', {}).get('action') == 'approve' else 'ai_auto'
    if recommendation_markdown.startswith('---'):
        return recommendation_markdown
    front_matter = f"""---
issue_id: {approved_issue['issue_id']}
alert_id: {approved_issue.get('alert_id', '')}
source: {approved_issue.get('source', '')}
source_type: {approved_issue.get('source_type', '')}
source_alert_id: {approved_issue.get('source_alert_id', '')}
sentry_id: {approved_issue.get('sentry_id', '')}
policy_pack: {approved_issue.get('policy_pack', '')}
priority: {final['priority']}
danger: {final['danger']}
project: {metadata['project']}
send_status: send
confidence: {review.get('confidence', 0.0)}
ai_generated: true
approval_source: {approval_source}
review_status: approved
link: {metadata['link']}
timestamp: {dt.datetime.now(dt.timezone.utc).isoformat()}
---

"""
    return front_matter + recommendation_markdown


def run(*, config_file: str, dry_run: bool = False) -> int:
    repo_root = get_repo_root()
    config = load_pipeline_stage_config('recommendation', config_file)
    logger.info("=== Recommendation Agent Starting ===")

    output_dir = Path(config.get('output_dir', './output'))
    approved_dir = output_dir / 'alerts' / 'approved'
    recommendations_dir = output_dir / 'alerts' / 'recommendations'
    recommendations_dir.mkdir(parents=True, exist_ok=True)

    approved_files = list(approved_dir.glob('*.json'))
    if not approved_files:
        logger.info("No approved issues to generate recommendations for")
        return 0

    ai_client = None
    if config.get('ai', {}).get('enabled', False) and not dry_run:
        ai_config = config['ai']
        ai_client = PiAIClient(
            provider=ai_config['provider'],
            model=ai_config.get('model'),
            api_key=ai_config.get('api_key'),
            metrics_dir=config.get('metrics_dir'),
            agent_name='recommendation_agent',
            run_id=config.get('run_id'),
            pricing=config.get('ai_pricing'),
        )
    else:
        logger.warning("AI disabled for recommendation agent, generating fallback recommendations")

    generated_count = 0
    for idx, approved_file in enumerate(approved_files, 1):
        approved_issue = json.loads(approved_file.read_text(encoding='utf-8'))
        issue_id = approved_issue['issue_id']
        logger.info("[%d/%d] Generating recommendation for %s", idx, len(approved_files), issue_id)
        if ai_client is not None:
            recommendation_md = generate_recommendation(approved_issue, ai_client, repo_root, config_file)
        else:
            recommendation_md = generate_fallback_recommendation(
                approved_issue,
                "AI disabled by configuration or budget enforcement",
            )
        final_md = build_markdown_with_frontmatter(approved_issue, recommendation_md)
        (recommendations_dir / f"{issue_id}.md").write_text(final_md, encoding='utf-8')
        generated_count += 1

    logger.info("=== Recommendation Generation Complete: %d recommendations ===", generated_count)
    return 2 if generated_count > 0 else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent_config.yaml', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Test mode, no AI calls')
    args = parser.parse_args()
    try:
        return run(config_file=args.config, dry_run=args.dry_run)
    except Exception as exc:
        logger.error("Recommendation agent failed: %s", exc, exc_info=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
