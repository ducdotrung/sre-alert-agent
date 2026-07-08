#!/usr/bin/env python3
"""Pi CLI AI provider implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alert_agent.core.ai_client import PiAIClient
from alert_agent.core.ai_provider import AIProvider


class PiProvider(AIProvider):
    """Adapter that exposes ``PiAIClient`` through the provider interface."""

    def __init__(
        self,
        provider: str = "azure-openai-responses",
        model: str | None = None,
        api_key: str | None = None,
        metrics_dir: Path | str | None = None,
        agent_name: str | None = None,
        run_id: str | None = None,
        pricing: dict[str, Any] | None = None,
        extra_env: dict[str, str] | None = None,
        **kwargs: Any,
    ):
        self._client = PiAIClient(
            provider=provider,
            model=model,
            api_key=api_key,
            metrics_dir=metrics_dir,
            agent_name=agent_name,
            run_id=run_id,
            pricing=pricing,
            extra_env=extra_env,
        )
        self._provider_name = provider
        self._model_name = model

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> str:
        del max_tokens, temperature
        system_parts: list[str] = []
        prompt_parts: list[str] = []
        for message in messages:
            role = str(message.get("role") or "user")
            content = str(message.get("content") or "")
            if role == "system":
                system_parts.append(content)
                continue
            if role == "user":
                prompt_parts.append(content)
            else:
                prompt_parts.append(f"{role.upper()}:\n{content}")
        return self._client.query(
            "\n\n".join(part for part in prompt_parts if part),
            system_prompt="\n\n".join(part for part in system_parts if part) or None,
            metadata=kwargs.get("metadata"),
        )

    def get_last_usage(self) -> dict[str, Any] | None:
        return self._client.last_usage

    def get_provider_name(self) -> str:
        return self._provider_name

    def get_model_name(self) -> str | None:
        return self._model_name
