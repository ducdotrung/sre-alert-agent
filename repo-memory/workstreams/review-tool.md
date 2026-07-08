# Workstream: Review Tool

Last updated: 2026-07-08

## Goal

Make pending alerts easy to inspect, decide, audit, and dispatch without direct file manipulation.

## Durable References

- `docs/OPERATIONS_RUNBOOK.md`
- `scripts/review_queue.py`
- `scripts/review_web.py`

## Implemented

- CLI review actions in `scripts/review_queue.py`
- Manual review storage and audit history in `alert_agent/core/manual_review.py`
- Web UI in `scripts/review_web.py`
- Queue tabs, issue detail pages, manual actions, metrics page, and improvement proposal listing
- Review web routing now supports both `/` and a configured subpath such as `/sre-alert-review`, using `common.review_web_base_url` as the canonical outbound base URL
- Pending-review Teams cards now include inline review, queue, and source links plus explicit URL facts

## Related Sender Guardrails

- `alert_agent/pipeline/sender.py` now backfills recommendation metadata from queue JSON, rejects stale recommendations using `pipeline.sender.max_last_seen_age_hours`, validates live Sentry issue existence when enabled, and writes skipped receipts under `output/alerts/skipped/`

## Remaining Work

- reviewer ergonomics improvements listed in roadmap
- batch or faster review flows if queue volume grows
- possible deeper integration between issue review and improvement proposal review
- optional source-aware filters once a second alert source exists

## Notes

- The old review roadmap was removed after moving active task state into `repo-memory/`.
