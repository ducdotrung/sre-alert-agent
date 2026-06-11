#!/bin/bash
#
# Force approve one issue for testing the full pipeline
#
# This script takes a pending issue and moves it to approved/
# for testing recommendation and sender agents
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PENDING_DIR="output/alerts/pending"
APPROVED_DIR="output/alerts/approved"

mkdir -p "$APPROVED_DIR"

# Find first pending P0 issue
PENDING_FILE=$(ls -1 "$PENDING_DIR"/*.json 2>/dev/null | head -1)

if [ -z "$PENDING_FILE" ]; then
    echo "No pending issues found in $PENDING_DIR"
    exit 1
fi

ISSUE_ID=$(basename "$PENDING_FILE" .json)

echo "Force approving issue: $ISSUE_ID"
echo "  From: $PENDING_FILE"
echo "  To: $APPROVED_DIR/$ISSUE_ID.json"

# Update the review decision to "send" with high confidence
jq '.review.decision = "send" | .review.confidence = 0.95 | .review.reasoning = "MANUALLY APPROVED FOR TESTING: Force approved to test full pipeline (recommendation + sender)"' \
    "$PENDING_FILE" > "$APPROVED_DIR/$ISSUE_ID.json"

echo "✓ Issue approved for testing"
echo ""
echo "Next steps:"
echo "  1. Run recommendation agent:"
echo "     python3 -m alert_agent.pipeline.recommendation"
echo "  2. Run sender (dry-run):"
echo "     python3 -m alert_agent.pipeline.sender --dry-run"
echo "  3. Run sender (real):"
echo "     python3 -m alert_agent.pipeline.sender"
