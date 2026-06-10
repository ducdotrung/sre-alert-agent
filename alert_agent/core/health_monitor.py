#!/usr/bin/env python3
"""Helpers for pipeline health state and alert deduplication."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    """Return the current UTC timestamp as ISO8601."""
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json_file(path: Path) -> dict[str, Any]:
    """Read a JSON file, returning an empty object if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return {}


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON object to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


def parse_timestamp(value: Any) -> dt.datetime | None:
    """Parse an ISO8601 timestamp with a best-effort fallback."""
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None
