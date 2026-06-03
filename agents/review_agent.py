#!/usr/bin/env python3
"""
Review Agent: AI-powered review and send decision for critical issues.

This agent:
1. Reads triage results (P0/P1 only)
2. Uses AI to assess user/business impact and urgency
3. Decides: send, hold, or needs human review
4. Auto-approves high-confidence issues
5. Moves others to pending for human review
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
    format='[%(asctime)s] [%(levelname)s] [ReviewAgent] %(message)s',
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


def review_with_ai(
    triage_result: dict[str, Any],
    ai_client: PiAIClient,
    repo_root: Path
) -> dict[str, Any]:
    """
    Use AI to review issue and decide whether to send.

    Returns:
        Review result dict with decision, confidence, reasoning
    """
    metadata = triage_result['metadata']
    final_classification = triage_result['final']

    try:
        # Load prompt template
        template = load_prompt_template('review_decision.md', repo_root)

        # Calculate time window
        time_window = calculate_time_window(
            metadata['first_seen'],
            metadata['last_seen']
        )

        # Format prompt
        prompt = format_prompt(
            template,
            issue_id=triage_result['issue_id'],
            title=metadata['title'],
            project=metadata['project'],
            classification=final_classification['class'],
            confidence=final_classification['confidence'],
            priority=final_classification['priority'],
            danger=final_classification['danger'],
            count=metadata['count'],
            users=metadata['users'],
            first_seen=metadata['first_seen'],
            last_seen=metadata['last_seen'],
            time_window=time_window,
            link=metadata['link']
        )

        # Query AI
        response = ai_client.query_json(prompt)

        return {
            'decision': response.get('decision', 'review'),
            'confidence': float(response.get('confidence', 0.5)),
            'reasoning': response.get('reasoning', ''),
            'user_impact': response.get('user_impact', {}),
            'urgency': response.get('urgency', {}),
            'send_reasons': response.get('send_reasons', []),
            'timestamp': dt.datetime.now(dt.timezone.utc).isoformat()
        }

    except Exception as e:
        logger.warning(f"AI review failed for {triage_result['issue_id']}: {e}")
        # Conservative fallback: needs human review
        return {
            'decision': 'review',
            'confidence': 0.0,
            'reasoning': f'AI review failed: {e}',
            'user_impact': {},
            'urgency': {},
            'send_reasons': [],
            'ai_error': str(e),
            'timestamp': dt.datetime.now(dt.timezone.utc).isoformat()
        }


def should_auto_approve(
    triage_result: dict[str, Any],
    review_result: dict[str, Any],
    threshold: float
) -> tuple[bool, str]:
    """
    Determine if issue should be auto-approved for sending.

    Returns:
        (should_approve, reason)
    """
    priority = triage_result['final']['priority']
    decision = review_result['decision']
    confidence = review_result['confidence']

    # Only auto-approve if AI says "send"
    if decision != 'send':
        return False, f"AI decision is '{decision}', not 'send'"

    # P0 or P1 with high confidence → auto-approve
    if priority in ('P0', 'P1') and confidence >= threshold:
        return True, f"{priority} with high confidence ({confidence:.2f} >= {threshold})"

    return False, f"Confidence {confidence:.2f} below threshold {threshold}"


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent_config.yaml', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Test mode, no AI calls')
    args = parser.parse_args()

    try:
        repo_root = get_repo_root()
        config = load_agent_config('review_agent', args.config)

        logger.info("=== Review Agent Starting ===")

        # Setup paths
        output_dir = Path(config.get('output_dir', './output'))
        triage_dir = output_dir / 'alerts' / 'triage'
        reviewed_dir = output_dir / 'alerts' / 'reviewed'
        approved_dir = output_dir / 'alerts' / 'approved'
        pending_dir = output_dir / 'alerts' / 'pending'

        for directory in [reviewed_dir, approved_dir, pending_dir]:
            directory.mkdir(parents=True, exist_ok=True)

        # Find triage results
        triage_files = list(triage_dir.glob('*.json'))

        if not triage_files:
            logger.info("No triage results to review")
            return 0

        logger.info(f"Found {len(triage_files)} triage results")

        # Filter by priority
        filter_priorities = set(config.get('filter_priorities', ['P0', 'P1']))
        filtered_triages = []

        for triage_file in triage_files:
            with triage_file.open('r', encoding='utf-8') as f:
                triage_result = json.load(f)

            priority = triage_result['final']['priority']
            if priority in filter_priorities:
                filtered_triages.append((triage_file, triage_result))

        logger.info(f"Filtered to {len(filtered_triages)} critical issues ({', '.join(filter_priorities)})")

        if not filtered_triages:
            logger.info("No critical issues to review")
            return 0

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
            logger.error("Review agent requires AI to be enabled")
            return 1

        # Review each critical issue
        auto_approved_count = 0
        pending_count = 0
        threshold = config.get('auto_send_confidence_threshold', 0.85)

        for idx, (triage_file, triage_result) in enumerate(filtered_triages, 1):
            issue_id = triage_result['issue_id']
            logger.info(f"[{idx}/{len(filtered_triages)}] Reviewing {issue_id}")

            # AI review
            review_result = review_with_ai(triage_result, ai_client, repo_root)

            logger.info(f"  Decision: {review_result['decision']} "
                       f"(confidence: {review_result['confidence']:.2f})")

            # Combine triage + review results
            combined_result = {
                **triage_result,
                'review': review_result
            }

            # Save reviewed result
            reviewed_file = reviewed_dir / f"{issue_id}.json"
            with reviewed_file.open('w', encoding='utf-8') as f:
                json.dump(combined_result, f, indent=2)

            # Auto-approve or move to pending
            should_approve, reason = should_auto_approve(
                triage_result,
                review_result,
                threshold
            )

            if should_approve:
                logger.info(f"  Auto-approved: {reason}")
                approved_file = approved_dir / f"{issue_id}.json"
                with approved_file.open('w', encoding='utf-8') as f:
                    json.dump(combined_result, f, indent=2)
                auto_approved_count += 1
            else:
                logger.info(f"  Needs review: {reason}")
                pending_file = pending_dir / f"{issue_id}.json"
                with pending_file.open('w', encoding='utf-8') as f:
                    json.dump(combined_result, f, indent=2)
                pending_count += 1

        logger.info(f"=== Review Complete: {auto_approved_count} auto-approved, {pending_count} pending human review ===")

        # Return exit code 2 if any issues were approved (signals to trigger recommendation agent)
        return 2 if auto_approved_count > 0 else 0

    except Exception as e:
        logger.error(f"Review agent failed: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
