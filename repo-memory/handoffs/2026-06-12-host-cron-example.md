# Handoff - 2026-06-12 Host Cron Example

## Session Summary

- Added a quick-deploy cron example for local server installs under `deploy/systemd/`.
- Kept it in `/etc/cron.d` format so it can be managed as a file rather than a manual per-user crontab.

## Added

- `deploy/systemd/sre-alert-agent.cron.example`
- `deploy/systemd/README.md`

## Schedule Covered

- every minute: `./scripts/run_triage.sh --minutes 2`
- every 5 minutes: `python3 scripts/check_pipeline_health.py`
- every Monday at `02:15` UTC: `./scripts/run_self_improve.sh`

## Notes

- Uses `PATH=/usr/local/bin:/usr/bin:/bin`
- Uses `/opt/sre-alert-agent` instead of any environment-specific repo path
- Sends triage output to `/var/log/sre-alert-agent.log`
- Sends health and self-improve output to `output/logs/`
