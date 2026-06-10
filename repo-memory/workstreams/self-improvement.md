# Workstream: Self-Improvement

Last updated: 2026-06-10

## Goal

Turn manual review outcomes into safe, human-reviewed improvement proposals for rules, thresholds, and prompts.

## Durable Design Doc

- `docs/SELF_IMPROVEMENT_AGENT.md`

## Implemented

- Read-only runner exists in `alert_agent/commands/run_self_improve.py`
- Audit events and issue documents are collected in `alert_agent/improvement/collector.py`
- Pattern analysis exists in `alert_agent/improvement/analyzer.py`
- Proposal generation and bundle writing exist in `alert_agent/improvement/proposer.py`
- Review web UI already exposes an `/improvements` page in `scripts/review_web.py`
- Tests exist in `tests/test_self_improve.py`

## Not Implemented Yet

- proposal decision workflow: accept / reject / defer
- proposal audit log
- proposal detail view with reviewer note
- patch-ready output for accepted proposals
- command or UI flow to apply accepted proposal content into config or prompts

## Current Assessment

The feature is beyond "step 1 planned". Phase 1 read-only proposal generation is already real.

The next meaningful step is not another analyzer pass. The next meaningful step is human handling of generated proposals.

## Recommended Next Slice

1. Add proposal storage conventions beyond `status: proposed`
2. Add CLI or web actions for proposal review
3. Persist reviewer decision history for proposals
4. Generate a focused patch suggestion for accepted proposals

## Notes

- Keep this work read-only with respect to production config until proposal review is solid.
- Prefer config and prompt changes before Python logic changes.
- If the roadmap doc and code disagree, trust the code and record the mismatch here.
