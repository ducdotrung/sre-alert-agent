"""Compatibility package for legacy shared imports."""

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
