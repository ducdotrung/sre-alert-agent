#!/usr/bin/env python3
"""Compatibility wrapper for the shared sender stage."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alert_agent.pipeline.sender import build_teams_message_card, main, parse_front_matter


if __name__ == '__main__':
    raise SystemExit(main())
