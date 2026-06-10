#!/usr/bin/env python3
"""Configuration loader with environment variable substitution."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml


def load_dotenv_if_present(path: Path) -> None:
    """Load a simple .env file into the process without overwriting existing vars."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue

        if line.startswith('export '):
            line = line[7:].strip()

        key, sep, value = line.partition('=')
        if not sep:
            continue

        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue

        if value and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]

        os.environ[key] = value


def substitute_env_vars(value: Any) -> Any:
    """
    Recursively substitute environment variables in config values.

    Supports: ${VAR_NAME} or ${VAR_NAME:default_value}

    Args:
        value: Config value (str, dict, list, etc.)

    Returns:
        Value with env vars substituted
    """
    if isinstance(value, str):
        def resolve_template(template: str) -> str:
            result: list[str] = []
            index = 0

            while index < len(template):
                if template.startswith('${', index):
                    replacement, index = resolve_expression(template, index + 2)
                    result.append(replacement)
                    continue

                result.append(template[index])
                index += 1

            return ''.join(result)

        def resolve_expression(template: str, index: int) -> tuple[str, int]:
            expr: list[str] = []
            nesting = 0

            while index < len(template):
                if template.startswith('${', index):
                    nesting += 1
                    expr.append('${')
                    index += 2
                    continue

                char = template[index]
                if char == '}' and nesting == 0:
                    return resolve_var_expr(''.join(expr)), index + 1

                if char == '}' and nesting > 0:
                    nesting -= 1

                expr.append(char)
                index += 1

            # Leave unmatched templates unchanged.
            return '${' + ''.join(expr), index

        def resolve_var_expr(expr: str) -> str:
            nesting = 0
            separator = -1

            for index, char in enumerate(expr):
                if expr.startswith('${', index):
                    nesting += 1
                    continue
                if char == '}' and nesting > 0:
                    nesting -= 1
                    continue
                if char == ':' and nesting == 0:
                    separator = index
                    break

            if separator == -1:
                var_name = expr
                default = ''
            else:
                var_name = expr[:separator]
                default = expr[separator + 1:]

            return os.environ.get(var_name, resolve_template(default))

        return resolve_template(value)

    elif isinstance(value, dict):
        return {k: substitute_env_vars(v) for k, v in value.items()}

    elif isinstance(value, list):
        return [substitute_env_vars(item) for item in value]

    else:
        return value


def load_yaml_config(path: Path | str) -> dict[str, Any]:
    """
    Load YAML config file with environment variable substitution.

    Args:
        path: Path to YAML file

    Returns:
        Config dict with env vars substituted

    Raises:
        FileNotFoundError: If file doesn't exist
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open('r', encoding='utf-8') as f:
        raw_config = yaml.safe_load(f)

    return substitute_env_vars(raw_config)


def load_json_config(path: Path | str) -> dict[str, Any] | list[Any]:
    """
    Load JSON config file with environment variable substitution.

    Args:
        path: Path to JSON file

    Returns:
        Config dict/list with env vars substituted

    Raises:
        FileNotFoundError: If file doesn't exist
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open('r', encoding='utf-8') as f:
        raw_config = json.load(f)

    return substitute_env_vars(raw_config)


def get_repo_root() -> Path:
    """
    Get repository root directory.

    Returns:
        Path to repo root

    Raises:
        RuntimeError: If not in a git repo
    """
    current = Path(__file__).resolve()

    # Walk up until we find .git or reach root
    for parent in [current] + list(current.parents):
        if (parent / '.git').exists():
            return parent

    raise RuntimeError("Not in a git repository")


def load_full_config(config_file: str = "config/agent_config.yaml") -> dict[str, Any]:
    """Load the full repo config with env substitution applied."""
    repo_root = get_repo_root()
    load_dotenv_if_present(repo_root / '.env')
    return load_yaml_config(repo_root / config_file)


def _merge_common(full_config: dict[str, Any], payload: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if 'common' in full_config:
        merged.update(full_config['common'])
    if payload:
        merged.update(payload)
    return merged


def load_agent_config(agent_name: str, config_file: str = "config/agent_config.yaml") -> dict[str, Any]:
    """
    Load configuration for a specific agent.

    Args:
        agent_name: Agent name (e.g., "triage_agent")
        config_file: Config file path (relative to repo root)

    Returns:
        Agent-specific config dict

    Raises:
        FileNotFoundError: If config file not found
        KeyError: If agent not in config
    """
    full_config = load_full_config(config_file)

    if agent_name not in full_config:
        raise KeyError(f"Agent '{agent_name}' not found in config file")

    # Merge with common/shared config if present
    return _merge_common(full_config, full_config[agent_name])


def load_pipeline_stage_config(
    stage_name: str,
    config_file: str = "config/agent_config.yaml",
    *,
    legacy_section: str | None = None,
) -> dict[str, Any]:
    """Load a pipeline stage config from `pipeline.<stage>` with legacy fallback."""
    full_config = load_full_config(config_file)
    pipeline_config = dict(full_config.get("pipeline", {}) or {})
    stage_config = pipeline_config.get(stage_name)
    if isinstance(stage_config, dict):
        return _merge_common(full_config, stage_config)
    if legacy_section:
        return load_agent_config(legacy_section, config_file)
    raise KeyError(f"Pipeline stage '{stage_name}' not found in config file")


def load_source_config(
    source_name: str,
    config_file: str = "config/agent_config.yaml",
) -> dict[str, Any]:
    """Load a source definition from `sources.<name>` with legacy fallbacks."""
    full_config = load_full_config(config_file)
    sources = dict(full_config.get("sources", {}) or {})
    source_config = sources.get(source_name)
    if isinstance(source_config, dict):
        merged = _merge_common(full_config, source_config.get("config"))
        merged["source_name"] = source_name
        merged["kind"] = source_config.get("kind", source_name)
        merged["enabled"] = source_config.get("enabled", True)
        merged["policy_pack"] = source_config.get("policy_pack", source_name)
        return merged

    if source_name in full_config:
        merged = _merge_common(full_config, full_config[source_name])
        merged["source_name"] = source_name
        merged["kind"] = source_name
        merged["enabled"] = True
        merged["policy_pack"] = f"{source_name}-default"
        return merged

    raise KeyError(f"Source '{source_name}' not found in config file")


def load_policy_pack(
    pack_name: str,
    config_file: str = "config/agent_config.yaml",
) -> dict[str, Any]:
    """Load a policy pack, falling back to legacy Sentry paths."""
    full_config = load_full_config(config_file)
    policy_packs = dict(full_config.get("policy_packs", {}) or {})
    if pack_name in policy_packs:
        return _merge_common(full_config, policy_packs[pack_name])

    if pack_name in {"sentry", "sentry-default"} and "triage_agent" in full_config:
        triage_config = load_agent_config("triage_agent", config_file)
        return {
            "name": pack_name,
            "classification_rules": triage_config.get("classification_rules"),
            "priority_thresholds": triage_config.get("priority_thresholds"),
            "ignore_rules": triage_config.get("ignore_rules"),
            "prompts": {
                "triage": "prompts/triage_reclassify.md",
                "review": "prompts/review_decision.md",
                "recommendation": "prompts/recommendation_generate.md",
            },
        }

    raise KeyError(f"Policy pack '{pack_name}' not found in config file")
