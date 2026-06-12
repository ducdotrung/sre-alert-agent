# Workstream: Multi-Source Architecture

Last updated: 2026-06-12

## Goal

Turn the repo from a Sentry-shaped implementation into a shared alert engine that can ingest multiple sources through explicit plugins.

## Implemented

- canonical alert model in `alert_agent/core/models.py`
- plugin contract in `alert_agent/core/plugin.py`
- registry in `alert_agent/core/registry.py`
- shared triage, review, recommendation, and sender stages in `alert_agent/pipeline/`
- Sentry plugin in `alert_agent/sources/sentry/`
- triage/review/recommendation prompts now receive normalized source metadata fields such as `source`, `source_type`, `summary`, `service`, and `environment`
- source-aware entrypoint in `scripts/run_pipeline.py`
- orchestrator can pass `PIPELINE_SOURCE` to triage while still defaulting to `sentry`
- config surface is consolidated onto `pipeline.*`, `sources.*`, and `policy_packs.*`
- `alert_agent/core/config_loader.py` no longer falls back to legacy top-level stage or source sections
- sender now loads `pipeline.sender` like the other shared stages
- callers now execute `python3 -m alert_agent.pipeline.{triage,review,recommendation,sender}` directly
- `scripts/run_triage.sh` and `alert_agent/core/manual_review.py` now dispatch those direct module entrypoints instead of wrapper files

## Remaining Work

- move policy files from generic `config/` and `prompts/` locations into source-specific directories when ready
- add source labels and filtering in `scripts/review_web.py`
- add a second source plugin to validate the abstraction
- decide whether monitor summaries and UI should show per-source counters
- decide how far Kubernetes packaging should be normalized across `deploy/aks/` and `deploy/eks/`, or whether one provider-neutral package should replace both later

## Notes

- current review and recommendation stages are shared, not source-specific classes
- that is intentional for now; only add source-specific review or recommendation behavior when a real second source demands it
- workstation sanity check on 2026-06-11: `scripts/run_pipeline.py --source sentry --triage-dry-run --recommendation-dry-run --sender-dry-run` reached Sentry successfully once run outside the sandbox
- workstation sanity check on 2026-06-11: `python3 -m alert_agent.pipeline.triage --config config/agent_config.yaml --source sentry --minutes 20 --dry-run` reached Sentry successfully once run outside the sandbox
- local sanity check on 2026-06-11: `python3 scripts/review_queue.py dispatch --dry-run` succeeded after switching dispatch to direct module calls
- same workstation pass showed `alert_agent.pipeline.review` still depends on an AI key path that is not currently satisfying `pi` for the configured Azure provider
