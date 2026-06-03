# Quick Start - 5 Minutes

Get the Sentry Alert Agent running in 5 minutes.

## Step 1: Configure (2 min)

```bash
cd ~/sre-alert-agent

# Copy config
cp .env.example .env

# Edit these 3 required values:
nano .env
```

**Required**:
```bash
SENTRY_BASE_URL=https://sentry.example.com
SENTRY_AUTH_TOKEN=sntrys_xxxxx
DEEPSEEK_API_KEY=sk-xxxxx
```

**Optional** (for sending to Teams):
```bash
TEAMS_WEBHOOK_URL=https://example.com/webhook
```

## Step 2: Test (2 min)

```bash
# Run automated test
./scripts/test_poc.sh
```

Expected output:
```
[✓] Sentry API connection successful
[✓] pi CLI with DeepSeek is working  
[✓] Triage agent completed: X issues processed
[✓] POC test successful!
```

## Step 3: Review Results (1 min)

```bash
# See what AI found
ls output/alerts/approved/
cat output/alerts/recommendations/*.md | head -50
```

## Step 4: Send to Teams (optional)

```bash
# Dry-run first (shows message, doesn't send)
python3 agents/sender.py --dry-run

# Actually send
python3 agents/sender.py
```

Check your Teams channel!

## Next: Production Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for:
- Workstation setup
- Cron setup
- Monitoring and maintenance

## Common Issues

**"pi: command not found"**
```bash
npm install -g @lastmile-ai/pi-cli
```

**"Sentry API connection failed"**
- Check `SENTRY_BASE_URL` (include https://)
- Check `SENTRY_AUTH_TOKEN` is valid
- Test: `curl -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" $SENTRY_BASE_URL/api/0/`

**"No issues found"**
- Normal if Sentry has no recent errors
- Try longer lookback: `./scripts/run_triage.sh --hours 168`

## Architecture

```
Sentry → Triage Agent → Review Agent → Recommendation Agent → Teams
         (Rules+AI)     (AI Decision)   (AI Writeup)           
```

## Files Created

```
output/alerts/
├── triage/          ← All issues classified
├── approved/        ← Auto-approved (confidence >85%)
├── pending/         ← Needs your review
├── recommendations/ ← AI-generated writeups
└── sent/            ← Delivered to Teams
```

## Help

- Full docs: [AGENT_README.md](AGENT_README.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Deployment: [DEPLOYMENT.md](DEPLOYMENT.md)
