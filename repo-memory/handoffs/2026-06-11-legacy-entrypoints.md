# Handoff - 2026-06-11 Legacy Entrypoints Rename

## Session Summary

- Renamed the compatibility wrapper directory from `agents/` to `legacy_entrypoints/`.
- Updated shell scripts, manual-review subprocess calls, tests, and docs to use the new path.
- Added `legacy_entrypoints/README.md` and `legacy_entrypoints/__init__.py` to make the purpose of the wrapper layer explicit.
- Refreshed architecture and repo-memory references so the code layout matches the documented model.

## Current Status

- `alert_agent/` remains the real implementation package.
- `scripts/` remains the operator and cron entrypoint layer.
- `legacy_entrypoints/` is now clearly labeled as compatibility-only wrappers over shared pipeline code.

## Validation

- `python3 -m unittest tests.test_review_notifications tests.test_self_improve tests.test_improvement_review_state`
- `python3 -m py_compile alert_agent/core/manual_review.py legacy_entrypoints/triage_agent.py legacy_entrypoints/review_agent.py legacy_entrypoints/recommendation_agent.py legacy_entrypoints/sender.py`

## Remaining Gap

- The wrapper layer still exists; it has only been renamed and clarified, not removed.
- A later cleanup can replace wrapper-based subprocess calls with direct `scripts/` or `alert_agent.commands` entrypoints.

## Exact Next Step

If desired, remove the need for wrapper scripts entirely by switching remaining subprocess calls onto direct `scripts/` or `python -m alert_agent...` commands.
