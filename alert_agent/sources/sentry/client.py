"""Compatibility import surface for the Sentry source package."""

from alert_agent.core.sentry_client import (
    SentryClient,
    discover_org,
    fetch_issues,
    fetch_issues_paginated,
    resolve_projects,
)

__all__ = [
    "SentryClient",
    "discover_org",
    "fetch_issues",
    "fetch_issues_paginated",
    "resolve_projects",
]
