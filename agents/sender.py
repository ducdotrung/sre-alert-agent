#!/usr/bin/env python3
"""
Sender: Send approved recommendations to Microsoft Teams.

This agent:
1. Reads recommendation markdown files
2. Builds Teams MessageCard JSON
3. POSTs to Teams webhook
4. Moves sent files and creates receipts
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from shared.config_loader import get_repo_root, load_agent_config


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [Sender] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def parse_front_matter(content: str) -> tuple[dict[str, str], str]:
    """
    Parse YAML front matter from markdown.

    Returns:
        (metadata_dict, body_content)
    """
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
    """Truncate text to max length, add ellipsis."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + '...'


def extract_executive_summary(body: str) -> str | None:
    """Extract executive summary section from markdown."""
    match = re.search(r'##\s+Executive Summary\s*\n(.*?)(?=\n##|\Z)', body, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def extract_immediate_action(body: str) -> str | None:
    """Extract immediate action section from markdown."""
    match = re.search(r'##\s+Immediate Action(?:\s+Required)?\s*\n(.*?)(?=\n##|\Z)', body, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def priority_color(priority: str) -> str:
    """Get Teams message color for priority."""
    return {
        'P0': 'E81123',  # Red
        'P1': 'F7630C',  # Orange
        'P2': 'FFB900',  # Yellow
        'P3': '107C10',  # Green
    }.get(priority.upper(), '666666')


def build_teams_message_card(
    metadata: dict[str, str],
    body: str
) -> dict[str, Any]:
    """
    Build Microsoft Teams MessageCard JSON.

    Args:
        metadata: Front matter metadata
        body: Markdown body

    Returns:
        Teams MessageCard dict
    """
    issue_id = metadata.get('issue_id', 'unknown')
    priority = metadata.get('priority', 'P3')
    confidence = metadata.get('confidence', '0.0')
    project = metadata.get('project', '')
    danger = metadata.get('danger', '')

    # Extract key sections
    exec_summary = extract_executive_summary(body) or "See details below"
    immediate_action = extract_immediate_action(body) or "Review recommendation"

    # Truncate for Teams (avoid overly long messages)
    exec_summary = truncate_text(exec_summary, 400)
    immediate_action = truncate_text(immediate_action, 600)

    # Build message
    title = f"🚨 Sentry Alert [{priority}] {issue_id}"
    if float(confidence) >= 0.85:
        title += " 🤖 AI Auto-Approved"

    facts = [
        {"name": "Issue", "value": issue_id},
        {"name": "Priority", "value": priority},
        {"name": "Danger", "value": danger},
    ]

    if project:
        facts.append({"name": "Project", "value": project})

    if confidence:
        facts.append({"name": "AI Confidence", "value": f"{float(confidence):.0%}"})

    # Build card
    card: dict[str, Any] = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"Sentry alert {issue_id}",
        "themeColor": priority_color(priority),
        "title": title,
        "sections": [
            {
                "activityTitle": "Executive Summary",
                "text": exec_summary,
                "markdown": True
            },
            {
                "facts": facts
            },
            {
                "activityTitle": "Immediate Action Required",
                "text": immediate_action,
                "markdown": True
            }
        ]
    }

    # Add link to Sentry
    sentry_link = metadata.get('link')
    if sentry_link:
        card["potentialAction"] = [
            {
                "@type": "OpenUri",
                "name": "Open in Sentry",
                "targets": [{"os": "default", "uri": sentry_link}]
            }
        ]

    return card


def send_to_teams(webhook_url: str, payload: dict[str, Any], timeout: int = 15) -> str:
    """
    POST message card to Teams webhook.

    Returns:
        Response body

    Raises:
        RuntimeError: If request fails
    """
    data = json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(webhook_url, data=data, method='POST')
    request.add_header('Content-Type', 'application/json')

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode('utf-8', errors='replace')

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f"Teams webhook HTTP {exc.code}: {detail}") from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Teams webhook: {exc}") from exc


def move_to_sent(
    recommendation_file: Path,
    sent_dir: Path
) -> Path:
    """Move recommendation file to sent directory."""
    sent_dir.mkdir(parents=True, exist_ok=True)
    destination = sent_dir / recommendation_file.name

    if destination.exists():
        # Add timestamp suffix if file already exists
        suffix = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stem = recommendation_file.stem
        destination = sent_dir / f"{stem}-{suffix}.md"

    shutil.move(str(recommendation_file), str(destination))
    return destination


def write_receipt(
    destination: Path,
    metadata: dict[str, str],
    webhook_response: str
) -> None:
    """Write send receipt JSON."""
    receipt = {
        "sentAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "issue_id": metadata.get('issue_id'),
        "priority": metadata.get('priority'),
        "project": metadata.get('project'),
        "sourceFile": str(destination),
        "webhookResponse": webhook_response[:500],
    }

    receipt_path = destination.with_suffix(destination.suffix + '.receipt.json')
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent_config.yaml', help='Config file path')
    parser.add_argument('--dry-run', action='store_true', help='Print messages without sending')
    args = parser.parse_args()

    try:
        repo_root = get_repo_root()
        config = load_agent_config('sender', args.config)

        logger.info("=== Sender Starting ===")

        # Setup paths
        output_dir = Path(config.get('output_dir', './output'))
        recommendations_dir = output_dir / 'alerts' / 'recommendations'
        sent_dir = output_dir / 'alerts' / 'sent'

        # Find recommendations
        recommendation_files = list(recommendations_dir.glob('*.md'))

        if not recommendation_files:
            logger.info("No recommendations to send")
            return 0

        logger.info(f"Found {len(recommendation_files)} recommendations")

        # Get webhook URL
        webhook_url = config.get('teams_webhook_url')
        if not webhook_url and not args.dry_run:
            logger.error("TEAMS_WEBHOOK_URL not configured")
            return 1

        timeout = int(config.get('timeout', 15))

        # Send each recommendation
        sent_count = 0
        failed_count = 0

        for idx, rec_file in enumerate(recommendation_files, 1):
            logger.info(f"[{idx}/{len(recommendation_files)}] Processing {rec_file.name}")

            # Parse recommendation
            content = rec_file.read_text(encoding='utf-8')
            metadata, body = parse_front_matter(content)

            # Check send_status
            send_status = metadata.get('send_status', 'send')
            if send_status != 'send':
                logger.info(f"  Skipping: send_status={send_status}")
                continue

            # Build Teams message
            message_card = build_teams_message_card(metadata, body)

            if args.dry_run:
                logger.info("  DRY-RUN mode:")
                print(json.dumps(message_card, indent=2))
                sent_count += 1
                continue

            # Send to Teams
            try:
                response = send_to_teams(webhook_url or '', message_card, timeout)
                logger.info(f"  Sent successfully")

                # Move to sent/ and create receipt
                destination = move_to_sent(rec_file, sent_dir)
                write_receipt(destination, metadata, response)

                sent_count += 1

            except Exception as e:
                logger.error(f"  Failed to send: {e}")
                failed_count += 1

        logger.info(f"=== Sender Complete: {sent_count} sent, {failed_count} failed ===")

        return 0 if failed_count == 0 else 1

    except Exception as e:
        logger.error(f"Sender failed: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
