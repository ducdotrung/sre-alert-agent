# Workstream: Self-Improvement

Last updated: 2026-06-11

## Goal

Turn manual review outcomes into safe, human-reviewed improvement proposals for rules, thresholds, and prompts.

## Durable Design Doc

- `docs/SELF_IMPROVEMENT_AGENT.md`

## Implemented

- Runner exists in `alert_agent/commands/run_self_improve.py`
- Audit events and issue documents are collected in `alert_agent/improvement/collector.py`
- Pattern analysis exists in `alert_agent/improvement/analyzer.py`
- Proposal generation now writes one file per proposal plus `latest.json` in `alert_agent/improvement/proposer.py`
- Proposal identity, manifests, and storage helpers live in `alert_agent/improvement/storage.py`
- Reviewer decisions and applied bookkeeping live in `alert_agent/improvement/{decisions,review_state}.py`
- Patch generation exists in `alert_agent/improvement/patcher.py`
- Impact measurement exists in `alert_agent/improvement/measurement.py`
- CLI proposal workflow now lives in `scripts/review_queue.py proposals ...`
- Review web UI exposes proposal decision flow plus applied-impact table in `scripts/review_web.py`
- Tests exist in `tests/test_self_improve.py`, `tests/test_improvement_review_state.py`, `tests/test_improvement_patcher.py`, and `tests/test_improvement_measurement.py`

## Not Implemented Yet

- in-app auto-apply of proposal patches into tracked config files
- proposal voting or multi-reviewer workflow
- automatic regression-to-new-proposal feedback from measured regressions

## Current Assessment

The feature is now a closed human-reviewed loop for POC scope:

- detect repeated manual-review patterns
- write durable proposal files
- review proposals in CLI or web
- generate patch-ready diffs
- mark shipped proposals as applied
- show before/after volume for applied proposals

## Recommended Next Slice

1. Add direct links to generated `.patch` artifacts in the web detail page
2. Add lightweight reviewer-facing guidance for `git apply` / `git apply --check`
3. Promote measurement regressions back into proposal generation only after a real false-positive sample exists

## Notes

- Keep this work read-only with respect to production config until patch output is solid and human-reviewed.
- Prefer config and prompt changes before Python logic changes.
- If the roadmap doc and code disagree, trust the code and record the mismatch here.
