# Current State

Last updated: 2026-06-12

## Repo Snapshot

- Core Sentry triage pipeline is implemented and runnable through `scripts/run_triage.sh`.
- The runtime now has a shared pipeline layer in `alert_agent/pipeline/` and a source plugin layer in `alert_agent/sources/`.
- Legacy wrapper entrypoints have been removed; callers now invoke `alert_agent.pipeline.*` modules directly.
- Manual review workflow exists in both CLI and web UI form.
- The review web now supports either `/` or a configured subpath derived from `common.review_web_base_url`.
- Monitoring work is implemented for current scope: usage ledger, budgets, pipeline health, queue health, daily summary, and static dashboard.
- Self-improvement proposals now support per-proposal storage, review decisions, patch artifacts, manual apply bookkeeping, and impact measurement.
- Public-safe container packaging now exists as `Dockerfile` and `requirements.txt`, and Kubernetes examples now exist under both `deploy/aks/` and `deploy/eks/`.
- Host quick-deploy assets now include a managed cron example under `deploy/systemd/` for triage, health, and self-improvement jobs.
- Prompt contracts are refreshed and documented in `docs/PROMPT_GUIDE.md`.

## Current Truth By Area

### Monitoring

- Status: stable for current planned scope
- Source of truth: `docs/WORKSTATION_MONITORING.md` plus the monitoring scripts in `scripts/`
- Note: the old monitoring roadmap was removed after moving active status tracking into `repo-memory/`.

### Review Tool

- Status: usable now
- Implemented: CLI review workflow, review web UI, audit history, pending-review notifications, direct review links, root/subpath routing support
- Remaining gap: remaining work is mostly ergonomics and deeper review workflows
- Source of truth: `scripts/review_queue.py`, `scripts/review_web.py`, and this memory folder

### Self-Improvement

- Status: proposal loop is implemented through review, patch generation, manual apply tracking, and read-only impact measurement
- Implemented:
  - collect manual review history
  - analyze repeated patterns
  - generate one file per proposal plus `latest.json` manifest
  - persist reviewer decisions on proposal documents
  - accept, reject, defer, patch, and apply proposals from CLI
  - review and decide proposals in the web UI
  - generate unified diff patch artifacts for accepted proposals
  - track applied proposals and suppress them in future self-improve runs
  - measure before/after manual-review volume for applied proposals
- Main code:
  - `alert_agent/commands/run_self_improve.py`
  - `alert_agent/improvement/collector.py`
  - `alert_agent/improvement/analyzer.py`
  - `alert_agent/improvement/storage.py`
  - `alert_agent/improvement/proposer.py`
  - `alert_agent/improvement/decisions.py`
  - `alert_agent/improvement/patcher.py`
  - `alert_agent/improvement/measurement.py`
  - `alert_agent/improvement/review_state.py`
  - `scripts/review_web.py`
  - `scripts/review_queue.py`
  - `tests/test_self_improve.py`
  - `tests/test_improvement_review_state.py`
  - `tests/test_improvement_patcher.py`
  - `tests/test_improvement_measurement.py`
- Remaining gap: proposal patches are still human-applied only; there is no direct config mutation in-app

### Multi-Source Architecture

- Status: canonical config surface is consolidated; architecture is ready for a real second source
- Implemented:
  - canonical alert model in `alert_agent/core/models.py`
  - source plugin contract in `alert_agent/core/plugin.py`
  - built-in registry in `alert_agent/core/registry.py`
  - Sentry plugin in `alert_agent/sources/sentry/`
  - shared pipeline stages in `alert_agent/pipeline/`
  - normalized source metadata now flows into triage, review, and recommendation prompts
  - source-aware command entrypoint in `scripts/run_pipeline.py`
  - only canonical config sections remain for pipeline stages, sources, and policy packs
  - callers now execute `python3 -m alert_agent.pipeline.{triage,review,recommendation,sender}` directly
- Current limitation: only Sentry is implemented as a source plugin today; review and recommendation remain shared stages that use source-aware metadata and policy packs

## Most Likely Next Build

The next major options are:

1. add the second source plugin, likely Grafana, to validate the architecture with a real non-Sentry source
2. add source filter and source labels to the review UI
3. refine the new `deploy/eks/` package for the exact hackathon AWS environment, or keep using its env-driven render flow for image, hostname, ACM cert, and EFS storage class
4. fix the Azure/OpenAI review-agent config path so workstation review runs stop falling back to manual-review-only behavior

If the goal is architecture validation, the highest-value next step is implementing one real second source.

## Durable Docs Versus Memory

- `docs/ARCHITECTURE.md` and related files are durable reference docs
- `repo-memory/` is the place to record session state, handoffs, and exact next actions
