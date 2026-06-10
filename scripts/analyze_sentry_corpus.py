#!/usr/bin/env python3
"""Pull a larger Sentry issue corpus and analyze rule coverage gaps."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from alert_agent.core.config_loader import load_agent_config
from alert_agent.core.sentry_client import (
    SentryClient,
    discover_org,
    fetch_issues_paginated,
    resolve_projects,
)
from triage_agent import (
    assess_danger,
    check_ignore_rules,
    classify_by_rules,
    issue_text,
    load_classification_rules,
    load_ignore_rules,
    load_priority_thresholds,
    prioritize_by_rules,
)


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [CorpusAnalysis] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


STOPWORDS = {
    "the", "and", "for", "that", "with", "from", "this", "have", "into", "when",
    "your", "their", "there", "been", "were", "http", "https", "error", "errors",
    "exception", "failed", "failure", "request", "response", "issue", "null",
    "none", "true", "false", "unknown", "java", "org", "com", "service", "api",
    "message", "value", "type", "title", "level", "count", "users", "project",
    "platform", "cannot", "could", "would", "should", "while", "after", "before",
    "during", "because", "just", "over", "under", "more", "less", "than", "only",
    "last", "first", "seen", "client", "server", "backend", "frontend",
}


def load_dotenv_if_present(path: Path) -> None:
    """Load a simple .env file into the process without overwriting existing vars."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue

        if line.startswith('export '):
            line = line[7:].strip()

        key, sep, value = line.partition('=')
        if not sep:
            continue

        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue

        if value and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]

        os.environ[key] = value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent_config.yaml', help='Config file path')
    parser.add_argument('--minutes', type=int, help='Lookback window in minutes')
    parser.add_argument('--hours', type=int, help='Lookback window in hours')
    parser.add_argument('--days', type=int, help='Lookback window in days')
    parser.add_argument('--limit', type=int, default=3000, help='Max issues to fetch across all pages')
    parser.add_argument('--page-size', type=int, default=100, help='Issues per page request (max 100)')
    parser.add_argument('--query', help='Override Sentry query')
    parser.add_argument(
        '--analysis-dir',
        help='Override analysis output base directory (default: <output_dir>/analysis)',
    )
    return parser.parse_args()


def determine_stats_period(args: argparse.Namespace, lookback_hours: int = 24) -> str:
    """Convert CLI time args into Sentry statsPeriod format."""
    if args.minutes:
        return f"{args.minutes}m"
    if args.hours:
        return f"{args.hours}h"
    if args.days:
        return f"{args.days}d"
    return f"{lookback_hours}h"


def safe_int(value: Any) -> int:
    """Convert mixed numeric values to int safely."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def compute_rule_hits(issue: dict[str, Any], class_rules: dict[str, Any]) -> dict[str, list[str]]:
    """Return keyword hits by class for one issue."""
    text = issue_text(issue)
    hits_by_class: dict[str, list[str]] = {}
    for class_name, class_data in class_rules.items():
        keywords = class_data.get('keywords', [])
        hits = [keyword for keyword in keywords if keyword in text]
        if hits:
            hits_by_class[class_name] = hits
    return hits_by_class


def extract_candidate_terms(text: str) -> list[str]:
    """Extract candidate rule keywords from issue text."""
    tokens = re.findall(r"[a-z][a-z0-9_.$-]{2,}", text.lower())
    results: list[str] = []
    for token in tokens:
        if token in STOPWORDS:
            continue
        if token.isdigit():
            continue
        if token.startswith('http') or token.startswith('trace'):
            continue
        if len(token) < 4:
            continue
        results.append(token)
    return results


def make_output_dir(base_dir: Path) -> Path:
    """Create a timestamped analysis directory."""
    timestamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output_dir = base_dir / f"sentry-corpus-{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=False)
    return output_dir


def resolve_path(path: Path) -> Path:
    """Resolve repo-relative paths consistently."""
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def top_counter_items(counter: collections.Counter[str], limit: int) -> list[dict[str, Any]]:
    """Convert a Counter to JSON-friendly top items."""
    return [{'value': value, 'count': count} for value, count in counter.most_common(limit)]


def build_summary(
    issues: list[dict[str, Any]],
    analyzed: list[dict[str, Any]],
    ignored_count: int,
) -> dict[str, Any]:
    """Build a compact JSON summary."""
    class_counts = collections.Counter(item['rule_class'] for item in analyzed)
    priority_counts = collections.Counter(item['priority'] for item in analyzed)
    project_counts = collections.Counter(item['project'] for item in analyzed)
    unknown_issues = [item for item in analyzed if item['rule_class'] == 'unknown']

    total_issue_count = sum(item['count'] for item in analyzed)
    total_user_count = sum(item['users'] for item in analyzed)

    return {
        'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'total_issues_fetched': len(issues),
        'total_issues_analyzed': len(analyzed),
        'ignored_issues_skipped': ignored_count,
        'total_event_count': total_issue_count,
        'total_user_count': total_user_count,
        'unknown_issue_count': len(unknown_issues),
        'unknown_issue_ratio': round((len(unknown_issues) / len(analyzed)), 4) if analyzed else 0,
        'class_distribution': dict(class_counts),
        'priority_distribution': dict(priority_counts),
        'top_projects': top_counter_items(project_counts, 10),
    }


def suggest_rule_improvements(
    analyzed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Derive deterministic rule improvement suggestions from analysis results."""
    suggestions: list[dict[str, Any]] = []

    unknown_issues = [item for item in analyzed if item['rule_class'] == 'unknown']
    unknown_ratio = (len(unknown_issues) / len(analyzed)) if analyzed else 0
    if unknown_ratio >= 0.1:
        suggestions.append({
            'type': 'coverage-gap',
            'severity': 'high' if unknown_ratio >= 0.2 else 'medium',
            'message': (
                f"Unknown classification rate is {unknown_ratio:.1%} across the sampled corpus. "
                "Expand rule coverage before trusting the classifier on long windows."
            ),
        })

    noisy_disconnects = [
        item for item in analyzed
        if item['rule_class'] == 'client-disconnect' and item['users'] <= 5 and item['priority'] in {'P2', 'P3'}
    ]
    if len(noisy_disconnects) >= 10:
        suggestions.append({
            'type': 'ignore-rule',
            'severity': 'medium',
            'message': (
                f"Found {len(noisy_disconnects)} low-user client-disconnect issues. "
                "Add explicit ignore rules or keep strict thresholds to avoid wasting review time."
            ),
        })

    ambiguous = [item for item in analyzed if len(item['hit_counts']) >= 2 and item['top_hit_count'] > 0]
    if ambiguous:
        suggestions.append({
            'type': 'ambiguous-keywords',
            'severity': 'medium',
            'message': (
                f"Found {len(ambiguous)} issues where multiple classes matched the same number of keywords. "
                "Tighten overlapping keywords such as HTTP status codes shared by availability and dependency."
            ),
        })

    fatal_unknown = [item for item in unknown_issues if item['level'] == 'fatal']
    if fatal_unknown:
        suggestions.append({
            'type': 'prompt',
            'severity': 'medium',
            'message': (
                f"{len(fatal_unknown)} fatal issues still landed in 'unknown'. "
                "Add prompt guidance for fatal crash patterns and project-specific context."
            ),
        })

    return suggestions


def build_markdown_report(
    summary: dict[str, Any],
    analyzed: list[dict[str, Any]],
    keyword_candidates: list[dict[str, Any]],
    top_unknown: list[dict[str, Any]],
    suggestions: list[dict[str, Any]],
) -> str:
    """Render the human-readable analysis report."""
    lines = [
        "# Sentry Corpus Analysis",
        "",
        f"Generated: {summary['generated_at']}",
        f"Issues fetched: {summary['total_issues_fetched']}",
        f"Issues analyzed: {summary['total_issues_analyzed']}",
        f"Ignored by current rules: {summary['ignored_issues_skipped']}",
        f"Unknown classification rate: {summary['unknown_issue_ratio']:.1%}",
        "",
        "## Class Distribution",
        "",
    ]

    for class_name, count in sorted(summary['class_distribution'].items(), key=lambda item: item[1], reverse=True):
        lines.append(f"- {class_name}: {count}")

    lines.extend([
        "",
        "## Priority Distribution",
        "",
    ])

    for priority, count in sorted(summary['priority_distribution'].items()):
        lines.append(f"- {priority}: {count}")

    lines.extend([
        "",
        "## Top Projects",
        "",
    ])

    for project in summary['top_projects']:
        lines.append(f"- {project['value']}: {project['count']}")

    lines.extend([
        "",
        "## Recommended Improvements",
        "",
    ])

    if suggestions:
        for suggestion in suggestions:
            lines.append(f"- [{suggestion['severity']}] {suggestion['message']}")
    else:
        lines.append("- No obvious rule gaps exceeded the current thresholds.")

    lines.extend([
        "",
        "## Top Unknown Issues",
        "",
    ])

    if top_unknown:
        for item in top_unknown:
            lines.append(
                f"- {item['issue_id']} | {item['project']} | count={item['count']} users={item['users']} | {item['title']}"
            )
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Candidate Keywords From Unknown Issues",
        "",
    ])

    if keyword_candidates:
        for candidate in keyword_candidates:
            examples = ", ".join(candidate['examples'])
            lines.append(
                f"- `{candidate['keyword']}` ({candidate['weighted_hits']}) "
                f"from {candidate['issue_count']} issues. Examples: {examples}"
            )
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Suggested Next Edits",
        "",
        "- Update `config/classification_rules.yaml` with the strongest repeated unknown patterns.",
        "- Update `prompts/triage_reclassify.md` with project-specific examples from the top unknown issues.",
        "- Re-run this script after rule changes and compare the unknown classification rate.",
    ])

    return "\n".join(lines) + "\n"


def main() -> int:
    """Main entry point."""
    args = parse_args()
    load_dotenv_if_present(REPO_ROOT / '.env')

    triage_config = load_agent_config('triage_agent', args.config)
    sentry_config = load_agent_config('sentry', args.config)
    common_config = load_agent_config('common', args.config)

    output_dir = resolve_path(Path(common_config.get('output_dir', './output')))
    analysis_base = resolve_path(Path(args.analysis_dir)) if args.analysis_dir else output_dir / 'analysis'
    analysis_dir = make_output_dir(analysis_base)

    logger.info("Writing analysis to %s", analysis_dir)

    class_rules = load_classification_rules(REPO_ROOT / triage_config['classification_rules'])
    priority_thresholds = load_priority_thresholds(REPO_ROOT / triage_config['priority_thresholds'])
    ignore_rules = load_ignore_rules(REPO_ROOT / triage_config['ignore_rules'])
    confidence_config = priority_thresholds.get('confidence', {})

    sentry_client = SentryClient(sentry_config['base_url'], sentry_config['auth_token'])
    org = sentry_config.get('organization') or discover_org(sentry_client)
    stats_period = determine_stats_period(args, lookback_hours=24 * 14)

    project_specs = None
    if sentry_config.get('projects'):
        project_names = [value.strip() for value in sentry_config['projects'].split(',') if value.strip()]
        if project_names:
            project_specs = resolve_projects(sentry_client, org, project_names)

    issues = fetch_issues_paginated(
        sentry_client,
        org=org,
        stats_period=stats_period,
        query=args.query or sentry_config.get('query', 'is:unresolved'),
        projects=project_specs,
        environment=sentry_config.get('environment'),
        limit=args.limit,
        page_size=args.page_size,
    )

    logger.info("Fetched %s issues", len(issues))

    analyzed: list[dict[str, Any]] = []
    ignored_count = 0
    unknown_term_weights: collections.Counter[str] = collections.Counter()
    unknown_term_examples: dict[str, set[str]] = collections.defaultdict(set)

    for issue in issues:
        should_ignore, ignore_reason = check_ignore_rules(issue, ignore_rules)
        if should_ignore:
            ignored_count += 1
            continue

        rule_class, rule_confidence, rule_reasoning = classify_by_rules(issue, class_rules, confidence_config)
        priority = prioritize_by_rules(issue, rule_class, priority_thresholds)
        count = safe_int(issue.get('count'))
        users = safe_int(issue.get('userCount') or issue.get('users'))
        hits_by_class = compute_rule_hits(issue, class_rules)
        hit_counts = {class_name: len(hits) for class_name, hits in hits_by_class.items()}
        top_hit_count = max(hit_counts.values()) if hit_counts else 0

        item = {
            'issue_id': issue.get('shortId', '') or str(issue.get('id', '')),
            'sentry_id': str(issue.get('id', '')),
            'title': issue.get('title', ''),
            'project': issue.get('project', {}).get('slug', ''),
            'count': count,
            'users': users,
            'level': str(issue.get('level', '')).lower(),
            'rule_class': rule_class,
            'priority': priority,
            'danger': assess_danger(rule_class, priority, count, users),
            'confidence': rule_confidence,
            'reasoning': rule_reasoning,
            'link': issue.get('permalink', ''),
            'ignore_reason': ignore_reason,
            'hit_counts': hit_counts,
            'top_hit_count': top_hit_count,
        }
        analyzed.append(item)

        if rule_class == 'unknown':
            text = issue_text(issue)
            weight = max(1, min(count, 500))
            for token in extract_candidate_terms(text):
                unknown_term_weights[token] += weight
                if len(unknown_term_examples[token]) < 3:
                    unknown_term_examples[token].add(item['issue_id'])

    summary = build_summary(issues, analyzed, ignored_count)
    suggestions = suggest_rule_improvements(analyzed)

    keyword_candidates = []
    for keyword, weighted_hits in unknown_term_weights.most_common(20):
        keyword_candidates.append({
            'keyword': keyword,
            'weighted_hits': weighted_hits,
            'issue_count': len(unknown_term_examples[keyword]),
            'examples': sorted(unknown_term_examples[keyword]),
        })

    top_unknown = sorted(
        [item for item in analyzed if item['rule_class'] == 'unknown'],
        key=lambda item: (item['count'], item['users']),
        reverse=True,
    )[:20]

    report = build_markdown_report(summary, analyzed, keyword_candidates, top_unknown, suggestions)

    (analysis_dir / 'raw_issues.json').write_text(json.dumps(issues, indent=2), encoding='utf-8')
    (analysis_dir / 'rule_analysis.json').write_text(json.dumps(analyzed, indent=2), encoding='utf-8')
    (analysis_dir / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    (analysis_dir / 'keyword_candidates.json').write_text(json.dumps(keyword_candidates, indent=2), encoding='utf-8')
    (analysis_dir / 'analysis_report.md').write_text(report, encoding='utf-8')

    logger.info("Analysis complete")
    logger.info("Summary: %s analyzed, %s unknown, %s ignored", summary['total_issues_analyzed'], summary['unknown_issue_count'], ignored_count)
    logger.info("Report: %s", analysis_dir / 'analysis_report.md')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
