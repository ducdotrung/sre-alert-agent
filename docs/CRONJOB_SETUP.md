# Cronjob Setup for Sentry Alert Agent

## Overview

This guide helps you set up automated Sentry issue triage on a dedicated workstation or server that runs continuously.

## Prerequisites

1. A Linux/Unix workstation or server (can be WSL, VM, or dedicated server)
2. Python 3.8 or later installed
3. Git installed
4. Network access to Sentry and Teams webhook endpoint
5. A private location for storing credentials

## Step 1: Clone the Repository on the Target Workstation

```bash
# SSH into your target workstation
ssh user@your-workstation

# Clone the repository
cd /opt  # or wherever you want to store it
git clone <your-repo-url> sre-alert-agent
# or if using a remote repo:
# git clone <your-repo-url> sre-alert-agent

cd sre-alert-agent
```

## Step 2: Create Private Environment File

Create a secure directory for credentials:

```bash
# Create a private directory (not in the repo)
mkdir -p ~/.config

# Create the environment file
nano ~/.config/sre-alert-agent.env
```

Add your configuration:

```bash
# Sentry Configuration
SENTRY_BASE_URL=https://sentry.example.com
SENTRY_AUTH_TOKEN=replace-with-token
SENTRY_ORG=replace-with-org-slug
SENTRY_PROJECTS=backend,ai-service,frontend
SENTRY_QUERY=is:unresolved
SENTRY_ENVIRONMENT=production
SENTRY_OUTPUT_DIR=/var/log
SENTRY_CRITICAL_PRIORITIES=P0,P1
SENTRY_LIMIT=100

# Teams Configuration
TEAMS_WEBHOOK_URL=https://example.com/webhook
TEAMS_TIMEOUT=15
TEAMS_MAX_LAST_SEEN_AGE_HOURS=48

# Optional
SENTRY_IGNORE_FILE=/opt/sre-alert-agent/config/ignore_rules.json
```

Secure the file:

```bash
chmod 600 ~/.config/sre-alert-agent.env
```

## Step 3: Create Output Directory

```bash
mkdir -p /var/log
```

## Step 4: Test the Scripts Manually

Before setting up cron, test that everything works:

```bash
cd /opt/sre-alert-agent

# Test triage collection (20-minute lookback)
./scripts/run_triage.sh --minutes 20

# Check the output
ls -la /var/log/alerts/pending/

# If you have pending alerts, they need manual approval:
# Review them and move approved ones:
# mv /var/log/alerts/pending/SENTRY-123.md /var/log/alerts/approved/

# Test sending (dry-run first)
python3 agents/sender.py --dry-run

# Actually send if dry-run looks good
python3 agents/sender.py
```

## Step 5: Create Cron Wrapper Script

Create a wrapper script with better logging:

```bash
sudo nano /usr/local/bin/sentry-triage-cron.sh
```

```bash
#!/bin/bash
set -euo pipefail

# Configuration
REPO_DIR="/opt/sre-alert-agent"
ENV_FILE="/etc/sentry-agent/config.env"
LOG_DIR="/var/log"
LOCK_FILE="/var/run/sentry-agent.lock"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Function to log with timestamp
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_DIR/cron.log"
}

# Prevent concurrent runs
if [ -f "$LOCK_FILE" ]; then
    log "ERROR: Lock file exists. Previous run may still be running."
    exit 1
fi

touch "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

log "=== Starting Sentry Triage ==="

# Pull latest changes (optional, if you want auto-updates)
cd "$REPO_DIR"

# Run triage (check last 20 minutes for frequent monitoring)
log "Running sentry triage..."
if ./scripts/run_triage.sh --minutes 20 >> "$LOG_DIR/alert-agent.log" 2>&1; then
    log "Triage completed successfully"
else
    log "ERROR: Triage failed with exit code $?"
    exit 1
fi

# Send approved alerts (this requires manual approval first)
log "Sending approved alerts..."
if python3 agents/sender.py >> "$LOG_DIR/alert-agent.log" 2>&1; then
    log "Send completed successfully"
else
    log "ERROR: Send failed with exit code $?"
    exit 1
fi

log "=== Sentry Triage Complete ==="
```

Make it executable:

```bash
sudo chmod +x /usr/local/bin/sentry-triage-cron.sh
```

## Step 6: Set Up Crontab

Edit your crontab:

```bash
crontab -e
```

Add one of these schedules based on your needs:

### Option A: Run every 15 minutes (recommended for production monitoring)
```cron
# Sentry Alert Triage - every 4 hours
*/15 * * * * cd /opt/sre-alert-agent && ./scripts/run_triage.sh --minutes 20 >> /var/log/alert-agent.log 2>&1
```

### Option B: Run every hour during business hours
```cron
# Sentry Alert Triage - hourly during business hours (9 AM - 6 PM, Mon-Fri)
0 9-18 * * 1-5 /usr/local/bin/sentry-triage-cron.sh
```

### Option C: Run every 30 minutes (aggressive monitoring)
```cron
# Sentry Alert Triage - every 30 minutes
*/30 * * * * /usr/local/bin/sentry-triage-cron.sh
```

### Option D: Custom schedule - twice daily at specific times
```cron
# Sentry Alert Triage - 9 AM and 5 PM daily
0 9,17 * * * /usr/local/bin/sentry-triage-cron.sh
```

## Step 7: Monitor Cron Execution

Check if cron is running:

```bash
# View cron logs
tail -f /var/log/alert-agent.log

# View detailed triage logs
tail -f /var/log/alert-agent.log

# View send logs
tail -f /var/log/alert-agent.log

# Check if lock file exists (indicates running job)
ls -la /var/run/sentry-agent.lock
```

## Step 8: Log Rotation Setup

Prevent logs from growing too large:

```bash
sudo nano /etc/logrotate.d/sentry-agent
```

```
/var/log/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0644 your-username your-username
}
```

## Important Notes

### Manual Approval Required

The default workflow requires **manual approval** before sending alerts:

1. Cron runs triage → creates `/var/log/alerts/pending/*.md`
2. **You review** pending alerts
3. **You move approved** files to `/var/log/alerts/approved/`
4. Next cron run (or manual trigger) sends approved alerts

### Auto-Approval (Use with Caution)

If you want fully automated sending without manual approval, modify the wrapper script to automatically approve P0 alerts:

```bash
# Add this between triage and send steps in the wrapper script:
# Auto-approve P0 alerts (DANGEROUS - use carefully)
for alert in /var/log/alerts/pending/*.md; do
    if [ -f "$alert" ] && grep -q "priority: P0" "$alert"; then
        mv "$alert" /var/log/alerts/approved/
        log "Auto-approved P0 alert: $(basename $alert)"
    fi
done
```

⚠️ **Warning**: Auto-approval can flood your Teams channel with false positives. Only use after tuning your ignore rules.

## Troubleshooting

### Cron job not running?
```bash
# Check cron service
sudo systemctl status cron

# Check cron logs
sudo tail -f /var/log/syslog | grep CRON

# Verify crontab
crontab -l
```

### Permission errors?
```bash
# Ensure proper ownership
sudo chown -R $USER:$USER /var/log
```

### Script failures?
```bash
# Run manually to see errors
/usr/local/bin/sentry-triage-cron.sh

# Check Python dependencies
python3 -c "import urllib.request; import json; print('OK')"
```

## Maintenance

### Update the repository
```bash
cd /opt/sre-alert-agent
git pull origin main
```

### Update ignore rules
```bash
nano /opt/sre-alert-agent/config/ignore_rules.json
```

Example ignore file:
```json
{
  "SENTRY-1234": {
    "reason": "Known issue, fix scheduled for Q3",
    "expires": "2026-09-30"
  },
  "SENTRY-5678": {
    "reason": "Third-party API intermittent noise",
    "expires": "2026-12-31"
  }
}
```

### Clean old data
```bash
# Clean sent alerts older than 90 days
find /var/log/alerts/sent -name "*.md" -mtime +90 -delete

# Clean old logs
find /var/log -name "*.log" -mtime +60 -delete
```
