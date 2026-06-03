# Quick Start Guide: Sentry Alert Agent

Complete setup in 3 main steps: Teams channel, environment configuration, and automation.

## 1️⃣ Teams Channel Setup (5 minutes)

### Create Channel
1. Teams → Your DevOps team → Click **"..."** → **Add channel**
2. Name: **`Sentry Critical Alerts`**
3. Description: "Automated Sentry issue triage and critical alert notifications"
4. Privacy: **Standard**

### Get Webhook URL
1. In new channel → Click **"..."** → **Connectors** (or **Workflows**)
2. Find **Incoming Webhook** → **Configure**
3. Name: **Sentry Alert Agent**
4. **Copy the webhook URL** (you'll need this next)
5. Click **Done**

**📋 Full details**: See [TEAMS_SETUP.md](./TEAMS_SETUP.md)

---

## 2️⃣ Environment Configuration (5 minutes)

Create `~/.config/sre-alert-agent.env` (or any private location):

```bash
# Required: Sentry API
SENTRY_BASE_URL=https://sentry.example.com
SENTRY_AUTH_TOKEN=replace-with-token
SENTRY_ORG=replace-with-org-slug

# Required: Teams Webhook (from step 1)
TEAMS_WEBHOOK_URL=https://example.com/webhook

# Optional but recommended
SENTRY_PROJECTS=backend,frontend,api
SENTRY_CRITICAL_PRIORITIES=P0,P1
SENTRY_OUTPUT_DIR=~/sre-alert-agent/output
TEAMS_MAX_LAST_SEEN_AGE_HOURS=48
```

### Test Locally

```bash
# Test triage collection
./scripts/run_triage.sh --hours 168

# Review pending alerts
ls output/alerts/pending/

# Move approved alerts
mv output/alerts/pending/SENTRY-123.md output/alerts/approved/

# Test sending (dry-run)
python3 agents/sender.py --dry-run

# Actually send
python3 agents/sender.py
```

---

## 3️⃣ Cronjob Setup (10 minutes)

### On Your Target Workstation

```bash
# Clone repo
cd /opt
git clone <your-repo-url> sre-alert-agent

# Create directories
mkdir -p ~/sre-alert-agent/output/logs

# Copy your env file
cp /path/to/your/sre-alert-agent.env ~/.config/sre-alert-agent.env
chmod 600 ~/.config/sre-alert-agent.env
```

### Create Cron Wrapper

Save this as `/usr/local/bin/sentry-triage-cron.sh`:

```bash
#!/bin/bash
set -euo pipefail

REPO_DIR="$HOME/sre-alert-agent"
ENV_FILE="$HOME/.config/sre-alert-agent.env"
LOG_DIR="$REPO_DIR/output/logs"
LOCK_FILE="/var/run/sentry-agent.lock"

mkdir -p "$LOG_DIR"

if [ -f "$LOCK_FILE" ]; then
    echo "[$(date)] Lock file exists, exiting" >> "$LOG_DIR/cron.log"
    exit 1
fi

touch "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

echo "[$(date)] Starting triage" >> "$LOG_DIR/cron.log"

cd "$REPO_DIR"
"$REPO_DIR/scripts/run_triage.sh" --hours 4 >> "$LOG_DIR/triage-$(date +%Y%m%d).log" 2>&1
python3 "$REPO_DIR/agents/sender.py" >> "$LOG_DIR/send-$(date +%Y%m%d).log" 2>&1

echo "[$(date)] Completed" >> "$LOG_DIR/cron.log"
```

Make executable:
```bash
sudo chmod +x /usr/local/bin/sentry-triage-cron.sh
```

### Add to Crontab

```bash
crontab -e
```

Choose a schedule:

```cron
# Every 4 hours (recommended)
0 */4 * * * /usr/local/bin/sentry-triage-cron.sh

# Every hour during business hours (9 AM - 6 PM, Mon-Fri)
0 9-18 * * 1-5 /usr/local/bin/sentry-triage-cron.sh

# Every 30 minutes (aggressive)
*/30 * * * * /usr/local/bin/sentry-triage-cron.sh
```

**📋 Full details**: See [CRONJOB_SETUP.md](./CRONJOB_SETUP.md)

---

## 🎯 Recommended Workflow

### Initial Setup Phase
1. **Run manually** with 7-day lookback to understand your alert landscape
2. **Review all pending alerts** - identify noise vs. real issues
3. **Create ignore rules** for accepted noise in your private ignore file
4. **Manually approve** and send only P0/P1 alerts

### Production Phase
1. **Cron runs every 4 hours** checking the last 4 hours of issues
2. **Review pending alerts** daily or after each cron run
3. **Move approved** alerts to approved folder
4. **Next cron run** automatically sends approved alerts to Teams
5. **Refine ignore rules** as needed

### Optional: Auto-Approval (After Tuning)
Once you trust your ignore rules, you can auto-approve P0 alerts by adding this to the cron wrapper before the send step:

```bash
# Auto-approve P0 alerts only
for alert in "$REPO_DIR"/output/alerts/pending/*.md; do
    if [ -f "$alert" ] && grep -q "priority: P0" "$alert"; then
        mv "$alert" "$REPO_DIR/output/alerts/approved/"
    fi
done
```

---

## 📊 Monitoring

```bash
# Watch cron execution
tail -f "$LOG_DIR/cron.log"

# See detailed triage output
tail -f "$LOG_DIR/triage-$(date +%Y%m%d).log"

# Check pending alerts
ls -la "$REPO_DIR/output/alerts/pending/"

# Check what was sent
ls -la "$REPO_DIR/output/alerts/sent/"
```

---

## 🔧 Troubleshooting

| Problem | Solution |
|---------|----------|
| No alerts in Teams | Check webhook URL, verify approved files exist, check send logs |
| Too many alerts | Add ignore rules, increase `TEAMS_MAX_LAST_SEEN_AGE_HOURS` |
| Cron not running | Check `systemctl status cron`, verify crontab with `crontab -l` |
| Permission errors | `sudo chown -R $USER:$USER "$REPO_DIR/output"` |
| Duplicate sends | Check for lock file `/var/run/sentry-agent.lock`, may indicate concurrent runs |

---

## 📚 Additional Resources

- [TEAMS_SETUP.md](./TEAMS_SETUP.md) - Detailed Teams configuration
- [CRONJOB_SETUP.md](./CRONJOB_SETUP.md) - Advanced cron setup and maintenance
- [../README.md](../README.md) - Main project README
- [../sentry-triage-playbooks/SKILL.md](../sentry-triage-playbooks/SKILL.md) - Skill documentation

---

## 🔐 Security Checklist

- ✅ Webhook URL stored in private env file (not in repo)
- ✅ Env file permissions set to `600` (only owner can read)
- ✅ Sentry auth token stored securely
- ✅ Output directory not world-readable
- ✅ Logs rotated to prevent disk fill
- ✅ Lock file prevents concurrent runs
