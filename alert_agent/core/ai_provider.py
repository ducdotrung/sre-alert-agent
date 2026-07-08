#!/usr/bin/env python3
"""Base interface for AI provider plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AIProvider(ABC):
    """Common interface for pluggable AI providers."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> str:
        """Send a chat request and return the response text."""

    @abstractmethod
    def get_last_usage(self) -> dict[str, Any] | None:
        """Return usage information for the last request, if any."""

    def supports_streaming(self) -> bool:
        return False

    def get_provider_name(self) -> str:
        return self.__class__.__name__.replace("Provider", "").lower()

    def get_model_name(self) -> str | None:
        return None

    def query(
        self,
        prompt: str,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, metadata=metadata)

    def query_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import json
        import re

        response = self.query(prompt, system_prompt=system_prompt, metadata=metadata).strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
        if match:
            response = match.group(1).strip()
        return json.loads(response)
