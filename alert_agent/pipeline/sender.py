#!/usr/bin/env python3
"""Shared Teams sender stage."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
import shutil
import urllib.parse
from pathlib import Path
from typing import Any

from alert_agent.core.config_loader import load_pipeline_stage_config, load_source_config
from alert_agent.core.review_links import build_review_issue_url
from alert_agent.core.sentry_client import SentryClient
from alert_agent.core.teams import send_to_teams


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [Sender] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def parse_front_matter(content: str) -> tuple[dict[str, str], str]:
    if not content.startswith('---\n'):
        return {}, content
    end = content.find('\n---\n', 4)
    if end < 0:
        return {}, content
    front_matter_block = content[4:end]
    body = content[end + 5:]
    metadata: dict[str, str] = {}
    for line in front_matter_block.splitlines():
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        metadata[key.strip()] = value.strip()
    return metadata, body


def parse_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def truncate_text(text: str, max_length: int = 500) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + '...'


def extract_section(body: str, heading: str) -> str | None:
    match = re.search(rf'##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##|\Z)', body, re.DOTALL)
    return match.group(1).strip() if match else None


def merge_issue_metadata(front_matter: dict[str, str], issue_doc: dict[str, Any]) -> dict[str, str]:
    metadata = dict(front_matter)
    issue_metadata = dict(issue_doc.get('metadata', {}) or {})

    for key in ('source', 'source_type', 'source_alert_id', 'sentry_id', 'policy_pack', 'review_status'):
        value = issue_doc.get(key)
        if value not in (None, '') and not metadata.get(key):
            metadata[key] = str(value)

    for key in ('priority', 'danger'):
        value = dict(issue_doc.get('final', {}) or {}).get(key)
        if value not in (None, '') and not metadata.get(key):
            metadata[key] = str(value)

    if not metadata.get('confidence'):
        confidence = dict(issue_doc.get('review', {}) or {}).get('confidence')
        if confidence not in (None, ''):
            metadata['confidence'] = str(confidence)

    for key in ('project', 'link', 'first_seen', 'last_seen'):
        value = issue_metadata.get(key)
        if value not in (None, '') and not metadata.get(key):
            metadata[key] = str(value)

    return metadata


def load_issue_metadata(output_dir: Path, front_matter: dict[str, str]) -> dict[str, str]:
    issue_id = str(front_matter.get('issue_id') or '').strip()
    if not issue_id:
        return dict(front_matter)

    alert_dir = output_dir / 'alerts'
    for queue_name, review_status in (
        ('approved', 'approved'),
        ('pending', 'pending'),
        ('reviewed', 'reviewed'),
        ('triage', ''),
    ):
        candidate = alert_dir / queue_name / f'{issue_id}.json'
        if not candidate.exists():
            continue
        issue_doc = json.loads(candidate.read_text(encoding='utf-8'))
        merged = merge_issue_metadata(front_matter, issue_doc)
        if review_status and not merged.get('review_status'):
            merged['review_status'] = review_status
        return merged

    return dict(front_matter)


def is_recent_enough(metadata: dict[str, str], max_age_hours: int) -> tuple[bool, str]:
    if max_age_hours <= 0:
        return True, ''

    last_seen = parse_timestamp(metadata.get('last_seen'))
    if last_seen is None:
        return True, ''

    age_hours = (dt.datetime.now(dt.timezone.utc) - last_seen).total_seconds() / 3600
    if age_hours <= max_age_hours:
        return True, ''
    return False, f"last_seen {metadata.get('last_seen')} is older than {max_age_hours}h"


def sentry_issue_exists(config: dict[str, str], sentry_id: str) -> bool:
    base_url = str(config.get('base_url') or '').strip()
    auth_token = str(config.get('auth_token') or '').strip()
    if not base_url or not auth_token or not sentry_id:
        return True

    client = SentryClient(base_url, auth_token)
    try:
        client.get(f"/api/0/issues/{urllib.parse.quote(str(sentry_id))}/")
        return True
    except RuntimeError as exc:
        message = str(exc)
        if ' 404 ' in f' {message} ' or 'does not exist' in message.lower():
            return False
        raise


def priority_color(priority: str) -> str:
    return {
        'P0': 'E81123',
        'P1': 'F7630C',
        'P2': 'FFB900',
        'P3': '107C10',
    }.get(priority.upper(), '666666')


def build_teams_message_card(metadata: dict[str, str], body: str, review_web_base_url: str = "") -> dict[str, Any]:
    issue_id = metadata.get('issue_id', 'unknown')
    priority = metadata.get('priority', 'P3')
    confidence = metadata.get('confidence', '0.0')
    project = metadata.get('project', '')
    danger = metadata.get('danger', '')
    approval_source = metadata.get('approval_source', 'ai_auto')
    source = metadata.get('source', 'alert')

    exec_summary = truncate_text(extract_section(body, 'Executive Summary') or "See details below", 400)
    immediate_action = truncate_text(
        extract_section(body, 'Immediate Action')
        or extract_section(body, 'Immediate Action Required')
        or "Review recommendation",
        600,
    )
    title = f"Alert [{priority}] {issue_id}"
    if source:
        title = f"{source.title()} {title}"
    if approval_source != 'manual' and float(confidence) >= 0.85:
        title += " AI Auto-Approved"

    facts = [
        {"name": "Issue", "value": issue_id},
        {"name": "Source", "value": source},
        {"name": "Priority", "value": priority},
        {"name": "Danger", "value": danger},
    ]
    if project:
        facts.append({"name": "Project", "value": project})
    if confidence:
        facts.append({"name": "AI Confidence", "value": f"{float(confidence):.0%}"})
    if approval_source == 'manual':
        facts.append({"name": "Approval Source", "value": "manual review"})

    card: dict[str, Any] = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"{source} alert {issue_id}",
        "themeColor": priority_color(priority),
        "title": title,
        "sections": [
            {"activityTitle": "Executive Summary", "text": exec_summary, "markdown": True},
            {"facts": facts},
            {"activityTitle": "Immediate Action Required", "text": immediate_action, "markdown": True},
        ],
    }

    source_link = metadata.get('link')
    review_link = build_review_issue_url(review_web_base_url, issue_id, metadata.get('review_status', 'approved') or 'approved')
    actions: list[dict[str, Any]] = []
    if review_link:
        actions.append({"@type": "OpenUri", "name": "Open Review", "targets": [{"os": "default", "uri": review_link}]})
    if source_link:
        actions.append({"@type": "OpenUri", "name": f"Open in {source.title()}", "targets": [{"os": "default", "uri": source_link}]})
    if actions:
        card["potentialAction"] = actions
    return card


def move_to_queue(recommendation_file: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / recommendation_file.name
    if destination.exists():
        suffix = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = target_dir / f"{recommendation_file.stem}-{suffix}.md"
    shutil.move(str(recommendation_file), str(destination))
    return destination


def write_receipt(destination: Path, metadata: dict[str, str], webhook_response: str) -> None:
    receipt = {
        "sentAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "issue_id": metadata.get('issue_id'),
        "alert_id": metadata.get('alert_id'),
        "source": metadata.get('source'),
        "priority": metadata.get('priority'),
        "project": metadata.get('project'),
        "sourceFile": str(destination),
        "webhookResponse": webhook_response[:500],
    }
    destination.with_suffix(destination.suffix + '.receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')


def write_skip_receipt(destination: Path, metadata: dict[str, str], reason: str) -> None:
    receipt = {
        "skippedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "issue_id": metadata.get('issue_id'),
        "alert_id": metadata.get('alert_id'),
        "source": metadata.get('source'),
        "priority": metadata.get('priority'),
        "project": metadata.get('project'),
        "sourceFile": str(destination),
        "reason": reason,
    }
    destination.with_suffix(destination.suffix + '.skip.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')


def run(*, config_file: str, dry_run: bool = False) -> int:
    config = load_pipeline_stage_config('sender', config_file)
    logger.info("=== Sender Starting ===")
    output_dir = Path(config.get('output_dir', './output'))
    recommendations_dir = output_dir / 'alerts' / 'recommendations'
    sent_dir = output_dir / 'alerts' / 'sent'
    skipped_dir = output_dir / 'alerts' / 'skipped'
    recommendation_files = list(recommendations_dir.glob('*.md'))
    if not recommendation_files:
        logger.info("No recommendations to send")
        return 0
    webhook_url = config.get('teams_webhook_url')
    if not webhook_url and not dry_run:
        logger.error("TEAMS_WEBHOOK_URL not configured")
        return 1
    timeout = int(config.get('timeout', 15))
    review_web_base_url = str(config.get('review_web_base_url') or '')
    max_last_seen_age_hours = int(config.get('max_last_seen_age_hours', 48) or 0)
    sentry_source_config: dict[str, str] | None = None
    if str(config.get('validate_sentry_issue_links', 'true')).lower() in {'1', 'true', 'yes', 'on'}:
        try:
            sentry_source_config = load_source_config('sentry', config_file)
        except KeyError:
            sentry_source_config = None

    sent_count = 0
    skipped_count = 0
    failed_count = 0
    for idx, rec_file in enumerate(recommendation_files, 1):
        logger.info("[%d/%d] Processing %s", idx, len(recommendation_files), rec_file.name)
        metadata, body = parse_front_matter(rec_file.read_text(encoding='utf-8'))
        metadata = load_issue_metadata(output_dir, metadata)
        if metadata.get('send_status', 'send') != 'send':
            logger.info("  Skipping: send_status=%s", metadata.get('send_status', 'missing'))
            continue
        is_fresh, fresh_reason = is_recent_enough(metadata, max_last_seen_age_hours)
        if not is_fresh:
            logger.warning("  Skipping stale recommendation: %s", fresh_reason)
            destination = move_to_queue(rec_file, skipped_dir)
            write_skip_receipt(destination, metadata, fresh_reason)
            skipped_count += 1
            continue
        if metadata.get('source') == 'sentry' and sentry_source_config:
            sentry_id = str(metadata.get('sentry_id') or '').strip()
            try:
                exists = sentry_issue_exists(sentry_source_config, sentry_id)
            except Exception as exc:
                logger.error("  Failed validating Sentry issue %s: %s", sentry_id or metadata.get('issue_id'), exc)
                failed_count += 1
                continue
            if not exists:
                reason = f"Sentry issue {sentry_id or metadata.get('issue_id')} no longer exists"
                logger.warning("  Skipping invalid recommendation: %s", reason)
                destination = move_to_queue(rec_file, skipped_dir)
                write_skip_receipt(destination, metadata, reason)
                skipped_count += 1
                continue
        message_card = build_teams_message_card(metadata, body, review_web_base_url)
        if dry_run:
            logger.info("  DRY-RUN mode")
            print(json.dumps(message_card, indent=2))
            sent_count += 1
            continue
        try:
            response = send_to_teams(webhook_url or '', message_card, timeout)
            destination = move_to_queue(rec_file, sent_dir)
            write_receipt(destination, metadata, response)
            sent_count += 1
        except Exception as exc:
            logger.error("  Failed to send: %s", exc)
            failed_count += 1

    logger.info("=== Sender Complete: %d sent, %d skipped, %d failed ===", sent_count, skipped_count, failed_count)
    return 0 if failed_count == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent_config.yaml', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Print messages without sending')
    args = parser.parse_args()
    try:
        return run(config_file=args.config, dry_run=args.dry_run)
    except Exception as exc:
        logger.error("Sender failed: %s", exc, exc_info=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
