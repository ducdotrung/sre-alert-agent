# Microsoft Teams Setup

## 1. Create an Incoming Webhook

1. Open the Teams channel that should receive alerts.
2. Add an Incoming Webhook or the equivalent workflow action available in your tenant.
3. Copy the webhook URL.

## 2. Add the Webhook to `.env`

```bash
TEAMS_WEBHOOK_URL=https://example.invalid/webhook
TEAMS_TIMEOUT=15
TEAMS_MAX_LAST_SEEN_AGE_HOURS=48
```

Optional monitoring and pending-review channels can use separate webhooks:

```bash
TEAMS_MONITOR_WEBHOOK_URL=https://example.invalid/monitor-webhook
TEAMS_PENDING_REVIEW_WEBHOOK_URL=https://example.invalid/pending-webhook
```

## 3. Dry-Run the Sender

```bash
python3 agents/sender.py --config config/agent_config.yaml --dry-run
```

## 4. Send for Real

```bash
python3 agents/sender.py --config config/agent_config.yaml
```

## Notes

- treat webhook URLs as secrets
- keep them in `.env` or a secret manager, not in Git
- rotate them if they leak or are shared broadly
