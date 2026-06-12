# Host Deployment Assets

This folder contains quick-deploy assets for a single Linux host.

Current files:

- `review-web.service.example`: systemd unit for the review UI
- `sre-alert-agent.cron.example`: `/etc/cron.d` example for the triage pipeline, health check, and self-improvement jobs

## Install The Review UI Service

```bash
sudo cp deploy/systemd/review-web.service.example /etc/systemd/system/sre-alert-agent-review-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now sre-alert-agent-review-web.service
```

## Install The Scheduled Jobs

```bash
sudo cp deploy/systemd/sre-alert-agent.cron.example /etc/cron.d/sre-alert-agent
sudo chmod 644 /etc/cron.d/sre-alert-agent
sudo systemctl restart cron || sudo systemctl restart crond
```

The cron example assumes:

- repo path: `/opt/sre-alert-agent`
- Python path: `/usr/bin/python3`
- logs under `/opt/sre-alert-agent/output/logs/`

If your install path differs, edit the cron file before copying it into `/etc/cron.d/`.
