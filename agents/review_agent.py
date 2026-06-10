#!/usr/bin/env python3
"""Compatibility wrapper for the shared review stage."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alert_agent.pipeline.review import main


if __name__ == '__main__':
    raise SystemExit(main())
