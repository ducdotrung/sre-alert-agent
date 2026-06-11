#!/usr/bin/env python3
"""Shared review stage for triaged alerts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any

from alert_agent.core.ai_client import PiAIClient, format_prompt
from alert_agent.core.config_loader import (
    get_repo_root,
    load_pipeline_stage_config,
    load_policy_pack,
)
from alert_agent.core.pending_review_notifications import (
    load_notification_state,
    notify_pending_issue,
    save_notification_state,
)


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [ReviewAgent] %(message)s',
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


def load_review_prompt(repo_root: Path, config_file: str, pack_name: str) -> str:
    pack = load_policy_pack(pack_name, config_file)
    prompt_path = repo_root / str(dict(pack.get("prompts", {}) or {}).get("review", "prompts/review_decision.md"))
    return prompt_path.read_text(encoding='utf-8')


def review_with_ai(
    triage_result: dict[str, Any],
    ai_client: PiAIClient,
    repo_root: Path,
    config_file: str,
) -> dict[str, Any]:
    metadata = triage_result['metadata']
    final_classification = triage_result['final']

    try:
        template = load_review_prompt(repo_root, config_file, str(triage_result.get('policy_pack') or 'sentry-default'))
        time_window = calculate_time_window(metadata['first_seen'], metadata['last_seen'])
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
            link=metadata['link'],
        )
        response = ai_client.query_json(
            prompt,
            metadata={
                'issue_id': triage_result['issue_id'],
                'operation': 'review_decision',
                'project': metadata['project'],
                'source': triage_result.get('source'),
            }
        )
        return {
            'decision': response.get('decision', 'review'),
            'confidence': float(response.get('confidence', 0.5)),
            'reasoning': response.get('reasoning', ''),
            'user_impact': response.get('user_impact', {}),
            'urgency': response.get('urgency', {}),
            'send_reasons': response.get('send_reasons', []),
            'timestamp': dt.datetime.now(dt.timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.warning("AI review failed for %s: %s", triage_result['issue_id'], exc)
        return {
            'decision': 'review',
            'confidence': 0.0,
            'reasoning': f'AI review failed: {exc}',
            'user_impact': {},
            'urgency': {},
            'send_reasons': [],
            'ai_error': str(exc),
            'timestamp': dt.datetime.now(dt.timezone.utc).isoformat(),
        }


def should_auto_approve(
    triage_result: dict[str, Any],
    review_result: dict[str, Any],
    threshold: float,
) -> tuple[bool, str]:
    priority = triage_result['final']['priority']
    decision = review_result['decision']
    confidence = review_result['confidence']
    if decision != 'send':
        return False, f"AI decision is '{decision}', not 'send'"
    if priority in ('P0', 'P1') and confidence >= threshold:
        return True, f"{priority} with high confidence ({confidence:.2f} >= {threshold})"
    return False, f"Confidence {confidence:.2f} below threshold {threshold}"


def run(*, config_file: str, dry_run: bool = False) -> int:
    repo_root = get_repo_root()
    config = load_pipeline_stage_config('review', config_file)
    logger.info("=== Review Agent Starting ===")

    output_dir = Path(config.get('output_dir', './output'))
    triage_dir = output_dir / 'alerts' / 'triage'
    reviewed_dir = output_dir / 'alerts' / 'reviewed'
    approved_dir = output_dir / 'alerts' / 'approved'
    pending_dir = output_dir / 'alerts' / 'pending'
    for directory in [reviewed_dir, approved_dir, pending_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    triage_files = list(triage_dir.glob('*.json'))
    if not triage_files:
        logger.info("No triage results to review")
        return 0

    filter_priorities = set(config.get('filter_priorities', ['P0', 'P1']))
    filtered_triages: list[tuple[Path, dict[str, Any]]] = []
    for triage_file in triage_files:
        triage_result = json.loads(triage_file.read_text(encoding='utf-8'))
        if triage_result['final']['priority'] in filter_priorities:
            filtered_triages.append((triage_file, triage_result))

    logger.info("Filtered to %d critical issues (%s)", len(filtered_triages), ', '.join(filter_priorities))
    if not filtered_triages:
        return 0

    notification_state = load_notification_state(config)
    if config.get('ai', {}).get('enabled', False) and not dry_run:
        ai_config = config['ai']
        ai_client = PiAIClient(
            provider=ai_config['provider'],
            model=ai_config.get('model'),
            api_key=ai_config.get('api_key'),
            metrics_dir=config.get('metrics_dir'),
            agent_name='review_agent',
            run_id=config.get('run_id'),
            pricing=config.get('ai_pricing'),
        )
    else:
        logger.error("Review agent requires AI to be enabled")
        return 1

    auto_approved_count = 0
    pending_count = 0
    threshold = float(config.get('auto_send_confidence_threshold', 0.85))

    for idx, (_, triage_result) in enumerate(filtered_triages, 1):
        issue_id = triage_result['issue_id']
        logger.info("[%d/%d] Reviewing %s", idx, len(filtered_triages), issue_id)
        review_result = review_with_ai(triage_result, ai_client, repo_root, config_file)
        combined_result = {**triage_result, 'review': review_result}
        (reviewed_dir / f"{issue_id}.json").write_text(json.dumps(combined_result, indent=2), encoding='utf-8')
        should_approve, reason = should_auto_approve(triage_result, review_result, threshold)

        if should_approve:
            logger.info("  Auto-approved: %s", reason)
            (approved_dir / f"{issue_id}.json").write_text(json.dumps(combined_result, indent=2), encoding='utf-8')
            auto_approved_count += 1
        else:
            logger.info("  Needs review: %s", reason)
            (pending_dir / f"{issue_id}.json").write_text(json.dumps(combined_result, indent=2), encoding='utf-8')
            try:
                if notify_pending_issue(combined_result, config, notification_state, dry_run=dry_run):
                    logger.info("  Pending review notification emitted")
            except Exception as exc:
                logger.warning("  Pending review notification failed: %s", exc)
            pending_count += 1

    if not dry_run:
        save_notification_state(config, notification_state)
    logger.info("=== Review Complete: %d auto-approved, %d pending human review ===", auto_approved_count, pending_count)
    return 2 if auto_approved_count > 0 else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent_config.yaml', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Test mode, no AI calls')
    args = parser.parse_args()
    try:
        return run(config_file=args.config, dry_run=args.dry_run)
    except Exception as exc:
        logger.error("Review agent failed: %s", exc, exc_info=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
