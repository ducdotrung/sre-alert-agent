#!/usr/bin/env python3
"""Shared triage stage driven by a source plugin."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any

import yaml

from alert_agent.core.ai_client import PiAIClient, format_prompt
from alert_agent.core.config_loader import (
    get_repo_root,
    load_pipeline_stage_config,
    load_source_config,
)
from alert_agent.core.models import AlertRecord
from alert_agent.core.plugin import PipelineContext, PolicyPack
from alert_agent.core.registry import get_source_plugin


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [TriageAgent] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def load_classification_rules(config_path: Path) -> dict[str, Any]:
    with config_path.open('r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data.get('classes', {})


def load_priority_thresholds(config_path: Path) -> dict[str, Any]:
    with config_path.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_ignore_rules(config_path: Path) -> list[dict[str, Any]]:
    if not config_path.exists():
        return []
    with config_path.open('r', encoding='utf-8') as f:
        data = json.load(f)
    return [r for r in data.get('rules', []) if r.get('enabled', True)]


def alert_text(alert: AlertRecord) -> str:
    fields = [
        alert.title,
        alert.summary,
        alert.culprit,
        alert.severity,
        alert.platform,
        alert.project,
        alert.service,
        alert.source,
    ]
    fields.extend(str(v) for v in alert.labels.values())
    return ' '.join(str(v).lower() for v in fields if v)


def classify_by_rules(
    alert: AlertRecord,
    class_rules: dict[str, Any],
    confidence_config: dict[str, float]
) -> tuple[str, float, str]:
    text = alert_text(alert)

    for keyword in class_rules.get('client-disconnect', {}).get('keywords', []):
        if keyword in text:
            return 'client-disconnect', confidence_config.get('exact_keyword_match', 0.9), f"matched '{keyword}'"

    if 'javascript' in text or 'browser' in text:
        for keyword in class_rules.get('frontend-client', {}).get('keywords', []):
            if keyword in text:
                return 'frontend-client', confidence_config.get('exact_keyword_match', 0.9), f"matched '{keyword}'"

    best_class = 'unknown'
    best_confidence = confidence_config.get('no_match', 0.3)
    best_hits: list[str] = []

    for class_name, class_data in class_rules.items():
        if class_name in ('client-disconnect', 'frontend-client'):
            continue
        hits = [kw for kw in class_data.get('keywords', []) if kw in text]
        if len(hits) > len(best_hits):
            best_class = class_name
            best_hits = hits

    if best_hits:
        if len(best_hits) >= 3:
            best_confidence = confidence_config.get('multiple_keywords', 0.85)
        else:
            best_confidence = confidence_config.get('single_keyword', 0.7)
        return best_class, best_confidence, 'matched ' + ', '.join(f"'{h}'" for h in best_hits[:3])

    if str(alert.severity).lower() == 'fatal':
        return 'availability', 0.6, 'fatal issue level'

    return 'unknown', best_confidence, 'no keyword match'


def prioritize_by_rules(alert: AlertRecord, issue_class: str, thresholds: dict[str, Any]) -> str:
    count = int(alert.count or 0)
    users = int(alert.affected_users or 0)
    level = str(alert.severity or '').lower()

    class_thresholds = thresholds.get('class_thresholds', {}).get(issue_class, {})
    p0_threshold = class_thresholds.get('P0', {})
    if count >= p0_threshold.get('count', 999999) or users >= p0_threshold.get('users', 999999):
        return 'P0'

    p1_threshold = class_thresholds.get('P1', {})
    if count >= p1_threshold.get('count', 999999) or users >= p1_threshold.get('users', 999999):
        priority = 'P1'
    elif count >= 50 or users >= 5:
        priority = 'P2'
    else:
        priority = 'P3'

    if level == 'fatal' and thresholds.get('fatal_bump', False):
        if priority == 'P3':
            priority = 'P2'
        elif priority == 'P2':
            priority = 'P1'
        elif priority == 'P1' and issue_class in ('availability', 'dependency', 'performance-timeout'):
            priority = 'P0'

    return priority


def assess_danger(issue_class: str, priority: str, count: int, users: int) -> str:
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
    alert: AlertRecord,
    rule_result: dict[str, Any],
    ai_client: PiAIClient,
    prompt_path: Path,
) -> dict[str, Any]:
    try:
        template = prompt_path.read_text(encoding='utf-8')
        prompt = format_prompt(
            template,
            source=alert.source or 'unknown',
            source_type=alert.source_type or 'unknown',
            title=alert.title,
            summary=alert.summary or '',
            project=alert.project or 'unknown',
            service=alert.service or '',
            environment=alert.environment or '',
            platform=alert.platform or 'unknown',
            count=alert.count,
            users=alert.affected_users,
            level=alert.severity or 'unknown',
            first_seen=alert.first_seen,
            last_seen=alert.last_seen,
            culprit=alert.culprit,
            metadata_type=alert.labels.get('metadata_type', ''),
            metadata_value=alert.labels.get('metadata_value', ''),
            rule_class=rule_result['class'],
            rule_priority=rule_result['priority'],
            rule_confidence=rule_result['confidence'],
            rule_reasoning=rule_result['reasoning'],
        )
        response = ai_client.query_json(
            prompt,
            metadata={
                'issue_id': alert.source_alert_id,
                'operation': 'triage_reclassify',
                'project': alert.project or 'unknown',
                'source': alert.source,
            }
        )
        return {
            'class': response.get('class', rule_result['class']),
            'priority': response.get('priority', rule_result['priority']),
            'danger': response.get('danger', rule_result['danger']),
            'confidence': float(response.get('confidence', 0.5)),
            'reasoning': response.get('reasoning', 'AI classification'),
            'source': 'ai_enhanced',
        }
    except Exception as exc:
        logger.warning("AI reclassification failed for %s: %s", alert.source_alert_id, exc)
        return {**rule_result, 'source': 'rule_based_fallback', 'ai_error': str(exc)}


def check_ignore_rules(
    alert: AlertRecord,
    rules: list[dict[str, Any]],
    issue_class: str | None = None,
) -> tuple[bool, str | None]:
    now = dt.datetime.now(dt.timezone.utc)
    title = str(alert.title or '').lower()
    project = str(alert.project or '').lower()
    count = int(alert.count or 0)

    for rule in rules:
        rule_source = str(rule.get('source') or '').strip().lower()
        if rule_source and rule_source != str(alert.source).lower():
            continue

        expires = rule.get('expires')
        if expires:
            try:
                expire_date = dt.datetime.fromisoformat(str(expires).replace('Z', '+00:00'))
                if expire_date.tzinfo is None:
                    expire_date = expire_date.replace(tzinfo=dt.timezone.utc)
                if expire_date < now:
                    continue
            except ValueError:
                pass

        if rule.get('issue_id') and rule['issue_id'] in (alert.source_alert_id, alert.raw_ref.get('external_id', '')):
            return True, rule.get('reason', 'matched ignore rule')

        if rule.get('class'):
            if issue_class is None or rule['class'].lower() != issue_class.lower():
                continue
            max_count = rule.get('max_count')
            if max_count is None or count <= max_count:
                if not rule.get('title_contains') and not rule.get('project') and not rule.get('issue_id'):
                    return True, rule.get('reason', 'matched class rule')

        if rule.get('title_contains') and str(rule['title_contains']).lower() in title:
            max_count = rule.get('max_count')
            if max_count is None or count <= max_count:
                return True, rule.get('reason', 'matched title pattern')
            continue

        if rule.get('project') and str(rule['project']).lower() == project:
            max_count = rule.get('max_count')
            if max_count is None or count <= max_count:
                return True, rule.get('reason', 'matched project rule')

    return False, None


def triage_alert(
    alert: AlertRecord,
    policy_pack: PolicyPack,
    class_rules: dict[str, Any],
    priority_thresholds: dict[str, Any],
    confidence_threshold: float,
    ai_client: PiAIClient | None,
) -> dict[str, Any]:
    rule_class, rule_confidence, rule_reasoning = classify_by_rules(
        alert, class_rules, priority_thresholds.get('confidence', {})
    )

    rule_priority = prioritize_by_rules(alert, rule_class, priority_thresholds)
    rule_danger = assess_danger(rule_class, rule_priority, int(alert.count), int(alert.affected_users))
    rule_result = {
        'class': rule_class,
        'priority': rule_priority,
        'danger': rule_danger,
        'confidence': rule_confidence,
        'reasoning': rule_reasoning,
        'source': 'rule_based',
    }

    final_result = rule_result
    triage_prompt = policy_pack.prompts.get('triage')
    if ai_client and triage_prompt and rule_confidence < confidence_threshold:
        logger.info(
            "  AI reclassifying %s (rule confidence %.2f < %.2f)",
            alert.source_alert_id,
            rule_confidence,
            confidence_threshold,
        )
        final_result = reclassify_with_ai(alert, rule_result, ai_client, triage_prompt)

    return {
        'issue_id': alert.source_alert_id,
        'alert_id': alert.alert_id,
        'source': alert.source,
        'source_type': alert.source_type,
        'source_alert_id': alert.source_alert_id,
        'policy_pack': policy_pack.name,
        'sentry_id': alert.raw_ref.get('external_id', ''),
        'alert': alert.to_dict(),
        'rule_classification': rule_result,
        'ai_classification': final_result if final_result.get('source') == 'ai_enhanced' else None,
        'final': final_result,
        'metadata': {
            'title': alert.title,
            'summary': alert.summary,
            'project': alert.project,
            'service': alert.service,
            'environment': alert.environment,
            'platform': alert.platform,
            'count': alert.count,
            'users': alert.affected_users,
            'level': alert.severity,
            'first_seen': alert.first_seen,
            'last_seen': alert.last_seen,
            'culprit': alert.culprit,
            'link': alert.link,
            'metadata_type': alert.labels.get('metadata_type', ''),
            'metadata_value': alert.labels.get('metadata_value', ''),
        },
        'ignored': False,
        'ignore_reason': None,
        'timestamp': dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def determine_stats_period(config: dict[str, Any], hours: int | None, minutes: int | None) -> str:
    if minutes:
        return f"{minutes}m"
    if hours:
        return f"{hours}h"
    return f"{config.get('lookback_hours', 1)}h"


def build_context(config_file: str, source_name: str) -> tuple[PipelineContext, PolicyPack]:
    repo_root = get_repo_root()
    stage_config = load_pipeline_stage_config('triage', config_file)
    source_config = load_source_config(source_name, config_file)
    output_dir = Path(stage_config.get('output_dir', './output'))
    metrics_dir = Path(stage_config.get('metrics_dir', './output/metrics'))
    context = PipelineContext(
        config_file=config_file,
        repo_root=repo_root,
        output_dir=output_dir,
        metrics_dir=metrics_dir,
        run_id=stage_config.get('run_id'),
        stage_config=stage_config,
        source_config=source_config,
    )
    plugin = get_source_plugin(source_name)
    return context, plugin.load_policy_pack(context)


def run(
    *,
    config_file: str,
    source_name: str = 'sentry',
    hours: int | None = None,
    minutes: int | None = None,
    dry_run: bool = False,
) -> int:
    context, policy_pack = build_context(config_file, source_name)
    plugin = get_source_plugin(source_name)
    config = context.stage_config

    logger.info("=== Triage Agent Starting ===")
    triage_dir = context.output_dir / 'alerts' / 'triage'
    triage_dir.mkdir(parents=True, exist_ok=True)

    stats_period = determine_stats_period(config, hours, minutes)
    logger.info("Fetching %s alerts (period=%s)", source_name, stats_period)
    raw_alerts = plugin.fetch_alerts(context, stats_period=stats_period)
    logger.info("Fetched %d alerts", len(raw_alerts))
    if not raw_alerts:
        logger.info("No alerts to triage")
        return 0

    class_rules = load_classification_rules(policy_pack.classification_rules)
    priority_thresholds = load_priority_thresholds(policy_pack.priority_thresholds)
    ignore_rules = load_ignore_rules(policy_pack.ignore_rules)

    ai_client = None
    if config.get('ai', {}).get('enabled', False) and not dry_run:
        ai_config = config['ai']
        ai_client = PiAIClient(
            provider=ai_config['provider'],
            model=ai_config.get('model'),
            api_key=ai_config.get('api_key'),
            metrics_dir=config.get('metrics_dir'),
            agent_name='triage_agent',
            run_id=config.get('run_id'),
            pricing=config.get('ai_pricing'),
        )
        logger.info("AI client initialized (provider=%s)", ai_config['provider'])
    else:
        logger.info("AI reclassification disabled (dry-run or config)")

    triage_results: list[dict[str, Any]] = []
    critical_count = 0
    threshold = float(config.get('rule_confidence_threshold', 0.7))

    for idx, raw_alert in enumerate(raw_alerts, 1):
        alert = plugin.normalize_alert(raw_alert, context)
        logger.info("[%d/%d] Triaging %s", idx, len(raw_alerts), alert.source_alert_id)

        pre_rule_class, _, _ = classify_by_rules(alert, class_rules, priority_thresholds.get('confidence', {}))
        should_ignore, ignore_reason = check_ignore_rules(alert, ignore_rules, issue_class=pre_rule_class)
        if should_ignore:
            logger.info("  Ignored: %s", ignore_reason)
            continue

        result = triage_alert(
            alert,
            policy_pack,
            class_rules,
            priority_thresholds,
            threshold,
            ai_client,
        )
        triage_results.append(result)
        if result['final']['priority'] in ('P0', 'P1'):
            critical_count += 1

        output_file = triage_dir / f"{result['issue_id']}.json"
        output_file.write_text(json.dumps(result, indent=2), encoding='utf-8')

    logger.info("=== Triage Complete: %d alerts written, %d critical ===", len(triage_results), critical_count)
    return 2 if critical_count > 0 else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/agent_config.yaml', help='Config file path')
    parser.add_argument('--source', default='sentry', help='Source plugin name')
    parser.add_argument('--hours', type=int, help='Lookback window in hours')
    parser.add_argument('--minutes', type=int, help='Lookback window in minutes')
    parser.add_argument('--dry-run', action='store_true', help='Test mode, no AI calls')
    args = parser.parse_args()
    try:
        return run(
            config_file=args.config,
            source_name=args.source,
            hours=args.hours,
            minutes=args.minutes,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        logger.error("Triage agent failed: %s", exc, exc_info=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
