# Monitoring

The repo includes lightweight monitoring built around files in `output/metrics/` and optional Teams notifications.

## Available Checks

- AI budget thresholds: `python3 scripts/check_ai_budget.py`
- pipeline freshness and lock-file state: `python3 scripts/check_pipeline_health.py`
- queue backlog and stale stages: `python3 scripts/check_queue_health.py`
- daily operational summary: `python3 scripts/send_daily_summary.py --dry-run --force`
- budget enforcement state transitions: `python3 scripts/check_budget_enforcement.py`

## Metrics Files

Typical files written under `output/metrics/`:

- `pipeline_state.json`
- `budget_alert_state.json`
- `health_alert_state.json`
- `queue_alert_state.json`
- `daily_summary_state.json`
- `budget_enforcement_state.json`
- `manual_review_actions.jsonl`

## Environment Variables

Common monitoring variables from `.env.example`:

```bash
SENTRY_METRICS_DIR=./output/metrics
TEAMS_MONITOR_WEBHOOK_URL=https://example.invalid/webhook
AI_MONTHLY_BUDGET_USD=10
AI_DAILY_BUDGET_USD=1
AI_BUDGET_THRESHOLDS_PERCENT=50,80,100
HEALTH_STALE_RUN_AFTER_MINUTES=120
HEALTH_STUCK_LOCK_AFTER_MINUTES=90
QUEUE_PENDING_THRESHOLD=10
QUEUE_APPROVED_STALE_HOURS=4
QUEUE_RECOMMENDATION_STALE_HOURS=2
```

## Review UI Metrics Pages

The local review UI exposes:

- `/metrics`: runtime and queue metrics
- `/improvements`: self-improvement proposal bundles

## Suggested Schedule

```cron
0 * * * * cd /opt/sre-alert-agent && ./scripts/run_triage.sh >> output/logs/cron.log 2>&1
*/15 * * * * cd /opt/sre-alert-agent && python3 scripts/check_pipeline_health.py >> output/logs/health-cron.log 2>&1
*/15 * * * * cd /opt/sre-alert-agent && python3 scripts/check_queue_health.py >> output/logs/queue-cron.log 2>&1
0 23 * * * cd /opt/sre-alert-agent && python3 scripts/send_daily_summary.py >> output/logs/daily-summary.log 2>&1
```
