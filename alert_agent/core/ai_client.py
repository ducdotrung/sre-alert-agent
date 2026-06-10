#!/usr/bin/env python3
"""AI client wrapper for pi CLI with usage and cost ledger support."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class PiAIClient:
    """Wrapper for pi CLI to call AI models."""

    PROVIDER_ENV_MAP = {
        "azure-openai": "AZURE_OPENAI_API_KEY",
        "azure-openai-chat": "AZURE_OPENAI_API_KEY",
        "azure-openai-responses": "AZURE_OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "google": "GEMINI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
    }

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
    ):
        """
        Initialize AI client.

        Args:
            provider: AI provider (azure-openai-responses, deepseek, openai, google, etc.)
            model: Model name (optional, uses provider default)
            api_key: API key (optional, uses env var)
            metrics_dir: Directory to store usage ledgers
            agent_name: Agent or subsystem name for usage records
            run_id: Shared pipeline run identifier
            pricing: Optional pricing config for cost estimation
        """
        self.provider = provider
        self.model = model
        env_var = self.PROVIDER_ENV_MAP.get(provider, f"{provider.upper().replace('-', '_')}_API_KEY")
        self.api_key = api_key or os.environ.get("AI_API_KEY") or os.environ.get(env_var)
        self.timeout = int(os.environ.get("AI_TIMEOUT", "60"))
        self.metrics_dir = Path(metrics_dir) if metrics_dir else None
        self.agent_name = agent_name or "unknown"
        self.run_id = run_id or os.environ.get("RUN_ID")
        self.pricing = pricing or {}
        self.extra_env = {str(key): str(value) for key, value in (extra_env or {}).items() if value not in (None, "")}
        self.last_usage: dict[str, Any] | None = None
        self.last_response_text = ""
        self.last_record: dict[str, Any] | None = None

    @staticmethod
    def _extract_text_content(content: Any) -> str:
        """Extract assistant text from Pi JSON mode message content."""
        if isinstance(content, str):
            return content

        if not isinstance(content, list):
            return ""

        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts).strip()

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        """Convert a numeric-like value to float if possible."""
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value: Any) -> int:
        """Convert a numeric-like value to int, defaulting to zero."""
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _estimate_cost(self, usage: dict[str, Any] | None) -> tuple[float | None, str]:
        """Estimate cost from token usage when Pi does not provide one."""
        if not usage:
            return None, "missing"

        cost = usage.get("cost")
        if isinstance(cost, dict):
            total = self._safe_float(cost.get("total"))
            if total is not None:
                return total, "provider"

        input_tokens = self._safe_int(usage.get("input"))
        output_tokens = self._safe_int(usage.get("output"))
        cache_read_tokens = self._safe_int(usage.get("cacheRead"))
        cache_write_tokens = self._safe_int(usage.get("cacheWrite"))

        input_rate = self._safe_float(self.pricing.get("input_per_million"))
        output_rate = self._safe_float(self.pricing.get("output_per_million"))
        cache_read_rate = self._safe_float(self.pricing.get("cache_read_per_million")) or 0.0
        cache_write_rate = self._safe_float(self.pricing.get("cache_write_per_million")) or 0.0

        if input_rate is None and output_rate is None:
            return None, "missing"

        estimated = 0.0
        if input_rate is not None:
            estimated += (input_tokens / 1_000_000) * input_rate
        if output_rate is not None:
            estimated += (output_tokens / 1_000_000) * output_rate
        estimated += (cache_read_tokens / 1_000_000) * cache_read_rate
        estimated += (cache_write_tokens / 1_000_000) * cache_write_rate
        return estimated, "estimated"

    def _append_usage_record(self, record: dict[str, Any]) -> None:
        """Append one usage record to the monthly ledger."""
        if self.metrics_dir is None:
            return

        self.metrics_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m")
        ledger_path = self.metrics_dir / f"ai_usage-{stamp}.jsonl"
        with ledger_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True) + "\n")

    def query(
        self,
        prompt: str,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Query AI via pi CLI.

        Args:
            prompt: User prompt
            system_prompt: System prompt (optional)
            metadata: Extra usage ledger fields (issue_id, operation, etc.)

        Returns:
            AI response as string

        Raises:
            RuntimeError: If pi CLI fails
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(prompt)
            prompt_file = f.name

        started_at = time.time()

        try:
            cmd = [
                'pi',
                '--mode', 'json',
                '--provider', self.provider,
                '--no-session',  # Don't save session
            ]

            if self.model:
                cmd.extend(['--model', self.model])

            if system_prompt:
                cmd.extend(['--system-prompt', system_prompt])

            if self.api_key:
                cmd.extend(['--api-key', self.api_key])

            cmd.append('@' + prompt_file)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env={**os.environ, **self.extra_env, 'NO_COLOR': '1'}  # Disable color output
            )

            if result.returncode != 0:
                raise RuntimeError(f"pi CLI failed (exit {result.returncode}): {result.stderr}")

            response_text = ""
            usage: dict[str, Any] | None = None
            model_used = self.model
            provider_used = self.provider

            for raw_line in result.stdout.splitlines():
                line = raw_line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if event.get("type") != "message_end":
                    continue

                message = event.get("message", {})
                if message.get("role") != "assistant":
                    continue

                response_text = self._extract_text_content(message.get("content"))
                usage = message.get("usage")
                provider_used = message.get("provider", provider_used)
                model_used = message.get("model", model_used)

            if not response_text:
                raise RuntimeError("pi JSON mode completed without an assistant response")

            duration_ms = round((time.time() - started_at) * 1000)
            cost_usd, cost_source = self._estimate_cost(usage)
            prompt_meta = metadata or {}
            issue_id = prompt_meta.get("issue_id")
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_id": self.run_id,
                "agent": self.agent_name,
                "operation": prompt_meta.get("operation"),
                "issue_id": issue_id,
                "provider": provider_used,
                "model": model_used,
                "success": True,
                "duration_ms": duration_ms,
                "prompt_chars": len(prompt),
                "response_chars": len(response_text),
                "prompt_tokens": self._safe_int((usage or {}).get("input")),
                "completion_tokens": self._safe_int((usage or {}).get("output")),
                "cache_read_tokens": self._safe_int((usage or {}).get("cacheRead")),
                "cache_write_tokens": self._safe_int((usage or {}).get("cacheWrite")),
                "total_tokens": self._safe_int((usage or {}).get("total")),
                "cost_usd": cost_usd,
                "cost_source": cost_source,
                "system_prompt": bool(system_prompt),
                "metadata": {
                    k: v for k, v in prompt_meta.items() if k not in {"issue_id", "operation"}
                },
            }

            self.last_usage = usage
            self.last_response_text = response_text
            self.last_record = record
            self._append_usage_record(record)

            return response_text

        finally:
            Path(prompt_file).unlink(missing_ok=True)

    def query_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Query AI and parse JSON response.

        Args:
            prompt: User prompt (should request JSON output)
            system_prompt: System prompt (optional)

        Returns:
            Parsed JSON as dict

        Raises:
            RuntimeError: If pi CLI fails
            json.JSONDecodeError: If response is not valid JSON
        """
        response = self.query(prompt, system_prompt, metadata)

        # Extract JSON from markdown code blocks if present
        if '```json' in response:
            match = re.search(r'```json\s*\n(.*?)\n```', response, re.DOTALL)
            if match:
                response = match.group(1)
        elif '```' in response:
            # Generic code block
            match = re.search(r'```\s*\n(.*?)\n```', response, re.DOTALL)
            if match:
                response = match.group(1)

        # Remove any leading/trailing text that's not JSON
        response = response.strip()
        if not response.startswith('{') and not response.startswith('['):
            # Try to find JSON object in the response
            json_match = re.search(r'(\{.*\}|\[.*\])', response, re.DOTALL)
            if json_match:
                response = json_match.group(1)

        return json.loads(response)

    def test_connection(self) -> bool:
        """
        Test if AI client can connect and query.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            response = self.query("What is 2+2? Reply with just the number.")
            return '4' in response
        except Exception:
            return False


def load_prompt_template(template_name: str, base_dir: Path | None = None) -> str:
    """
    Load prompt template from prompts/ directory.

    Args:
        template_name: Template filename (e.g., "triage_reclassify.txt")
        base_dir: Base directory (defaults to repo root)

    Returns:
        Template content as string

    Raises:
        FileNotFoundError: If template doesn't exist
    """
    if base_dir is None:
        # Assume we're in agents/shared/, go up two levels to repo root
        base_dir = Path(__file__).parent.parent.parent

    template_path = base_dir / "prompts" / template_name

    if not template_path.exists():
        raise FileNotFoundError(f"Prompt template not found: {template_path}")

    return template_path.read_text(encoding='utf-8')


def format_prompt(template: str, **kwargs: Any) -> str:
    """
    Format prompt template with variables.

    Args:
        template: Prompt template string with {variable} placeholders
        **kwargs: Variables to substitute

    Returns:
        Formatted prompt
    """
    return template.format(**kwargs)
