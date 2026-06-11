# SRE Alert Agent

AI-assisted Sentry triage for Microsoft Teams. The system pulls recent Sentry issues, classifies them with rules plus optional AI, holds uncertain cases for review, and sends approved alerts to Teams.

## For Bosses

- Purpose: reduce noise and route only actionable Sentry incidents to the team.
- Current flow: Sentry -> Triage -> Review -> Recommendation -> Teams.
- Human control stays in the loop for uncertain or non-critical issues.
- Rules, thresholds, prompts, and ignore lists are all kept in Git.

## Current Status

- Production triage pipeline runs through `scripts/run_triage.sh`.
- Internal pipeline now runs through `alert_agent/pipeline/` with a source plugin layer under `alert_agent/sources/`.
- Azure OpenAI support for `pi` is wired and tested through `.env`.
- Bulk Sentry corpus analysis exists in `scripts/analyze_sentry_corpus.py`.
- Recent tuning reduced the 14-day unknown classification bucket from `48` issues to `31`.

## Operator URLs

- [Review UI](http://localhost:8088)
- [Metrics UI](http://localhost:8088/metrics)

## Main Docs

- [repo-memory/current-state.md](repo-memory/current-state.md) - active repo memory, current implementation state, and likely next step
- [QUICKSTART.md](QUICKSTART.md) - 5 minute local test
- [DEPLOYMENT.md](DEPLOYMENT.md) - workstation setup, cron, monitoring
- [docs/OPERATIONS_RUNBOOK.md](docs/OPERATIONS_RUNBOOK.md) - logs, state files, debug flow, and day-2 operations
- [docs/WORKSTATION_MONITORING.md](docs/WORKSTATION_MONITORING.md) - AI usage ledger and budget alerts on the workstation
- [docs/SELF_IMPROVEMENT_AGENT.md](docs/SELF_IMPROVEMENT_AGENT.md) - AI-assisted self-improvement design and rollout guardrails
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - system design
- [POC_TEST_RESULTS.md](POC_TEST_RESULTS.md) - short proof-of-concept summary

## Typical Commands

```bash
# Run the production pipeline
./scripts/run_triage.sh --minutes 70

# Or run the shared source-aware pipeline directly
python3 scripts/run_pipeline.py --source sentry --minutes 70

# View AI token/cost usage for the current month
python3 scripts/usage_report.py

# Check configured AI budgets and emit Teams warnings if thresholds are crossed
python3 scripts/check_ai_budget.py

# Check pipeline health and emit Teams warnings for failed/stale runs
python3 scripts/check_pipeline_health.py

# Check queue/workflow state and emit Teams warnings for backlog or stale files
python3 scripts/check_queue_health.py

# Send or preview the daily monitoring summary
python3 scripts/send_daily_summary.py --dry-run --force

# Generate the static monitoring dashboard
python3 scripts/generate_dashboard.py

# Generate self-improvement proposals from manual review history
python3 scripts/run_self_improve.py --dry-run --force

# Check whether budget enforcement would activate
python3 scripts/check_budget_enforcement.py

# Review pending alerts from the terminal
python3 scripts/review_queue.py list
python3 scripts/review_queue.py show BACKEND-ZY6
python3 scripts/review_queue.py approve BACKEND-ZY6 --reviewer danny --note "Validated impact"

# Run the local review UI for backend / AI teams
# Includes live /metrics and /improvements pages for operations and proposal review
python3 scripts/review_web.py --host 0.0.0.0 --port 8088

# Or run it as a systemd service on the workstation
sudo cp deploy/systemd/sentry-review-web.service.example /etc/systemd/system/sentry-review-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now sentry-review-web.service

# Test Azure/OpenAI provider wiring
./scripts/test_azure_pi.sh

# Analyze a larger corpus to improve rules/prompts
python3 scripts/analyze_sentry_corpus.py --days 14 --limit 3000
```

## Output

```text
output/
  alerts/
    triage/
    pending/
    approved/
    recommendations/
    sent/
    ignored/
  analysis/
  logs/
  metrics/
```

## Notes

- Keep real credentials in `.env` on the workstation or a private env file outside Git.
- Budget enforcement now emits a separate monitoring notification when enforcement activates or clears.
- `AGENTS.md` is the developer/operator reference for this repo, not the business summary.
- Older `docs/` files are still useful as reference, but the files above are the main entry points.
