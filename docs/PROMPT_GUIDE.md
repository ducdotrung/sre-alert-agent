# Prompt Guide

This repo treats AI prompts as source/team policy, not as Python business logic.

The shared pipeline can process many alert sources. Each source should normalize raw alerts into the canonical alert model, then select a policy pack with its own rules, thresholds, ignore rules, and optionally its own prompt files.

## Current Prompt Stages

The current AI-backed stages are:

| Stage | Default prompt | Output consumed by |
| --- | --- | --- |
| Triage reclassification | `prompts/triage_reclassify.md` | `alert_agent.pipeline.triage` JSON parser |
| Review decision | `prompts/review_decision.md` | `alert_agent.pipeline.review` JSON parser and auto-approval gate |
| Recommendation generation | `prompts/recommendation_generate.md` | `alert_agent.pipeline.recommendation` and Teams sender |
| Self-improvement summary | `prompts/self_improve_summarize.md` | proposal files under `output/improvement/proposals/` |

## Policy-Pack Model

A source can use the default prompts or define source-specific prompts in `config/agent_config.yaml`:

```yaml
policy_packs:
  sentry-default:
    classification_rules: config/classification_rules.yaml
    priority_thresholds: config/priority_thresholds.yaml
    ignore_rules: config/ignore_rules.json
    prompts:
      triage: prompts/triage_reclassify.md
      review: prompts/review_decision.md
      recommendation: prompts/recommendation_generate.md

  grafana-default:
    classification_rules: config/grafana/classification_rules.yaml
    priority_thresholds: config/grafana/priority_thresholds.yaml
    ignore_rules: config/grafana/ignore_rules.json
    prompts:
      triage: prompts/grafana/triage_reclassify.md
      review: prompts/grafana/review_decision.md
      recommendation: prompts/grafana/recommendation_generate.md
```

Use source-specific prompt files when the source has different concepts, for example Grafana alert labels, Prometheus expressions, runbook URLs, or service ownership metadata.

## Prompt Design Principles

1. **Keep prompts evidence-based**
   - The model should only use facts passed in the prompt.
   - Ask it to output `unknown` or `null` when data is missing.
   - Do not ask for trend, revenue loss, deploy correlation, SLA breach, or root cause unless the prompt input actually contains that evidence.

2. **Make output contracts strict**
   - Triage and review must return valid JSON only.
   - Recommendation must return markdown with exact headings because the sender extracts sections by heading.
   - Self-improvement summaries should be short plain text.

3. **Separate shared behavior from source-specific hints**
   - Shared prompt: class definitions, priority meanings, confidence calibration, safety rules.
   - Source-specific prompt: examples and terms for one source, such as Sentry stack traces or Grafana firing/resolved alerts.

4. **Prefer conservative automation**
   - If the model is unsure, choose `review` rather than `send`.
   - If root cause is unclear, say so.
   - If a command could mutate production, make it conditional and require verification first.

5. **Treat prompts like config**
   - Review prompt diffs like rules/threshold changes.
   - Validate with representative alert samples before production rollout.
   - Record important prompt changes in `repo-memory/`.

## Triage Prompt Contract

Current variables:

- `{source}`, `{source_type}`
- `{title}`, `{summary}`
- `{project}`, `{service}`, `{environment}`, `{platform}`
- `{count}`, `{users}`, `{level}`
- `{first_seen}`, `{last_seen}`
- `{culprit}`
- `{metadata_type}`, `{metadata_value}`
- `{rule_class}`, `{rule_priority}`, `{rule_confidence}`, `{rule_reasoning}`

Required output:

```json
{
  "class": "dependency",
  "priority": "P1",
  "danger": "high",
  "confidence": 0.86,
  "reasoning": "Short evidence-based explanation."
}
```

Allowed classes are currently shared across sources:

- `availability`
- `dependency`
- `auth-permission`
- `data-integrity`
- `input-validation`
- `client-disconnect`
- `frontend-client`
- `performance-timeout`
- `unknown`

If a future source needs a new class, update rules, thresholds, prompts, and downstream docs together.

## Review Prompt Contract

Current variables:

- `{issue_id}`
- `{source}`, `{source_type}`
- `{title}`, `{summary}`
- `{project}`, `{service}`, `{environment}`
- `{classification}`, `{classification_reasoning}`, `{confidence}`
- `{priority}`, `{danger}`
- `{count}`, `{users}`
- `{first_seen}`, `{last_seen}`, `{time_window}`
- `{link}`

Required output:

```json
{
  "decision": "review",
  "confidence": 0.78,
  "reasoning": "Short evidence-based explanation.",
  "user_impact": {
    "affected_users": 12,
    "affected_flow": "unknown",
    "estimated_revenue_loss": null,
    "customer_facing": null
  },
  "urgency": {
    "level": "high",
    "trend": "unknown",
    "sla_breach": null,
    "can_wait": null
  },
  "send_reasons": []
}
```

Important: the current code auto-approves only when `decision == "send"` and confidence meets `pipeline.review.auto_send_confidence_threshold`.

## Recommendation Prompt Contract

Current variables:

- `{issue_id}`
- `{source}`, `{source_type}`
- `{title}`, `{summary}`
- `{project}`, `{service}`, `{environment}`
- `{classification}`, `{classification_reasoning}`
- `{priority}`, `{danger}`
- `{count}`, `{users}`, `{time_window}`
- `{first_seen}`, `{last_seen}`
- `{culprit}`, `{platform}`, `{level}`
- `{link}`
- `{review_decision}`, `{review_confidence}`, `{review_reasoning}`
- `{user_impact}`, `{urgency}`

Required markdown headings:

```markdown
# 🔴 P1: One-line summary

## Executive Summary

## Immediate Action Required

## Root Cause Hypothesis

## Investigation Steps

## Success Criteria

## Additional Context
```

The Teams sender extracts `Executive Summary` and `Immediate Action Required`, so do not rename those headings.

## Self-Improvement Summary Contract

Current variables:

- `{pattern_kind}`
- `{source}`
- `{project}`
- `{classification}`
- `{priority}`
- `{sample_size}`
- `{evidence_counts}`
- `{reviewer_notes}`

Required output: 2-3 plain-text sentences, no markdown heading, no code, no JSON.

## Validation Checklist Before Production

For a prompt change, run at least:

```bash
python3 - <<'PY'
from pathlib import Path
# Smoke-test prompt .format(...) using representative variables.
PY

python3 -m unittest tests.test_config_loader tests.test_self_improve tests.test_improvement_patcher
```

For production readiness, also run a representative pipeline dry run or controlled run and inspect:

```bash
ls output/alerts/reviewed/
ls output/alerts/recommendations/
python3 scripts/review_queue.py list --status pending --limit 20
```

Check that:

- JSON outputs parse without fallback errors.
- auto-approved alerts are genuinely actionable.
- pending alerts include useful reasoning for human review.
- recommendation markdown has the required headings.
- commands are safe, use placeholders when needed, and do not invent infrastructure names.
