#!/usr/bin/env python3
"""Shared Microsoft Teams helpers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def send_to_teams(webhook_url: str, payload: dict[str, Any], timeout: int = 15) -> str:
    """
    POST message card to Teams webhook.

    Returns:
        Response body

    Raises:
        RuntimeError: If request fails
    """
    data = json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(webhook_url, data=data, method='POST')
    request.add_header('Content-Type', 'application/json')

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode('utf-8', errors='replace')

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f"Teams webhook HTTP {exc.code}: {detail}") from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Teams webhook: {exc}") from exc
