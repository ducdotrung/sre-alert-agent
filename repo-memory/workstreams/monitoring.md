# Workstream: Monitoring

Last updated: 2026-07-08

## Goal

Keep workstation operations visible without adding a database or backend service.

## Durable References

- `docs/WORKSTATION_MONITORING.md`
- `docs/OPERATIONS_RUNBOOK.md`
- monitoring scripts in `scripts/`

## Implemented

- AI usage ledger
- cost reporting
- budget alerts
- pipeline health checks
- queue health checks
- daily summary
- static dashboard
- budget enforcement modes
- daily summary now distinguishes `sent_today` from `sent_archive`
- Kubernetes packaging now includes budget-monitor CronJobs in both `deploy/aks/` and `deploy/eks/`

## Current Assessment

For the current scope, this workstream is effectively complete.

New monitoring work should be treated as a fresh enhancement, not as unfinished baseline roadmap work.
