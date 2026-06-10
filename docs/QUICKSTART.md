# Quick Start

Use this to validate the repo locally.

## 1. Prepare `.env`

Copy the example file and fill in the providers you want to use:

```bash
cp .env.example .env
```

Minimum variables:

```bash
SENTRY_BASE_URL=https://sentry.example.com
SENTRY_AUTH_TOKEN=replace-with-token
SENTRY_ORG=your-org-slug

AI_PROVIDER=azure-openai-responses
AI_MODEL=gpt-5.4
AZURE_OPENAI_API_KEY=replace-with-key
AZURE_OPENAI_BASE_URL=https://your-resource.cognitiveservices.azure.com

TEAMS_WEBHOOK_URL=https://example.invalid/webhook
```

If you only want to exercise the pipeline locally, keep sender commands in dry-run mode.

## 2. Validate Dependencies

```bash
python3 --version
pi --print "test"
```

If you are using the Azure helper flow, you can also run:

```bash
./scripts/test_azure_pi.sh
```

## 3. Run Triage

```bash
python3 agents/triage_agent.py --dry-run
./scripts/run_triage.sh --minutes 70
```

The pipeline writes artifacts to `output/alerts/` and logs to `output/logs/`.

## 4. Review Pending Alerts

```bash
python3 scripts/review_queue.py list
python3 scripts/review_queue.py show SENTRY-123
python3 scripts/review_queue.py approve SENTRY-123 --reviewer reviewer-1 --note "Validated impact"
```

You can also use the local review UI:

```bash
python3 scripts/review_web.py --host 0.0.0.0 --port 8088
```

## 5. Generate and Preview Notifications

```bash
python3 agents/recommendation_agent.py --config config/agent_config.yaml
python3 agents/sender.py --config config/agent_config.yaml --dry-run
```

## 6. Tune Rules With Real Data

```bash
python3 scripts/analyze_sentry_corpus.py --days 14 --limit 3000
```

This writes a timestamped report under `output/analysis/`.

## Next

- [DEPLOYMENT.md](DEPLOYMENT.md): generic deployment steps
- [ARCHITECTURE.md](ARCHITECTURE.md): system design
- [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md): day-2 operations
