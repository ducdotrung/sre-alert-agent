"""Sentry plugin wiring for the shared pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alert_agent.core.config_loader import load_policy_pack
from alert_agent.core.plugin import PipelineContext, PolicyPack
from alert_agent.sources.sentry.client import (
    SentryClient,
    discover_org,
    fetch_issues,
    resolve_projects,
)
from alert_agent.sources.sentry.normalizer import normalize_sentry_issue


class SentrySourcePlugin:
    name = "sentry"

    def fetch_alerts(self, context: PipelineContext, **kwargs: Any) -> list[dict[str, Any]]:
        source_config = context.source_config
        client = SentryClient(
            str(source_config["base_url"]),
            str(source_config["auth_token"]),
        )
        org = source_config.get("organization") or discover_org(client)
        stats_period = str(kwargs.get("stats_period") or source_config.get("stats_period") or "1h")

        project_specs = None
        if source_config.get("projects"):
            project_names = [p.strip() for p in str(source_config["projects"]).split(",") if p.strip()]
            if project_names:
                project_specs = resolve_projects(client, org, project_names)

        return fetch_issues(
            client,
            org=org,
            stats_period=stats_period,
            query=str(source_config.get("query") or "is:unresolved"),
            projects=project_specs,
            environment=source_config.get("environment"),
            limit=int(source_config.get("limit", 100)),
        )

    def normalize_alert(self, raw_alert: dict[str, Any], context: PipelineContext):
        return normalize_sentry_issue(raw_alert)

    def load_policy_pack(self, context: PipelineContext) -> PolicyPack:
        source_config = context.source_config
        pack = load_policy_pack(str(source_config.get("policy_pack") or "sentry-default"), context.config_file)
        prompts = {
            name: context.repo_root / str(path)
            for name, path in dict(pack.get("prompts", {}) or {}).items()
        }
        return PolicyPack(
            name=str(pack.get("name") or source_config.get("policy_pack") or "sentry-default"),
            classification_rules=context.repo_root / str(pack["classification_rules"]),
            priority_thresholds=context.repo_root / str(pack["priority_thresholds"]),
            ignore_rules=context.repo_root / str(pack["ignore_rules"]),
            prompts=prompts,
        )
