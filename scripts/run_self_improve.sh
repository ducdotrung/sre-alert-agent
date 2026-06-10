#!/bin/bash
#
# Self-improvement proposal runner
#
# Usage:
#   ./scripts/run_self_improve.sh [--force] [--dry-run]
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

CONFIG_FILE="${CONFIG_FILE:-config/agent_config.yaml}"
LOG_DIR="${LOG_DIR:-output/logs}"

mkdir -p "$LOG_DIR"

if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

python3 scripts/run_self_improve.py --config "$CONFIG_FILE" "$@" 2>&1 | tee -a "$LOG_DIR/self-improve-$(date +%Y%m%d).log"
