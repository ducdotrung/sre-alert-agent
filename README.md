# SRE Alert Agent

AI-assisted alert triage for Sentry. The repo pulls recent issues, classifies them with rules plus optional AI, routes uncertain cases into a manual review queue, generates responder guidance for approved alerts, and can send the result to Microsoft Teams.

## Repository Layout

- `alert_agent/`: shared pipeline, source plugins, monitoring, and core runtime code
- `config/`: thresholds, ignore rules, and pipeline configuration
- `prompts/`: model instructions for triage, review, recommendations, and self-improvement
- `scripts/`: shell and Python entrypoints for running the pipeline and operations tooling
- `docs/`: public project documentation
- `tests/`: unit test coverage for core workflows
- `repo-memory/`: short contributor handoff notes and current-state tracking

## Quick Start

```bash
cp .env.example .env
python3 -m alert_agent.pipeline.triage --dry-run
./scripts/run_triage.sh --minutes 70
python3 scripts/review_queue.py list
python3 -m alert_agent.pipeline.sender --dry-run
```

The main environment variables are `SENTRY_BASE_URL`, `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, the AI provider credentials you want to use, and `TEAMS_WEBHOOK_URL` if you want real delivery.

## Common Commands

```bash
# Run the legacy shell pipeline
./scripts/run_triage.sh --minutes 70

# Run the source-aware pipeline directly
python3 scripts/run_pipeline.py --source sentry --minutes 70

# Review queue from the CLI
python3 scripts/review_queue.py list
python3 scripts/review_queue.py show SENTRY-123
python3 scripts/review_queue.py approve SENTRY-123 --reviewer reviewer-1 --note "Validated impact"

# Local review UI
python3 scripts/review_web.py --host 0.0.0.0 --port 8088

# Monitoring and reporting
python3 scripts/check_ai_budget.py
python3 scripts/check_pipeline_health.py
python3 scripts/check_queue_health.py
python3 scripts/send_daily_summary.py --dry-run --force
python3 scripts/generate_dashboard.py

# Rule tuning and self-improvement
python3 scripts/analyze_sentry_corpus.py --days 14 --limit 3000
python3 scripts/run_self_improve.py --dry-run --force
```

## Output Layout

```text
output/
  alerts/
    triage/
    pending/
    approved/
    reviewed/
    recommendations/
    sent/
    rejected/
    ignored/
  analysis/
  logs/
  metrics/
```

## Docs

- [docs/QUICKSTART.md](docs/QUICKSTART.md): local setup and first run
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): system flow and extension points
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): generic single-host deployment
- [docs/CRONJOB_SETUP.md](docs/CRONJOB_SETUP.md): scheduled execution examples
- [docs/OPERATIONS_RUNBOOK.md](docs/OPERATIONS_RUNBOOK.md): queue, logs, and recovery steps
- [docs/WORKSTATION_MONITORING.md](docs/WORKSTATION_MONITORING.md): metrics, budgets, and health alerts
- [docs/SELF_IMPROVEMENT_AGENT.md](docs/SELF_IMPROVEMENT_AGENT.md): proposal-generation workflow
- [docs/TRIAGE_ANALYSIS.md](docs/TRIAGE_ANALYSIS.md): corpus analysis and tuning workflow
- [repo-memory/current-state.md](repo-memory/current-state.md): current implementation state for contributors
