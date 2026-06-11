# Handoff - 2026-06-11 Remove Legacy Entrypoints

## Session Summary

- Removed `legacy_entrypoints/` entirely.
- Rewired all remaining runtime and operator paths to call `alert_agent.pipeline.*` modules directly.

## Code Paths Updated

- `scripts/run_triage.sh` now runs:
  - `python3 -m alert_agent.pipeline.triage`
  - `python3 -m alert_agent.pipeline.review`
  - `python3 -m alert_agent.pipeline.recommendation`
  - `python3 -m alert_agent.pipeline.sender`
- `alert_agent/core/manual_review.py` dispatch now invokes recommendation and sender through `python3 -m ...`.
- Operator docs and helper scripts were updated to stop referencing deleted wrapper files.

## Verification

- `python3 -m unittest tests.test_config_loader tests.test_self_improve tests.test_improvement_review_state tests.test_improvement_patcher tests.test_improvement_measurement`
- `python3 -m py_compile alert_agent/core/manual_review.py alert_agent/pipeline/triage.py alert_agent/pipeline/review.py alert_agent/pipeline/recommendation.py alert_agent/pipeline/sender.py scripts/analyze_sentry_corpus.py scripts/review_queue.py scripts/review_web.py`
- `bash -n scripts/run_triage.sh scripts/test_poc.sh scripts/install.sh scripts/force_approve_test.sh`
- `python3 scripts/review_queue.py dispatch --dry-run`
- `python3 -m alert_agent.pipeline.triage --config config/agent_config.yaml --source sentry --minutes 20 --dry-run`
  - required running outside sandbox to reach Sentry
  - fetched 6 alerts and completed triage successfully

## Remaining Known Gap

- `alert_agent.pipeline.review` still depends on a `pi`/Azure credential path that is not currently satisfying the configured provider in this environment.
