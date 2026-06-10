"""Compatibility aliases for legacy ``shared.*`` and ``agents.shared.*`` imports."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


_MODULE_ALIASES = {
    "ai_client": "alert_agent.core.ai_client",
    "config_loader": "alert_agent.core.config_loader",
    "health_monitor": "alert_agent.core.health_monitor",
    "manual_review": "alert_agent.core.manual_review",
    "sentry_client": "alert_agent.core.sentry_client",
    "teams": "alert_agent.core.teams",
    "usage_metrics": "alert_agent.core.usage_metrics",
}


def _register_aliases() -> None:
    package_name = __name__
    for alias, target in _MODULE_ALIASES.items():
        module = importlib.import_module(target)
        setattr(sys.modules[package_name], alias, module)
        sys.modules[f"{package_name}.{alias}"] = module

        # Support ``from shared.foo import ...`` when ``agents/`` is on sys.path.
        if package_name == "shared":
            sys.modules[f"shared.{alias}"] = module


_register_aliases()

__all__ = sorted(_MODULE_ALIASES)
