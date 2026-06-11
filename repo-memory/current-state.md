# Current State

Last updated: 2026-06-11

## Repo Snapshot

- Core Sentry triage pipeline is implemented and runnable through `scripts/run_triage.sh`.
- The runtime now has a shared pipeline layer in `alert_agent/pipeline/` and a source plugin layer in `alert_agent/sources/`.
- The legacy `agents/` compatibility wrappers were removed; operational entrypoints now call `alert_agent.pipeline.*` directly.
- Manual review workflow exists in both CLI and web UI form.
- Monitoring work is implemented for current scope: usage ledger, budgets, pipeline health, queue health, daily summary, and static dashboard.
- Self-improvement phase 1 is partially implemented as a read-only proposal generator.
- Public-facing cleanup completed for the README, docs, example deployment files, and UI copy; old personal paths, legacy repo names, and internal URLs were removed.

## Current Truth By Area

### Monitoring

- Status: stable for current planned scope
- Source of truth: `docs/WORKSTATION_MONITORING.md` plus the monitoring scripts in `scripts/`
- Note: the old monitoring roadmap was removed after moving active status tracking into `repo-memory/`.

### Review Tool

- Status: usable now
- Implemented: CLI review workflow, review web UI, audit history, pending-review notifications, direct review links
- Remaining gap: remaining work is mostly ergonomics and deeper review workflows
- Source of truth: `scripts/review_queue.py`, `scripts/review_web.py`, and this memory folder

### Self-Improvement

- Status: phase 1 read-only pipeline exists
- Implemented:
  - collect manual review history
  - analyze repeated patterns
  - generate proposal bundles
  - expose proposals in the review web UI
- Main code:
  - `alert_agent/commands/run_self_improve.py`
  - `alert_agent/improvement/collector.py`
  - `alert_agent/improvement/analyzer.py`
  - `alert_agent/improvement/proposer.py`
  - `tests/test_self_improve.py`
- Remaining gap: proposal review lifecycle is not complete yet; proposals can be listed, but there is no full accept/reject/apply workflow

### Multi-Source Architecture

- Status: initial implementation complete for Sentry as the only active source
- Implemented:
  - canonical alert model in `alert_agent/core/models.py`
  - source plugin contract in `alert_agent/core/plugin.py`
  - built-in registry in `alert_agent/core/registry.py`
  - Sentry plugin in `alert_agent/sources/sentry/`
  - shared pipeline stages in `alert_agent/pipeline/`
  - source-aware command entrypoint in `scripts/run_pipeline.py`
- Current limitation: only the triage stage is truly source-pluggable today; review and recommendation remain shared stages that use source-aware metadata and policy packs

## Most Likely Next Build

The next major options are:

1. add proposal review lifecycle for self-improvement
2. add source filter and source labels to the review UI
3. add the second source plugin, likely Grafana, to validate the architecture with a real non-Sentry source

If the goal is architecture validation, the highest-value next step is implementing one real second source.

## Durable Docs Versus Memory

- `docs/ARCHITECTURE.md` and related files are durable reference docs
- `repo-memory/` is the place to record session state, handoffs, and exact next actions
