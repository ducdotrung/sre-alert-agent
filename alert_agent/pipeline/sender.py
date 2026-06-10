#!/usr/bin/env python3
"""Shared Teams sender stage."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from alert_agent.core.config_loader import load_agent_config
from alert_agent.core.review_links import build_review_issue_url
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


def truncate_text(text: str, max_length: int = 500) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + '...'


def extract_section(body: str, heading: str) -> str | None:
    match = re.search(rf'##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##|\Z)', body, re.DOTALL)
    return match.group(1).strip() if match else None


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
    source = (metadata.get('source') or '').strip() or ('sentry' if metadata.get('link') else 'alert')

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


def move_to_sent(recommendation_file: Path, sent_dir: Path) -> Path:
    sent_dir.mkdir(parents=True, exist_ok=True)
    destination = sent_dir / recommendation_file.name
    if destination.exists():
        suffix = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = sent_dir / f"{recommendation_file.stem}-{suffix}.md"
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


def run(*, config_file: str, dry_run: bool = False) -> int:
    config = load_agent_config('sender', config_file)
    logger.info("=== Sender Starting ===")
    output_dir = Path(config.get('output_dir', './output'))
    recommendations_dir = output_dir / 'alerts' / 'recommendations'
    sent_dir = output_dir / 'alerts' / 'sent'
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

    sent_count = 0
    failed_count = 0
    for idx, rec_file in enumerate(recommendation_files, 1):
        logger.info("[%d/%d] Processing %s", idx, len(recommendation_files), rec_file.name)
        metadata, body = parse_front_matter(rec_file.read_text(encoding='utf-8'))
        if metadata.get('send_status', 'send') != 'send':
            logger.info("  Skipping: send_status=%s", metadata.get('send_status', 'missing'))
            continue
        message_card = build_teams_message_card(metadata, body, review_web_base_url)
        if dry_run:
            logger.info("  DRY-RUN mode")
            print(json.dumps(message_card, indent=2))
            sent_count += 1
            continue
        try:
            response = send_to_teams(webhook_url or '', message_card, timeout)
            destination = move_to_sent(rec_file, sent_dir)
            write_receipt(destination, metadata, response)
            sent_count += 1
        except Exception as exc:
            logger.error("  Failed to send: %s", exc)
            failed_count += 1

    logger.info("=== Sender Complete: %d sent, %d failed ===", sent_count, failed_count)
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
