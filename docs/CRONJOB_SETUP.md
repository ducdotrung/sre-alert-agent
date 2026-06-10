# Cronjob Setup

This repo can be scheduled with cron, systemd timers, or another scheduler. Cron is the simplest option.

## Example Wrapper

Save this as `/usr/local/bin/sre-alert-agent-cron.sh`:

```bash
#!/bin/bash
set -euo pipefail

REPO_DIR="/opt/sre-alert-agent"
ENV_FILE="/etc/sre-alert-agent.env"
LOG_DIR="$REPO_DIR/output/logs"

mkdir -p "$LOG_DIR"

cd "$REPO_DIR"
set -a
source "$ENV_FILE"
set +a

./scripts/run_triage.sh --hours 4 >> "$LOG_DIR/triage-$(date +%Y%m%d).log" 2>&1
```

Make it executable:

```bash
sudo chmod +x /usr/local/bin/sre-alert-agent-cron.sh
```

## Example Schedules

```cron
# Every 4 hours
0 */4 * * * /usr/local/bin/sre-alert-agent-cron.sh

# Hourly during business hours
0 9-18 * * 1-5 /usr/local/bin/sre-alert-agent-cron.sh

# Every 30 minutes
*/30 * * * * /usr/local/bin/sre-alert-agent-cron.sh
```

## Optional Monitoring Jobs

```cron
*/15 * * * * cd /opt/sre-alert-agent && python3 scripts/check_pipeline_health.py >> output/logs/health-cron.log 2>&1
*/15 * * * * cd /opt/sre-alert-agent && python3 scripts/check_queue_health.py >> output/logs/queue-cron.log 2>&1
0 23 * * * cd /opt/sre-alert-agent && python3 scripts/send_daily_summary.py >> output/logs/daily-summary.log 2>&1
```

## Verification

```bash
crontab -l
tail -f /opt/sre-alert-agent/output/logs/cron.log
```
