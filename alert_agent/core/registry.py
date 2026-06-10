"""Built-in source plugin registry."""

from __future__ import annotations

from typing import Any

from .plugin import SourcePlugin


def get_source_plugin(source_name: str) -> SourcePlugin:
    """Return the built-in plugin for a source."""
    normalized = str(source_name).strip().lower()
    if normalized == "sentry":
        from alert_agent.sources.sentry.plugin import SentrySourcePlugin

        return SentrySourcePlugin()
    raise KeyError(f"Unknown source plugin: {source_name}")
