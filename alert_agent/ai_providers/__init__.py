"""AI provider plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alert_agent.core.ai_provider import AIProvider

PROVIDERS: dict[str, type[AIProvider]] = {}


def register_provider(name: str, provider_class: type[AIProvider]) -> None:
    PROVIDERS[name] = provider_class


def get_provider_class(name: str) -> type[AIProvider]:
    if name not in PROVIDERS:
        raise ValueError(f"Unknown AI provider: {name}. Available: {', '.join(sorted(PROVIDERS))}")
    return PROVIDERS[name]


from alert_agent.ai_providers.azure_litellm_provider import AzureLiteLLMProvider  # noqa: E402
from alert_agent.ai_providers.pi_provider import PiProvider  # noqa: E402

register_provider("pi", PiProvider)
register_provider("azure-openai-responses", PiProvider)
register_provider("azure-openai", PiProvider)
register_provider("azure-openai-chat", PiProvider)
register_provider("deepseek", PiProvider)
register_provider("openai", PiProvider)
register_provider("google", PiProvider)
register_provider("gemini", PiProvider)
register_provider("azure-litellm", AzureLiteLLMProvider)

__all__ = [
    "PROVIDERS",
    "register_provider",
    "get_provider_class",
    "PiProvider",
    "AzureLiteLLMProvider",
]
