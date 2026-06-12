# Workstream: Public Sanitization

Last updated: 2026-06-12

## Goal

Remove company- or person-specific identifiers so the repo can be shared publicly without leaking internal naming, URLs, or personal paths.

## Implemented

- Rewrote `README.md` to describe the repo structure and public workflow only.
- Replaced the `docs/` set with neutral project documentation focused on architecture, quick start, deployment, cron, operations, monitoring, and self-improvement.
- Removed the duplicate quick-start document and kept a single public entrypoint in `docs/QUICKSTART.md`.
- Replaced legacy repo paths with `/opt/sre-alert-agent` in examples and templates.
- Removed personal usernames, internal IP addresses, and the old repository hosting reference.
- Updated example assets such as `.env.example`, the systemd unit template, and `docs/sentry-ignore-example.json`.
- Neutralized internal-only UI wording in `scripts/review_web.py`.
- Imported another round of private-repo changes while keeping public-safe placeholders in `deploy/aks/`, `docs/PROMPT_GUIDE.md`, `README.md`, and `docs/DEPLOYMENT.md`.
- Replaced hardcoded registry, hostname, namespace, and gateway details from the private AKS manifests with generic examples.
- Added a public-safe `/etc/cron.d` example under `deploy/systemd/` using `/opt/sre-alert-agent` and generic log paths.

## Remaining Work

- Future feature work should keep public examples generic and avoid embedding environment-specific URLs or personal paths.
- If more internal history is imported later, run a repo-wide identifier scan before publishing.
- For AWS hackathon/demo use, keep examples generic and prefer `deploy/eks/` over copying any environment-specific registry, domain, or certificate values.
