#!/usr/bin/env python3
"""
Triage Agent: Hybrid rule-based + AI classification of Sentry issues.

This agent:
1. Fetches recent Sentry issues
2. Applies rule-based classification (keyword matching)
3. Uses AI to reclassify uncertain cases (confidence < threshold)
4. Applies ignore rules
5. Outputs triage results to JSON files
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Any

import yaml

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from shared.ai_client import PiAIClient, format_prompt, load_prompt_template
from shared.config_loader import get_repo_root, load_agent_config
from shared.sentry_client import SentryClient, discover_org, fetch_issues, resolve_projects


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [TriageAgent] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def load_classification_rules(config_path: Path) -> dict[str, Any]:
    """Load keyword classification rules from YAML."""
    with config_path.open('r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data.get('classes', {})


def load_priority_thresholds(config_path: Path) -> dict[str, Any]:
    """Load priority threshold rules from YAML."""
    with config_path.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_ignore_rules(config_path: Path) -> list[dict[str, Any]]:
    """Load ignore rules from JSON."""
    if not config_path.exists():
        return []

    with config_path.open('r', encoding='utf-8') as f:
        data = json.load(f)

    rules = data.get('rules', [])
    # Filter to only enabled rules
    return [r for r in rules if r.get('enabled', True)]


def issue_text(issue: dict[str, Any]) -> str:
    """Extract searchable text from issue for keyword matching."""
    project = issue.get('project', {})
    metadata = issue.get('metadata', {})

    fields = [
        issue.get('title'),
        issue.get('culprit'),
        issue.get('level'),
        project.get('platform'),
        project.get('slug'),
        metadata.get('type'),
        metadata.get('value'),
    ]

    return ' '.join(str(v).lower() for v in fields if v)


def classify_by_rules(
    issue: dict[str, Any],
    class_rules: dict[str, Any],
    confidence_config: dict[str, float]
) -> tuple[str, float, str]:
    """
    Classify issue using keyword rules.

    Returns:
        (class_name, confidence, reasoning)
    """
    text = issue_text(issue)

    # Special case: client-disconnect has highest priority to avoid false positives
    for keyword in class_rules.get('client-disconnect', {}).get('keywords', []):
        if keyword in text:
            return 'client-disconnect', confidence_config.get('exact_keyword_match', 0.9), f"matched '{keyword}'"

    # Check frontend-client next if javascript/browser present
    if 'javascript' in text or 'browser' in text:
        for keyword in class_rules.get('frontend-client', {}).get('keywords', []):
            if keyword in text:
                return 'frontend-client', confidence_config.get('exact_keyword_match', 0.9), f"matched '{keyword}'"

    # Check all other classes
    best_class = 'unknown'
    best_confidence = confidence_config.get('no_match', 0.3)
    best_hits: list[str] = []

    for class_name, class_data in class_rules.items():
        if class_name in ('client-disconnect', 'frontend-client'):
            continue  # Already checked

        keywords = class_data.get('keywords', [])
        hits = [kw for kw in keywords if kw in text]

        if len(hits) > len(best_hits):
            best_class = class_name
            best_hits = hits

    if best_hits:
        if len(best_hits) >= 3:
            best_confidence = confidence_config.get('multiple_keywords', 0.85)
        elif len(best_hits) >= 2:
            best_confidence = confidence_config.get('single_keyword', 0.7)
        else:
            best_confidence = confidence_config.get('single_keyword', 0.7)

        reasoning = 'matched ' + ', '.join(f"'{h}'" for h in best_hits[:3])
        return best_class, best_confidence, reasoning

    # No keywords matched
    if issue.get('level') == 'fatal':
        return 'availability', 0.6, 'fatal issue level'

    return 'unknown', best_confidence, 'no keyword match'


def prioritize_by_rules(
    issue: dict[str, Any],
    issue_class: str,
    thresholds: dict[str, Any]
) -> str:
    """Assign priority based on count/user thresholds."""
    count = int(issue.get('count', 0) or 0)
    users = int(issue.get('userCount', 0) or issue.get('users', 0) or 0)
    level = str(issue.get('level', '')).lower()

    class_thresholds = thresholds.get('class_thresholds', {}).get(issue_class, {})

    # Check P0 threshold
    p0_threshold = class_thresholds.get('P0', {})
    if count >= p0_threshold.get('count', 999999) or users >= p0_threshold.get('users', 999999):
        return 'P0'

    # Check P1 threshold
    p1_threshold = class_thresholds.get('P1', {})
    if count >= p1_threshold.get('count', 999999) or users >= p1_threshold.get('users', 999999):
        priority = 'P1'
    elif count >= 50 or users >= 5:
        priority = 'P2'
    else:
        priority = 'P3'

    # Bump priority for fatal level
    if level == 'fatal' and thresholds.get('fatal_bump', False):
        if priority == 'P3':
            priority = 'P2'
        elif priority == 'P2':
            priority = 'P1'
        elif priority == 'P1' and issue_class in ('availability', 'dependency', 'performance-timeout'):
            priority = 'P0'

    return priority


def assess_danger(issue_class: str, priority: str, count: int, users: int) -> str:
    """Assess danger level based on class and metrics."""
    if priority == 'P0':
        return 'critical'

    if issue_class in ('dependency', 'performance-timeout') and count >= 100:
        return 'high'

    if issue_class == 'client-disconnect':
        return 'low'

    if issue_class in ('auth-permission', 'data-integrity'):
        return 'medium'

    if users >= 5 or count >= 50:
        return 'medium'

    return 'low'


def reclassify_with_ai(
    issue: dict[str, Any],
    rule_result: dict[str, Any],
    ai_client: PiAIClient,
    repo_root: Path
) -> dict[str, Any]:
    """Use AI to reclassify uncertain issues."""
    try:
        # Load prompt template
        template = load_prompt_template('triage_reclassify.md', repo_root)

        # Format prompt with issue data
        project = issue.get('project', {})
        metadata = issue.get('metadata', {})

        prompt = format_prompt(
            template,
            title=issue.get('title', 'Untitled'),
            project=project.get('slug', 'unknown'),
            platform=project.get('platform', 'unknown'),
            count=issue.get('count', 0),
            users=issue.get('userCount', 0) or issue.get('users', 0),
            level=issue.get('level', 'unknown'),
            first_seen=issue.get('firstSeen', ''),
            last_seen=issue.get('lastSeen', ''),
            culprit=issue.get('culprit', ''),
            metadata_type=metadata.get('type', ''),
            metadata_value=metadata.get('value', ''),
            rule_class=rule_result['class'],
            rule_priority=rule_result['priority'],
            rule_confidence=rule_result['confidence'],
            rule_reasoning=rule_result['reasoning']
        )

        # Query AI
        response = ai_client.query_json(prompt)

        return {
            'class': response.get('class', rule_result['class']),
            'priority': response.get('priority', rule_result['priority']),
            'danger': response.get('danger', rule_result['danger']),
            'confidence': float(response.get('confidence', 0.5)),
            'reasoning': response.get('reasoning', 'AI classification'),
            'source': 'ai_enhanced'
        }

    except Exception as e:
        logger.warning(f"AI reclassification failed for {issue.get('shortId')}: {e}")
        # Fall back to rule-based result
        return {**rule_result, 'source': 'rule_based_fallback', 'ai_error': str(e)}


def check_ignore_rules(issue: dict[str, Any], rules: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """
    Check if issue matches any ignore rules.

    Returns:
        (should_ignore, reason)
    """
    now = dt.datetime.now(dt.timezone.utc)

    short_id = issue.get('shortId', '')
    issue_id = str(issue.get('id', ''))
    title = str(issue.get('title', '')).lower()
    project = issue.get('project', {}).get('slug', '').lower()
    count = int(issue.get('count', 0))

    for rule in rules:
        # Check expiry
        expires = rule.get('expires')
        if expires:
            try:
                expire_date = dt.datetime.fromisoformat(expires.replace('Z', '+00:00'))
                if expire_date < now:
                    continue  # Rule expired
            except ValueError:
                pass

        # Check issue_id match
        if rule.get('issue_id'):
            if rule['issue_id'] in (short_id, issue_id):
                return True, rule.get('reason', 'matched ignore rule')

        # Check class + count
        if rule.get('class'):
            # Need to get class from somewhere - skip for now in ignore check
            pass

        # Check title_contains
        if rule.get('title_contains'):
            if rule['title_contains'].lower() in title:
                return True, rule.get('reason', 'matched title pattern')

        # Check project
        if rule.get('project'):
            if rule['project'].lower() == project:
                # Also check count threshold if present
                max_count = rule.get('max_count')
                if max_count is None or count <= max_count:
                    return True, rule.get('reason', 'matched project rule')

    return False, None


def triage_issue(
    issue: dict[str, Any],
    class_rules: dict[str, Any],
    priority_thresholds: dict[str, Any],
    confidence_threshold: float,
    ai_client: PiAIClient | None,
    repo_root: Path
) -> dict[str, Any]:
    """
    Triage a single issue (rule-based + optional AI).

    Returns:
        Triage result dict
    """
    project = issue.get('project', {})
    metadata = issue.get('metadata', {})

    # Step 1: Rule-based classification
    rule_class, rule_confidence, rule_reasoning = classify_by_rules(
        issue, class_rules, priority_thresholds.get('confidence', {})
    )

    count = int(issue.get('count', 0))
    users = int(issue.get('userCount', 0) or issue.get('users', 0))

    rule_priority = prioritize_by_rules(issue, rule_class, priority_thresholds)
    rule_danger = assess_danger(rule_class, rule_priority, count, users)

    rule_result = {
        'class': rule_class,
        'priority': rule_priority,
        'danger': rule_danger,
        'confidence': rule_confidence,
        'reasoning': rule_reasoning,
        'source': 'rule_based'
    }

    # Step 2: AI reclassification if confidence too low
    if ai_client and rule_confidence < confidence_threshold:
        logger.info(f"  AI reclassifying {issue.get('shortId')} (rule confidence {rule_confidence:.2f} < {confidence_threshold})")
        ai_result = reclassify_with_ai(issue, rule_result, ai_client, repo_root)
        final_result = ai_result
    else:
        final_result = rule_result

    # Build output
    return {
        'issue_id': issue.get('shortId', '') or str(issue.get('id', '')),
        'sentry_id': str(issue.get('id', '')),
        'rule_classification': rule_result,
        'ai_classification': final_result if final_result.get('source') == 'ai_enhanced' else None,
        'final': final_result,
        'metadata': {
            'title': issue.get('title', ''),
            'project': project.get('slug', ''),
            'platform': project.get('platform', ''),
            'count': count,
            'users': users,
            'level': issue.get('level', ''),
            'first_seen': issue.get('firstSeen', ''),
            'last_seen': issue.get('lastSeen', ''),
            'culprit': issue.get('culprit', ''),
            'link': issue.get('permalink', ''),
            'metadata_type': metadata.get('type', ''),
            'metadata_value': metadata.get('value', '')
        },
        'ignored': False,
        'ignore_reason': None,
        'timestamp': dt.datetime.now(dt.timezone.utc).isoformat()
    }


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent_config.yaml', help='Config file path')
    parser.add_argument('--hours', type=int, help='Lookback window in hours (e.g., 1, 24, 168)')
    parser.add_argument('--minutes', type=int, help='Lookback window in minutes (e.g., 21, 30, 90)')
    parser.add_argument('--dry-run', action='store_true', help='Test mode, no AI calls')
    args = parser.parse_args()

    try:
        repo_root = get_repo_root()
        config = load_agent_config('triage_agent', args.config)

        logger.info("=== Triage Agent Starting ===")

        # Load Sentry config
        sentry_config = load_agent_config('sentry', args.config)
        output_dir = Path(config.get('output_dir', './output'))

        # Create output directories
        triage_dir = output_dir / 'alerts' / 'triage'
        triage_dir.mkdir(parents=True, exist_ok=True)

        # Initialize Sentry client
        sentry_client = SentryClient(
            sentry_config['base_url'],
            sentry_config['auth_token']
        )

        org = sentry_config.get('organization') or discover_org(sentry_client)

        # Determine lookback period
        if args.minutes:
            stats_period = f"{args.minutes}m"
        elif args.hours:
            stats_period = f"{args.hours}h"
        else:
            # Use config default
            lookback_hours = config.get('lookback_hours', 1)
            stats_period = f"{lookback_hours}h"

        logger.info(f"Fetching Sentry issues (org={org}, period={stats_period})")

        # Resolve project names to IDs
        project_specs = None
        if sentry_config.get('projects'):
            project_names = [p.strip() for p in sentry_config['projects'].split(',') if p.strip()]
            if project_names:
                logger.info(f"Resolving project names: {', '.join(project_names)}")
                project_specs = resolve_projects(sentry_client, org, project_names)
                logger.info(f"Resolved to project IDs: {', '.join(project_specs)}")

        # Fetch issues
        issues = fetch_issues(
            sentry_client,
            org=org,
            stats_period=stats_period,
            query=sentry_config.get('query', 'is:unresolved'),
            projects=project_specs,
            environment=sentry_config.get('environment'),
            limit=int(sentry_config.get('limit', 100))
        )

        logger.info(f"Fetched {len(issues)} issues")

        if not issues:
            logger.info("No issues to triage")
            return 0

        # Load classification rules
        class_rules = load_classification_rules(repo_root / config['classification_rules'])
        priority_thresholds = load_priority_thresholds(repo_root / config['priority_thresholds'])
        ignore_rules = load_ignore_rules(repo_root / config['ignore_rules'])

        logger.info(f"Loaded {len(ignore_rules)} ignore rules")

        # Initialize AI client if enabled
        ai_client = None
        if config.get('ai', {}).get('enabled', False) and not args.dry_run:
            ai_config = config['ai']
            ai_client = PiAIClient(
                provider=ai_config['provider'],
                model=ai_config.get('model'),
                api_key=ai_config.get('api_key')
            )
            logger.info(f"AI client initialized (provider={ai_config['provider']})")
        else:
            logger.info("AI reclassification disabled (dry-run or config)")

        # Triage each issue
        triage_results = []
        critical_count = 0

        for idx, issue in enumerate(issues, 1):
            short_id = issue.get('shortId', '') or str(issue.get('id', ''))
            logger.info(f"[{idx}/{len(issues)}] Triaging {short_id}")

            # Check ignore rules first
            should_ignore, ignore_reason = check_ignore_rules(issue, ignore_rules)

            if should_ignore:
                logger.info(f"  Ignored: {ignore_reason}")
                continue  # Skip ignored issues

            # Triage
            result = triage_issue(
                issue,
                class_rules,
                priority_thresholds,
                config.get('rule_confidence_threshold', 0.7),
                ai_client,
                repo_root
            )

            result['ignored'] = should_ignore
            result['ignore_reason'] = ignore_reason

            # Save to file
            output_file = triage_dir / f"{result['issue_id']}.json"
            with output_file.open('w', encoding='utf-8') as f:
                json.dump(result, f, indent=2)

            triage_results.append(result)

            # Count critical issues
            if result['final']['priority'] in ('P0', 'P1'):
                critical_count += 1

            logger.info(f"  Final: {result['final']['priority']} / {result['final']['class']} "
                       f"(confidence: {result['final']['confidence']:.2f})")

        logger.info(f"=== Triage Complete: {len(triage_results)} issues, {critical_count} critical (P0/P1) ===")

        # Return exit code 2 if critical issues found (signals to trigger next agents)
        return 2 if critical_count > 0 else 0

    except Exception as e:
        logger.error(f"Triage agent failed: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
