# Operations Runbook

## Key Paths

- repo: `/opt/sre-alert-agent` or your chosen checkout path
- queue data: `output/alerts/`
- logs: `output/logs/`
- metrics and state files: `output/metrics/`
- config: `config/agent_config.yaml`

## Daily Checks

```bash
python3 scripts/check_pipeline_health.py
python3 scripts/check_queue_health.py
python3 scripts/usage_report.py
python3 scripts/review_queue.py list
```

## Queue Operations

```bash
python3 scripts/review_queue.py list
python3 scripts/review_queue.py show SENTRY-123
python3 scripts/review_queue.py approve SENTRY-123 --reviewer reviewer-1 --note "Validated impact"
python3 scripts/review_queue.py reject SENTRY-123 --reviewer reviewer-1 --note "Not actionable"
python3 scripts/review_queue.py ignore SENTRY-123 --reviewer reviewer-1 --note "Known noise"
python3 scripts/review_queue.py dispatch --send
```

## Log Locations

- orchestrator: `output/logs/orchestrator.log`
- triage: `output/logs/triage-YYYYMMDD.log`
- review: `output/logs/review-YYYYMMDD.log`
- recommendation: `output/logs/recommendation-YYYYMMDD.log`
- sender: `output/logs/sender-YYYYMMDD.log`

## Common Recovery Steps

### Pipeline produced no alerts

1. verify `.env` values are loaded
2. test Sentry connectivity
3. run `python3 agents/triage_agent.py --dry-run`

### Queue is growing but nothing is sent

1. inspect `output/alerts/pending/` and `output/alerts/approved/`
2. run `python3 scripts/review_queue.py dispatch`
3. run sender in dry-run mode to inspect the payload

### Sender failed

1. check `TEAMS_WEBHOOK_URL`
2. run `python3 agents/sender.py --config config/agent_config.yaml --dry-run`
3. inspect the latest markdown in `output/alerts/recommendations/`

### Review UI is stale

1. check the service or process running `scripts/review_web.py`
2. confirm queue files are still being written
3. confirm `REVIEW_WEB_BASE_URL` matches the deployed UI address if links are wrong

## Relevant State Files

- `output/metrics/pipeline_state.json`
- `output/metrics/health_alert_state.json`
- `output/metrics/queue_alert_state.json`
- `output/metrics/budget_alert_state.json`
- `output/metrics/daily_summary_state.json`
- `output/metrics/manual_review_actions.jsonl`

## Contributor Notes

Project-level handoff notes live in [../repo-memory/current-state.md](../repo-memory/current-state.md) and the related workstream files under `repo-memory/workstreams/`.
