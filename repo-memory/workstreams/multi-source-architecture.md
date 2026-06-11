# Workstream: Multi-Source Architecture

Last updated: 2026-06-11

## Goal

Turn the repo from a Sentry-shaped implementation into a shared alert engine that can ingest multiple sources through explicit plugins.

## Implemented

- canonical alert model in `alert_agent/core/models.py`
- plugin contract in `alert_agent/core/plugin.py`
- registry in `alert_agent/core/registry.py`
- shared triage, review, recommendation, and sender stages in `alert_agent/pipeline/`
- Sentry plugin in `alert_agent/sources/sentry/`
- source-aware entrypoint in `scripts/run_pipeline.py`
- legacy wrappers removed; shell scripts, tests, and docs now point at `alert_agent.pipeline.*` directly
- orchestrator can pass `PIPELINE_SOURCE` to triage while still defaulting to `sentry`

## Remaining Work

- move policy files from generic `config/` and `prompts/` locations into source-specific directories when ready
- add source labels and filtering in `scripts/review_web.py`
- add a second source plugin to validate the abstraction
- decide whether monitor summaries and UI should show per-source counters

## Notes

- current review and recommendation stages are shared, not source-specific classes
- that is intentional for now; only add source-specific review or recommendation behavior when a real second source demands it
