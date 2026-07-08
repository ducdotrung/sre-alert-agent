#!/usr/bin/env python3
"""Azure LiteLLM AI provider implementation."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alert_agent.core.ai_provider import AIProvider


class AzureLiteLLMProvider(AIProvider):
    """Provider for an OpenAI-compatible Azure LiteLLM gateway."""

    def __init__(
        self,
        endpoint: str | None = None,
        deployment: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        metrics_dir: Path | str | None = None,
        agent_name: str | None = None,
        run_id: str | None = None,
        pricing: dict[str, Any] | None = None,
        timeout: int | str = 60,
        **kwargs: Any,
    ):
        del kwargs
        self.endpoint = (endpoint or os.environ.get("AZURE_LITELLM_ENDPOINT", "")).rstrip("/")
        self.deployment = deployment or os.environ.get("AZURE_LITELLM_DEPLOYMENT", "") or model or ""
        self.api_key = api_key or os.environ.get("AZURE_LITELLM_API_KEY", "")
        try:
            self.timeout = int(timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid Azure LiteLLM timeout: {timeout!r}") from exc

        if not self.endpoint:
            raise ValueError("Azure LiteLLM endpoint is required (AZURE_LITELLM_ENDPOINT)")
        if not self.deployment:
            raise ValueError("Azure LiteLLM deployment is required (AZURE_LITELLM_DEPLOYMENT)")
        if not self.api_key:
            raise ValueError("Azure LiteLLM API key is required (AZURE_LITELLM_API_KEY)")

        self.metrics_dir = Path(metrics_dir) if metrics_dir else None
        self.agent_name = agent_name or "unknown"
        self.run_id = run_id or os.environ.get("RUN_ID")
        self.pricing = pricing or {}
        self.last_usage: dict[str, Any] | None = None

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.deployment,
            "messages": messages,
        }
        if max_tokens is not None:
            payload["max_completion_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature

        request = urllib.request.Request(
            f"{self.endpoint}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        started_at = time.time()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8")
            raise RuntimeError(f"Azure LiteLLM API error ({exc.code}): {error_body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Azure LiteLLM connection error: {exc.reason}") from exc
        except Exception as exc:
            raise RuntimeError(f"Azure LiteLLM request failed: {exc}") from exc

        usage = result.get("usage", {})
        self.last_usage = {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        self._log_usage(messages, content, time.time() - started_at, kwargs.get("metadata", {}))
        return content

    def get_last_usage(self) -> dict[str, Any] | None:
        return self.last_usage

    def get_provider_name(self) -> str:
        return "azure-litellm"

    def get_model_name(self) -> str | None:
        return self.deployment

    def _log_usage(
        self,
        messages: list[dict[str, str]],
        response: str,
        duration: float,
        metadata: dict[str, Any] | None,
    ) -> None:
        del messages, response
        if self.metrics_dir is None:
            return

        metadata = metadata or {}
        usage = self.last_usage or {}
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)

        cost = None
        cost_source = "missing"
        if self.pricing:
            input_rate = float(self.pricing.get("input_per_million", 0) or 0)
            output_rate = float(self.pricing.get("output_per_million", 0) or 0)
            if input_rate or output_rate:
                cost = (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate
                cost_source = "estimated"

        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": self.agent_name,
            "operation": metadata.get("operation", "chat"),
            "provider": "azure-litellm",
            "model": self.deployment,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens", input_tokens + output_tokens) or 0),
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "success": True,
            "duration": round(duration, 3),
        }
        if cost is not None:
            record["cost"] = cost
            record["cost_usd"] = cost
            record["cost_source"] = cost_source
            record["cost_type"] = cost_source
        if self.run_id:
            record["run_id"] = self.run_id
        for key in ("issue_id", "alert_id", "priority", "classification"):
            if key in metadata:
                record[key] = metadata[key]

        try:
            self.metrics_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y-%m")
            ledger_path = self.metrics_dir / f"ai_usage-{stamp}.jsonl"
            with ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=True) + "\n")
        except Exception:
            pass
