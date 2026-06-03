# Sentry Alert Agent System - Architecture Proposal

**Version**: 0.1  
**Date**: 2026-06-01  
**Author**: DevOps Team  
**Status**: Proposal for Management Review

This document describes both the current shipped workflow and the proposed AI-enhanced workflow.

## Executive Summary

**Key benefits**
- Route only actionable alerts to Teams.
- Keep human review for uncertain cases.
- Keep rules, prompts, and thresholds in Git for auditability.

**Risk level**: Low, because the proposal is incremental and keeps a rule-based fallback.

## High-Level Flow

```text
Sentry API
  -> Agent 1: Triage Agent (rule-based + AI)
  -> Agent 2: Review Agent (AI)
  -> Agent 3: Recommendation Agent (AI)
  -> Sender (rule-based webhook delivery)
  -> Microsoft Teams
```

### Agent 1: Triage Agent

**Purpose**: Classify and prioritize incoming issues.

**Execution**: Every 1 hour.

**Logic**
1. Fetch recent issues from Sentry.
2. Apply keyword and threshold rules first.
3. Apply ignore rules from config.
4. If confidence is low, send the issue to AI for reclassification.
5. Emit final priority, class, danger level, confidence, and reasoning.

**Output**
`output/alerts/triage/SENTRY-{id}.json`

### Agent 2: Review Agent

**Purpose**: Decide whether a P0/P1 issue should be auto-approved or held for review.

**Execution**: Triggered by the triage agent when P0/P1 issues are found.

**Logic**
1. Consume only P0/P1 issues.
2. Evaluate user impact, business impact, urgency, and confidence.
3. Auto-approve only when priority is P0 and confidence is high enough.
4. Otherwise place the issue in pending review.

**Output**
- Approved: `output/alerts/approved/SENTRY-{id}.json`
- Pending: `output/alerts/pending/SENTRY-{id}.json`

### Agent 3: Recommendation Agent

**Purpose**: Generate actionable remediation guidance.

**Execution**: Triggered after approval.

**Logic**
1. Read approved issues.
2. Generate a concise remediation summary.
3. Include specific next steps and, when appropriate, commands or rollback ideas.
4. Render the result as Markdown for delivery.

**Output**
`output/alerts/recommendations/SENTRY-{id}.md`

### Sender

**Purpose**: Deliver the final alert to Teams.

**Execution**: After recommendations are produced.

**Logic**
1. Read recommendation Markdown files.
2. Parse front matter and content.
3. Build a Teams MessageCard payload.
4. POST to the Teams webhook.
5. Move delivered alerts to `sent/` and store a receipt.

## Proposal Details

### Rule-Based First, AI Second

The proposal does not replace rules with AI. It uses rules as the first filter because they are cheap, deterministic, and easy to audit. AI is reserved for:
- ambiguous issues,
- impact assessment,
- remediation recommendations.

### Human-in-the-Loop

Human review remains in the path for:
- low-confidence issues,
- non-P0/P1 alerts,
- exceptions that do not fit existing rules.

### Sender is Rule-Based

The sender is intentionally not AI-driven. It should stay deterministic:
- read generated files,
- format Teams cards,
- post via webhook,
- record receipts.

That keeps the delivery path simple and reliable.

## Repository Structure

Proposed layout:

```text
agents/
  triage_agent.py
  review_agent.py
  recommendation_agent.py
  sender.py
  shared/
    ai_client.py
    sentry_client.py
    config_loader.py

config/
  agent_config.yaml
  ignore_rules.json
  classification_rules.yaml
  priority_thresholds.yaml

prompts/
  triage_reclassify.txt
  review_decision.txt
  recommendation_generate.txt

output/
  alerts/
    triage/
    pending/
    approved/
    recommendations/
    sent/
    ignored/
  logs/
```

The current repo also keeps the simpler shipped-flow layout:

```text
reports/
snapshots/
alerts/pending/
alerts/approved/
alerts/sent/
alerts/ignored/
```

## Rollout Plan

### Phase 1
- Run the triage pipeline.
- Keep all review manual.
- Validate false positive rate.

### Phase 2
- Auto-approve only high-confidence P0s.
- Keep P1 in manual review.

### Phase 3
- Expand coverage to selected P1s.
- Add deployment context enrichment.
- Add a web UI only after the pipeline is stable.

## Risk and Mitigation

| Risk | Mitigation |
|---|---|
| AI false positives | Keep confidence thresholds and manual review |
| AI false negatives | Rule-based fallback remains active |
| Webhook failure | Retry and keep receipts for replay |
| Cost overrun | Rate limits and monthly spend monitoring |
| Alert fatigue | Ignore rules and tighter thresholds |

## Success Metrics

- Triage completes hourly without failure.
- Critical issues reach Teams in under 5 minutes.
- False positive rate stays below target.
- Pending queue remains manageable for humans.

## Security Notes

- Keep Sentry tokens, AI keys, and Teams webhooks out of Git.
- Store runtime output outside the repo or in ignored paths.
- Track config changes in Git for auditability.

## Future Enhancements

- Web UI for pending review.
- Deployment history correlation.
- Similar-incident lookup.
- Feedback loop for alert usefulness.
- Automated remediation for known issues.
