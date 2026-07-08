#!/usr/bin/env python3
"""Factory for creating AI provider instances."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alert_agent.ai_providers import get_provider_class
from alert_agent.core.ai_provider import AIProvider


def create_ai_provider(
    provider: str,
    model: str | None = None,
    api_key: str | None = None,
    metrics_dir: Path | str | None = None,
    agent_name: str | None = None,
    run_id: str | None = None,
    pricing: dict[str, Any] | None = None,
    **kwargs: Any,
) -> AIProvider:
    provider_class = get_provider_class(provider)
    return provider_class(
        provider=provider,
        model=model,
        api_key=api_key,
        metrics_dir=metrics_dir,
        agent_name=agent_name,
        run_id=run_id,
        pricing=pricing,
        **kwargs,
    )


create_ai_client = create_ai_provider
