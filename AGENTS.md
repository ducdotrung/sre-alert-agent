# Sentry Alert Agent System - Developer Guide

Multi-agent AI-powered system for automated Sentry alert triage and Teams notification.

## Quick Start

### 1. Setup Environment

```bash
# Copy example env file
cp .env.example .env

# Edit .env with your credentials
nano .env
```

Required variables:
- `SENTRY_BASE_URL`, `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`
- `DEEPSEEK_API_KEY` (or other AI provider)
- `TEAMS_WEBHOOK_URL`

### 2. Test AI Connection

```bash
# Test pi CLI is working
pi --print "What is 2+2?"

# Test with DeepSeek
pi --provider deepseek --print "Hello"
```

### 3. Run Agents

```bash
# Run full pipeline
./scripts/run_triage.sh

# Or run agents individually
python3 agents/triage_agent.py --config config/agent_config.yaml
python3 agents/review_agent.py --config config/agent_config.yaml
python3 agents/recommendation_agent.py --config config/agent_config.yaml
python3 agents/sender.py --config config/agent_config.yaml --dry-run
```

## Repo Memory

This repo uses `repo-memory/` as working memory for interrupted sessions and handoffs.

Read this before substantial work:

1. `repo-memory/current-state.md`
2. relevant files in `repo-memory/workstreams/`
3. latest file in `repo-memory/handoffs/`

Rules:

- treat `docs/` as durable design and reference material, not as the default source of active task state
- when `docs/` and implemented code disagree, record the mismatch in `repo-memory/`
- after meaningful work, update `repo-memory/current-state.md`, the touched workstream file, and a dated handoff note
- keep memory entries short, factual, and linked to source files instead of duplicating long docs

## Architecture

```
Sentry API → Triage Agent → Review Agent → Recommendation Agent → Sender → Teams
             (Rules + AI)   (AI)           (AI)                   (HTTP)
```

### Agent 1: Triage Agent

**Purpose**: Classify and prioritize Sentry issues

**Logic**:
1. Fetch recent issues from Sentry
2. Apply rule-based classification (keyword matching)
3. If rule confidence < 0.7 → Use AI to reclassify
4. Apply ignore rules
5. Output: `output/alerts/triage/{issue-id}.json`

**Exit codes**:
- `0` = No critical issues
- `1` = Error
- `2` = Critical issues found (triggers next agent)

### Agent 2: Review Agent

**Purpose**: Assess impact and decide whether to send

**Logic**:
1. Read triage results (P0/P1 only)
2. AI analyzes: user impact, business impact, urgency
3. AI decides: send, hold, or needs review
4. If P0 + confidence > 0.85 → Auto-approve
5. Else → Move to `pending/` for human review

**Output**:
- Auto-approved: `output/alerts/approved/{issue-id}.json`
- Needs review: `output/alerts/pending/{issue-id}.json`

**Exit codes**:
- `0` = Nothing auto-approved
- `1` = Error
- `2` = Issues approved (triggers next agent)

### Agent 3: Recommendation Agent

**Purpose**: Generate actionable recommendations

**Logic**:
1. Read approved issues
2. AI generates detailed markdown with:
   - Executive summary
   - Immediate action (with commands)
   - Root cause hypothesis
   - Investigation steps
3. Output: `output/alerts/recommendations/{issue-id}.md`

**Exit codes**:
- `0` = No recommendations
- `1` = Error
- `2` = Recommendations generated (triggers sender)

### Sender

**Purpose**: Send to Microsoft Teams

**Logic**:
1. Read recommendation markdown files
2. Parse front matter + extract key sections
3. Build Teams MessageCard JSON
4. POST to webhook
5. Move to `sent/` + create receipt

## Configuration Files

### `config/agent_config.yaml`

Main configuration for all agents. Uses environment variable substitution: `${VAR_NAME}` or `${VAR_NAME:default}`.

Edit to:
- Adjust confidence thresholds
- Enable/disable AI
- Change lookback windows
- Set auto-approval rules

### `config/classification_rules.yaml`

Keyword-to-class mappings for rule-based classification.

Edit to:
- Add new keywords for better classification
- Adjust keyword priorities

### `config/priority_thresholds.yaml`

Count/user thresholds for priority assignment.

Edit to:
- Tune P0/P1/P2/P3 thresholds
- Adjust per-class priorities

### `config/ignore_rules.json`

Issues to suppress (known noise).

Edit to:
- Add ignore rules for specific issues
- Suppress low-value alerts by class/title
- Set expiry dates for temporary ignores

Example:
```json
{
  "rules": [
    {
      "id": "ignore-client-disconnect",
      "enabled": true,
      "class": "client-disconnect",
      "max_count": 100,
      "reason": "Accepted noise",
      "expires": "2026-12-31"
    }
  ]
}
```

## Manual Review Workflow

Issues in `output/alerts/pending/` need human review.

### Review an Issue

```bash
# List pending issues
python3 scripts/review_queue.py list

# View one issue
python3 scripts/review_queue.py show SENTRY-123
```

### Approve for Sending

```bash
# Approve in a structured way
python3 scripts/review_queue.py approve SENTRY-123 --reviewer your-name --note "Confirmed impact"

# Then generate/send from the approved queue
python3 scripts/review_queue.py dispatch --send
```

### Ignore (Suppress)

```bash
# Move to ignored/ with an audit record
python3 scripts/review_queue.py ignore SENTRY-123 --reviewer your-name --note "Known noise"

# Add to ignore_rules.json
nano config/ignore_rules.json
```

### Reject (Do Not Send)

```bash
python3 scripts/review_queue.py reject SENTRY-123 --reviewer your-name --note "Not actionable enough for alerting"
```

Add rule:
```json
{
  "id": "ignore-sentry-123",
  "enabled": true,
  "issue_id": "SENTRY-123",
  "reason": "Known issue, fix scheduled Q3",
  "expires": "2026-09-30"
}
```

## Prompts (AI Instructions)

Located in `prompts/` directory. Edit to customize AI behavior.

### `prompts/triage_reclassify.md`

Used by Triage Agent when rule confidence is low.

Edit to:
- Add more classification examples
- Adjust classification criteria
- Change response format

### `prompts/review_decision.md`

Used by Review Agent to decide send/hold/review.

Edit to:
- Adjust auto-send criteria
- Add business context (SLA, revenue thresholds)
- Customize impact assessment

### `prompts/recommendation_generate.md`

Used by Recommendation Agent to generate markdown.

Edit to:
- Adjust tone (more/less formal)
- Add company-specific runbooks
- Include standard commands/procedures

## Output Directory Structure

```
output/
├── alerts/
│   ├── triage/          # Agent 1 output (JSON)
│   ├── reviewed/        # Agent 2 output (JSON)
│   ├── pending/         # Needs human review (JSON)
│   ├── approved/        # Auto-approved (JSON)
│   ├── rejected/        # Human-reviewed, do not send (JSON)
│   ├── recommendations/ # Agent 3 output (Markdown)
│   ├── sent/            # Sent to Teams (Markdown + receipts)
│   └── ignored/         # Manually suppressed (JSON)
└── logs/                # Agent execution logs
```

## Cron Setup

### Hourly Execution

```cron
# Run every hour
0 * * * * cd /opt/sre-alert-agent && ./scripts/run_triage.sh >> output/logs/cron.log 2>&1
```

### Custom Schedule

```cron
# Every 4 hours
0 */4 * * * cd /opt/sre-alert-agent && ./scripts/run_triage.sh

# Business hours only (9 AM - 6 PM, Mon-Fri)
0 9-18 * * 1-5 cd /opt/sre-alert-agent && ./scripts/run_triage.sh
```

## Troubleshooting

### Issue: AI client fails

```
ERROR: pi CLI failed (exit 1): ...
```

**Fix**:
1. Test `pi` command: `pi --print "test"`
2. Check API key: `echo $DEEPSEEK_API_KEY`
3. Try different provider: `pi --provider google --print "test"`

### Issue: No issues triaged

```
INFO: Fetched 0 issues
```

**Fix**:
1. Check Sentry credentials: `curl -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" $SENTRY_BASE_URL/api/0/`
2. Verify organization slug: `SENTRY_ORG=correct-slug`
3. Check query syntax: `SENTRY_QUERY=is:unresolved`

### Issue: Webhook fails

```
ERROR: Teams webhook HTTP 400: ...
```

**Fix**:
1. Test webhook: `curl -X POST -H "Content-Type: application/json" -d '{"text":"test"}' "$TEAMS_WEBHOOK_URL"`
2. Check webhook is still active in Teams (Connectors)
3. Verify URL is complete (often truncated when copying)

### Issue: Everything goes to pending

```
INFO: 0 auto-approved, 10 pending
```

**Fix**:
1. Check confidence threshold: Lower `auto_send_confidence_threshold` in config
2. Review AI responses: Check `output/alerts/reviewed/*.json` for low confidence scores
3. Adjust prompts to be less conservative

## Development

### Add New Classification Class

1. Edit `config/classification_rules.yaml`:
```yaml
custom-class:
  keywords:
    - "custom-keyword"
  priority: high
```

2. Edit `config/priority_thresholds.yaml`:
```yaml
class_thresholds:
  custom-class:
    P0: { count: 500, users: 20 }
    P1: { count: 100, users: 10 }
```

3. Update `prompts/triage_reclassify.md` to include new class in options

### Test Agent Individually

```bash
# Triage only (dry-run, no AI)
python3 agents/triage_agent.py --dry-run

# Review only (on existing triage results)
python3 agents/review_agent.py

# Recommendations only
python3 agents/recommendation_agent.py

# Sender dry-run (print messages, don't send)
python3 agents/sender.py --dry-run
```

### View Logs

```bash
# Orchestrator log
tail -f output/logs/orchestrator.log

# Agent-specific logs
tail -f output/logs/triage-$(date +%Y%m%d).log
tail -f output/logs/review-$(date +%Y%m%d).log
tail -f output/logs/recommendation-$(date +%Y%m%d).log
tail -f output/logs/sender-$(date +%Y%m%d).log
```

## Cost Estimation

Assuming 720 runs/month (hourly), 10 P0/P1 issues per run:

- **DeepSeek**: ~$2-5/month
- **OpenAI GPT-4**: ~$20-30/month
- **Google Gemini**: Free tier available

## GitOps Best Practices

All configuration is in Git:
- Commit changes to `config/` and `prompts/`
- Never commit `.env` or `output/` directory
- Use pull requests for config changes
- Test changes locally before merging

## Support

- Documentation: `docs/` directory
- Architecture: `docs/ARCHITECTURE.md`
- Comparison examples: `docs/COMPARISON_EXAMPLE.md`
- Issues: Create GitHub issue

## TODO (Future Enhancements)

- [ ] Web UI for pending review
- [ ] Incident history database (similar past incidents)
- [ ] Feedback loop ("was this helpful?")
- [ ] Multi-tenant support (multiple Teams channels)
