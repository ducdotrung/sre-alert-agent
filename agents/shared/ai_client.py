#!/usr/bin/env python3
"""AI client wrapper for pi CLI (DeepSeek integration)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class PiAIClient:
    """Wrapper for pi CLI to call AI models."""

    def __init__(self, provider: str = "deepseek", model: str | None = None, api_key: str | None = None):
        """
        Initialize AI client.

        Args:
            provider: AI provider (deepseek, openai, google, etc.)
            model: Model name (optional, uses provider default)
            api_key: API key (optional, uses env var)
        """
        self.provider = provider
        self.model = model
        self.api_key = api_key or os.environ.get(f"{provider.upper()}_API_KEY")
        self.timeout = int(os.environ.get("AI_TIMEOUT", "60"))

    def query(self, prompt: str, system_prompt: str | None = None) -> str:
        """
        Query AI via pi CLI.

        Args:
            prompt: User prompt
            system_prompt: System prompt (optional)

        Returns:
            AI response as string

        Raises:
            RuntimeError: If pi CLI fails
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(prompt)
            prompt_file = f.name

        try:
            cmd = [
                'pi',
                '--print',  # Non-interactive mode
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
                env={**os.environ, 'NO_COLOR': '1'}  # Disable color output
            )

            if result.returncode != 0:
                raise RuntimeError(f"pi CLI failed (exit {result.returncode}): {result.stderr}")

            return result.stdout.strip()

        finally:
            Path(prompt_file).unlink(missing_ok=True)

    def query_json(self, prompt: str, system_prompt: str | None = None) -> dict[str, Any]:
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
        response = self.query(prompt, system_prompt)

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
