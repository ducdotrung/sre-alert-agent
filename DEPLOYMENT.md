# Deployment Guide

Quick guide to deploy `sre-alert-agent` for POC and production.

## POC Deployment (Local Machine)

### 1. Prerequisites

```bash
# Check Python 3
python3 --version  # Should be 3.8+

# Check pi CLI
pi --version

# If pi not installed:
npm install -g @lastmile-ai/pi-cli
```

### 2. Configure Environment

```bash
cd /opt/sre-alert-agent

# Copy example config
cp .env.example .env

# Edit with your credentials
nano .env
```

**Required settings**:
```bash
# Sentry
SENTRY_BASE_URL=https://sentry.example.com
SENTRY_AUTH_TOKEN=replace-with-token
SENTRY_ORG=replace-with-org-slug
SENTRY_PROJECTS=backend,frontend  # Optional, comma-separated

# AI (DeepSeek)
DEEPSEEK_API_KEY=replace-with-api-key

# Teams (for sending alerts)
TEAMS_WEBHOOK_URL=https://example.com/webhook
```

### 3. Run POC Test

```bash
# Run automated test
./scripts/test_poc.sh
```

This will:
- Test Sentry API connection
- Test AI (DeepSeek) connection
- Run triage on last 24 hours
- Run review on critical issues
- Generate recommendations
- Show dry-run Teams message

**Expected output**:
```
[✓] Sentry API connection successful
[✓] pi CLI with DeepSeek is working
[✓] Triage agent completed: 15 issues processed
[✓] Review agent completed: 2 approved, 1 pending
[✓] Recommendation agent completed: 2 recommendations generated
[✓] Sender test completed (dry-run)
```

### 4. Review Results

```bash
# View triaged issues
ls -la output/alerts/triage/

# View approved issues (auto-approved by AI)
cat output/alerts/approved/SENTRY-123.json | jq

# View generated recommendations
cat output/alerts/recommendations/SENTRY-123.md

# View pending issues (need manual review)
ls -la output/alerts/pending/
```

### 5. Test Actual Teams Sending

```bash
# Send one recommendation (without dry-run)
python3 agents/sender.py

# Check Teams channel for message
```

---

## Production Deployment

```bash
# SSH to workstation
ssh user@workstation

# Clone from git
cd /opt
sudo git clone <your-repo-url> sre-alert-agent

# Or use copied files
sudo mv /tmp/sre-alert-agent /opt/

# Run install script
cd /opt/sre-alert-agent
sudo ./scripts/install.sh
```

The install script will:
1. Check prerequisites (Python, pi CLI)
2. Create directories under the repository output path
3. Copy environment template to `~/.config/sre-alert-agent.env`
4. Set permissions
5. Test installation

**Configure environment**:

```bash
nano ~/.config/sre-alert-agent.env
```

Add your credentials (same as POC).

### Set Up Cron

```bash
# Edit crontab
crontab -e

# Add hourly execution
0 * * * * cd /opt/sre-alert-agent && ./scripts/run_triage.sh --minutes 20 >> /var/log/alert-agent.log 2>&1

# Or every 4 hours
0 */4 * * * cd /opt/sre-alert-agent && ./scripts/run_triage.sh --minutes 20 >> /var/log/alert-agent.log 2>&1
```

**Alternative: systemd timer** (more robust):

```bash
# Create service file
sudo nano /etc/systemd/system/sentry-alert-agent.service
```

```ini
[Unit]
Description=Sentry Alert Agent
After=network.target

[Service]
Type=oneshot
User=your-user
WorkingDirectory=/opt/sre-alert-agent
EnvironmentFile=/path/to/private/sre-alert-agent.env
ExecStart=/opt/sre-alert-agent/scripts/run_triage.sh
StandardOutput=append:./output/logs/service.log
StandardError=append:./output/logs/service.log
```

```bash
# Create timer file
sudo nano /etc/systemd/system/sentry-alert-agent.timer
```

```ini
[Unit]
Description=Sentry Alert Agent Timer

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable sentry-alert-agent.timer
sudo systemctl start sentry-alert-agent.timer

# Check status
sudo systemctl status sentry-alert-agent.timer
sudo systemctl list-timers | grep sentry
```

---

## Monitoring & Maintenance

### Check Logs

```bash
# Orchestrator log
tail -f ./output/logs/cron.log

# Agent logs
tail -f ./output/logs/triage-$(date +%Y%m%d).log
tail -f ./output/logs/review-$(date +%Y%m%d).log
```

### Check Output

```bash
# Count pending reviews
ls ./output/alerts/pending/ | wc -l

# Recent sent alerts
ls -lt ./output/alerts/sent/ | head -10
```

### Manual Review Workflow

```bash
# View pending issue
cat ./output/alerts/pending/SENTRY-123.json | jq

# Approve for sending
mv ./output/alerts/pending/SENTRY-123.json \
   ./output/alerts/approved/

# Run recommendation + send
cd /opt/sre-alert-agent
python3 agents/recommendation_agent.py
python3 agents/sender.py

# Or ignore
mv ./output/alerts/pending/SENTRY-123.json \
   ./output/alerts/ignored/
```

### Update Configuration

```bash
# Edit ignore rules
nano /opt/sre-alert-agent/config/ignore_rules.json

# Commit to git
cd /opt/sre-alert-agent
git add config/ignore_rules.json
git commit -m "Add ignore rule for SENTRY-123"
# Or on other workstation:
git pull
```

---

## Troubleshooting

### Issue: No issues triaged

```bash
# Test Sentry connection
source ~/.config/sre-alert-agent.env
curl -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
     "$SENTRY_BASE_URL/api/0/"

# Check organization
curl -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
     "$SENTRY_BASE_URL/api/0/organizations/"
```

### Issue: AI calls failing

```bash
# Test pi CLI
pi --provider deepseek --print "test"

# Check API key
echo $DEEPSEEK_API_KEY

# Try different provider
export AI_PROVIDER=google
export GOOGLE_API_KEY=your-google-key
```

### Issue: Cron not running

```bash
# Check cron service
sudo systemctl status cron

# Check cron logs
sudo tail /var/log/syslog | grep CRON

# Verify crontab
crontab -l

# Test manually
cd ~/sre-alert-agent
./scripts/run_triage.sh
```

### Issue: Permissions errors

```bash
# Fix ownership
sudo chown -R $USER:$USER /opt/sre-alert-agent

# Fix env file permissions
sudo chmod 600 ~/.config/sre-alert-agent.env
```

---

## Rollback / Uninstall

### Stop cron

```bash
# Remove from crontab
crontab -e
# Delete the sentry-alert-agent line

# Or stop systemd timer
sudo systemctl stop sentry-alert-agent.timer
sudo systemctl disable sentry-alert-agent.timer
```

### Remove files

```bash
# Remove installation
sudo rm -rf /opt/sre-alert-agent

# Remove data (CAUTION: includes sent alerts)
rm -rf /opt/sre-alert-agent/output

# Remove logs
rm -rf /opt/sre-alert-agent/output/logs

# Remove env file
rm -f ~/.config/sre-alert-agent.env
```

---

## Production Checklist

Before going to production:

- [ ] POC tested successfully on local machine
- [ ] Sentry API credentials verified
- [ ] DeepSeek API key tested
- [ ] Teams webhook tested (received test message)
- [ ] Ignore rules configured for known noise
- [ ] Confidence threshold tuned (default: 0.85)
- [ ] Cron schedule decided (hourly recommended)
- [ ] Log rotation configured
- [ ] Team notified about new Teams channel
- [ ] Runbook added to wiki/confluence
- [ ] On-call rotation knows how to review pending alerts

---

## Getting Help

- Documentation: `docs/` directory
- Architecture: `docs/ARCHITECTURE.md`
- Developer guide: `AGENT_README.md`
- Comparison examples: `docs/COMPARISON_EXAMPLE.md`

## Cost Tracking

Monitor DeepSeek API usage:
- Expected: $2-10/month for typical usage
- Check dashboard: https://platform.deepseek.com/usage
- Set budget alerts if available

---

**Last Updated**: 2026-06-02
