# Cronjob Setup

This repo can be scheduled with cron, systemd timers, or another scheduler. Cron is the simplest option.

## Quick Deploy File

For a file-managed host setup, the repo includes:

- `deploy/systemd/sre-alert-agent.cron.example`

It is written in `/etc/cron.d` format and covers:

- triage every minute with `--minutes 2`
- pipeline health check every 5 minutes
- self-improvement every Monday at `02:15` UTC

Example install:

```bash
sudo cp deploy/systemd/sre-alert-agent.cron.example /etc/cron.d/sre-alert-agent
sudo chmod 644 /etc/cron.d/sre-alert-agent
sudo systemctl restart cron || sudo systemctl restart crond
```

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

If you installed the `/etc/cron.d` file instead of a per-user crontab, also check:

```bash
cat /etc/cron.d/sre-alert-agent
tail -f /var/log/sre-alert-agent.log
tail -f /opt/sre-alert-agent/output/logs/health-cron.log
tail -f /opt/sre-alert-agent/output/logs/self-improve-cron.log
```
