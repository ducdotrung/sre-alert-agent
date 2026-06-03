# `sre-alert-agent`

Reusable Sentry alert agent skill and scripts for DevOps alert review with automated Teams notifications.

## Quick Start

New to this project? Start here:

- **[Quick Start Guide](docs/QUICK_START.md)** - Complete setup in 15 minutes
- **[Teams Setup](docs/TEAMS_SETUP.md)** - Create Teams channel and webhook
- **[Cronjob Setup](docs/CRONJOB_SETUP.md)** - Automated monitoring on a dedicated workstation

## Contents

- `agents/`: triage, review, recommendation, and sender agents.
- `output/`: local runtime output placeholder. Generated reports, snapshots, alert queues, logs, and receipts are ignored by Git.
- `docs/`: Setup guides and documentation.

## Runtime Configuration

Keep real credentials in a private env file outside the repo or in your secret manager.

```bash
SENTRY_BASE_URL=https://sentry.example.com
SENTRY_AUTH_TOKEN=replace-with-token
SENTRY_ORG=replace-with-org-slug
SENTRY_PROJECTS=backend,ai-service
SENTRY_QUERY=is:unresolved
SENTRY_OUTPUT_DIR=/path/to/output
SENTRY_CRITICAL_PRIORITIES=P0
SENTRY_IGNORE_FILE=/path/to/private/sentry-ignore.json
TEAMS_WEBHOOK_URL=https://example.com/teams-webhook
```

## Run

```bash
./scripts/run_triage.sh --hours 168
```

Approve alerts by moving selected files from `alerts/pending/` to `alerts/approved/`, then send:

```bash
python3 agents/sender.py --dry-run
python3 agents/sender.py
```
