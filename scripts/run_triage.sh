#!/bin/bash
#
# Sentry Alert Agent Orchestrator
#
# This script runs all agents in sequence:
# 1. Triage Agent (rule-based + AI classification)
# 2. Review Agent (AI review for P0/P1) - only if triage found critical issues
# 3. Recommendation Agent (AI recommendations) - only if review approved issues
# 4. Sender (Teams notification) - only if recommendations generated
#
# Usage:
#   ./run_triage.sh [--hours N | --minutes N]
#
# Options:
#   --hours N      Lookback window in hours (e.g., 1, 24, 168)
#   --minutes N    Lookback window in minutes (e.g., 21, 30, 90)
#

set -euo pipefail

# Parse arguments
TIME_ARG=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --hours)
            TIME_ARG="--hours $2"
            shift 2
            ;;
        --minutes)
            TIME_ARG="--minutes $2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--hours N | --minutes N]"
            exit 1
            ;;
    esac
done

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

CONFIG_FILE="${CONFIG_FILE:-config/agent_config.yaml}"
LOG_DIR="${LOG_DIR:-output/logs}"
LOCK_FILE="${LOCK_FILE:-/tmp/sentry-alert-agent.lock}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
log() {
    echo -e "[$(date +'%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_DIR/orchestrator.log"
}

log_info() {
    log "${BLUE}[INFO]${NC} $*"
}

log_success() {
    log "${GREEN}[SUCCESS]${NC} $*"
}

log_warn() {
    log "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    log "${RED}[ERROR]${NC} $*"
}

# Create log directory
mkdir -p "$LOG_DIR"

# Check for lock file (prevent concurrent runs)
if [ -f "$LOCK_FILE" ]; then
    log_error "Lock file exists: $LOCK_FILE"
    log_error "Another instance may be running, or previous run crashed."
    log_error "Remove lock file if you're sure no other instance is running:"
    log_error "  sudo rm $LOCK_FILE"
    exit 1
fi

# Create lock file
touch "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

log_info "=========================================="
log_info "Sentry Alert Agent Pipeline Starting"
log_info "=========================================="
log_info "Config: $CONFIG_FILE"
log_info "Repo: $REPO_ROOT"
log_info ""

# Check environment
if [ ! -f "$CONFIG_FILE" ]; then
    log_error "Config file not found: $CONFIG_FILE"
    exit 1
fi

# Load .env if present
if [ -f ".env" ]; then
    log_info "Loading environment from .env"
    set -a
    source .env
    set +a
fi

# Agent 1: Triage
log_info "=========================================="
log_info "AGENT 1: Triage (Rule-based + AI)"
log_info "=========================================="

python3 agents/triage_agent.py --config "$CONFIG_FILE" $TIME_ARG 2>&1 | tee -a "$LOG_DIR/triage-$(date +%Y%m%d).log"
TRIAGE_EXIT=$?

TRIAGE_COUNT=$(ls output/alerts/triage/*.json 2>/dev/null | wc -l | tr -d ' ')
log_info "Triage complete: $TRIAGE_COUNT issues processed (exit code: $TRIAGE_EXIT)"

if [ $TRIAGE_EXIT -eq 1 ]; then
    log_error "Triage agent failed"
    exit 1
elif [ $TRIAGE_EXIT -eq 0 ]; then
    log_success "No critical issues found, stopping pipeline"
    exit 0
elif [ $TRIAGE_EXIT -eq 2 ]; then
    log_success "Critical issues found, continuing to review"
else
    log_warn "Unexpected exit code from triage: $TRIAGE_EXIT"
fi

# Agent 2: Review
log_info ""
log_info "=========================================="
log_info "AGENT 2: Review (AI assessment)"
log_info "=========================================="

python3 agents/review_agent.py --config "$CONFIG_FILE" 2>&1 | tee -a "$LOG_DIR/review-$(date +%Y%m%d).log"
REVIEW_EXIT=$?

APPROVED_COUNT=$(ls output/alerts/approved/*.json 2>/dev/null | wc -l | tr -d ' ')
PENDING_COUNT=$(ls output/alerts/pending/*.json 2>/dev/null | wc -l | tr -d ' ')
log_info "Review complete: $APPROVED_COUNT auto-approved, $PENDING_COUNT pending (exit code: $REVIEW_EXIT)"

if [ $REVIEW_EXIT -eq 1 ]; then
    log_error "Review agent failed"
    exit 1
elif [ $REVIEW_EXIT -eq 0 ]; then
    log_warn "No issues auto-approved, check pending/ for manual review"
    exit 0
elif [ $REVIEW_EXIT -eq 2 ]; then
    log_success "Issues auto-approved, continuing to recommendations"
else
    log_warn "Unexpected exit code from review: $REVIEW_EXIT"
fi

# Agent 3: Recommendation
log_info ""
log_info "=========================================="
log_info "AGENT 3: Recommendation (AI generation)"
log_info "=========================================="

python3 agents/recommendation_agent.py --config "$CONFIG_FILE" 2>&1 | tee -a "$LOG_DIR/recommendation-$(date +%Y%m%d).log"
RECO_EXIT=$?

RECO_COUNT=$(ls output/alerts/recommendations/*.md 2>/dev/null | wc -l | tr -d ' ')
log_info "Recommendations generated: $RECO_COUNT (exit code: $RECO_EXIT)"

if [ $RECO_EXIT -eq 1 ]; then
    log_error "Recommendation agent failed"
    exit 1
elif [ $RECO_EXIT -eq 0 ]; then
    log_warn "No recommendations generated"
    exit 0
elif [ $RECO_EXIT -eq 2 ]; then
    log_success "Recommendations ready, continuing to sender"
else
    log_warn "Unexpected exit code from recommendation: $RECO_EXIT"
fi

# Sender
log_info ""
log_info "=========================================="
log_info "SENDER: Teams Notification"
log_info "=========================================="

python3 agents/sender.py --config "$CONFIG_FILE" 2>&1 | tee -a "$LOG_DIR/sender-$(date +%Y%m%d).log"
SENDER_EXIT=$?

SENT_COUNT=$(ls output/alerts/sent/*.md 2>/dev/null | wc -l | tr -d ' ')
log_info "Sent to Teams: $SENT_COUNT (exit code: $SENDER_EXIT)"

if [ $SENDER_EXIT -eq 0 ]; then
    log_success "Sender complete"
else
    log_error "Sender failed"
    exit 1
fi

# Summary
log_info ""
log_info "=========================================="
log_info "Pipeline Complete"
log_info "=========================================="
log_info "Triaged: $TRIAGE_COUNT | Auto-approved: $APPROVED_COUNT | Pending Review: $PENDING_COUNT | Sent: $SENT_COUNT"
log_success "All agents completed successfully"
