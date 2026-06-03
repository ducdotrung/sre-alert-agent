#!/usr/bin/env python3
"""Configuration loader with environment variable substitution."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml


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
        # Pattern: ${VAR_NAME} or ${VAR_NAME:default}
        pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'

        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            default = match.group(2) if match.group(2) is not None else ''
            return os.environ.get(var_name, default)

        return re.sub(pattern, replacer, value)

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
    repo_root = get_repo_root()
    config_path = repo_root / config_file

    full_config = load_yaml_config(config_path)

    if agent_name not in full_config:
        raise KeyError(f"Agent '{agent_name}' not found in config file")

    # Merge with common/shared config if present
    agent_config = {}
    if 'common' in full_config:
        agent_config.update(full_config['common'])
    agent_config.update(full_config[agent_name])

    return agent_config
