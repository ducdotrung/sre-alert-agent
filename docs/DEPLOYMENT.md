# Deployment

This repo can run on a single Linux host with Python, `jq`, and the `pi` CLI available.

## Suggested Layout

```text
/opt/sre-alert-agent
/etc/sre-alert-agent.env
/opt/sre-alert-agent/output
```

You can change these paths, but keeping code, env, and runtime output separate makes upgrades and backup simpler.

## 1. Install the Repo

```bash
sudo git clone <your-repo-url> /opt/sre-alert-agent
cd /opt/sre-alert-agent
```

Or install from a local checkout:

```bash
sudo INSTALL_DIR=/opt/sre-alert-agent ENV_FILE=/etc/sre-alert-agent.env ./scripts/install.sh
```

## 2. Create the Environment File

```bash
sudo cp .env.example /etc/sre-alert-agent.env
sudo chmod 600 /etc/sre-alert-agent.env
sudoedit /etc/sre-alert-agent.env
```

Minimum values:

```bash
SENTRY_BASE_URL=https://sentry.example.com
SENTRY_AUTH_TOKEN=replace-with-token
SENTRY_ORG=your-org-slug
AI_PROVIDER=azure-openai-responses
AI_MODEL=gpt-5.4
AZURE_OPENAI_API_KEY=replace-with-key
AZURE_OPENAI_BASE_URL=https://your-resource.cognitiveservices.azure.com
TEAMS_WEBHOOK_URL=https://example.invalid/webhook
SENTRY_OUTPUT_DIR=/opt/sre-alert-agent/output
SENTRY_METRICS_DIR=/opt/sre-alert-agent/output/metrics
REVIEW_WEB_BASE_URL=http://localhost:8088
```

## 3. Create Runtime Directories

```bash
sudo mkdir -p /opt/sre-alert-agent/output/{alerts,analysis,logs,metrics}
sudo chown -R "$USER:$USER" /opt/sre-alert-agent
```

## 4. Verify the Installation

```bash
cd /opt/sre-alert-agent
set -a
source /etc/sre-alert-agent.env
set +a

python3 agents/triage_agent.py --dry-run
python3 agents/sender.py --config config/agent_config.yaml --dry-run
```

## 5. Optional: Review UI Service

Example unit file:

```ini
[Unit]
Description=SRE Alert Review Web UI
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/sre-alert-agent
EnvironmentFile=-/etc/sre-alert-agent.env
ExecStart=/usr/bin/python3 /opt/sre-alert-agent/scripts/review_web.py --config config/agent_config.yaml --host 0.0.0.0 --port 8088
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

The repo includes a template at [../deploy/systemd/sentry-review-web.service.example](../deploy/systemd/sentry-review-web.service.example).

## 6. Scheduled Execution

Use either cron or a scheduler of your choice. See [CRONJOB_SETUP.md](CRONJOB_SETUP.md) for examples.

## 7. Upgrade Flow

```bash
cd /opt/sre-alert-agent
git pull
python3 agents/triage_agent.py --dry-run
python3 agents/sender.py --config config/agent_config.yaml --dry-run
```

If queue files already exist, upgrades are usually safe because the pipeline is file-based and stage artifacts remain on disk.
