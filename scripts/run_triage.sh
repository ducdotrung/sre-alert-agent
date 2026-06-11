#!/bin/bash
#
# Alert Agent Orchestrator
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
PIPELINE_SOURCE="${PIPELINE_SOURCE:-sentry}"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
RUN_MARKER="/tmp/sentry-alert-agent-${RUN_ID}.marker"
export RUN_ID
TRIAGE_COUNT=0
APPROVED_COUNT=0
PENDING_COUNT=0
RECO_COUNT=0
SENT_COUNT=0
FAILURE_STAGE=""
BUDGET_ENFORCEMENT_MODE="warn_only"
BUDGET_ENFORCEMENT_ACTIVE="false"
BUDGET_ENFORCEMENT_REASON="not_checked"
RECOMMENDATION_DRY_RUN=""

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

check_budget_enforcement() {
    if [ ! -f "scripts/check_budget_enforcement.py" ]; then
        return
    fi

    local enforcement_json
    enforcement_json="$(python3 scripts/check_budget_enforcement.py --config "$CONFIG_FILE" 2>/dev/null || echo '{}')"
    BUDGET_ENFORCEMENT_MODE="$(printf '%s' "$enforcement_json" | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('mode','warn_only'))" 2>/dev/null || echo "warn_only")"
    BUDGET_ENFORCEMENT_ACTIVE="$(printf '%s' "$enforcement_json" | python3 -c "import json,sys; data=json.load(sys.stdin); print(str(data.get('active', False)).lower())" 2>/dev/null || echo "false")"
    BUDGET_ENFORCEMENT_REASON="$(printf '%s' "$enforcement_json" | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('reason','unknown'))" 2>/dev/null || echo "unknown")"

    if [ "$BUDGET_ENFORCEMENT_ACTIVE" = "true" ]; then
        log_warn "Budget enforcement active: mode=$BUDGET_ENFORCEMENT_MODE reason=$BUDGET_ENFORCEMENT_REASON"
    fi
}

count_modified_files() {
    local target_dir="$1"
    local pattern="$2"

    if [ ! -d "$target_dir" ] || [ ! -f "$RUN_MARKER" ]; then
        echo 0
        return
    fi

    find "$target_dir" -maxdepth 1 -type f -name "$pattern" -newer "$RUN_MARKER" | wc -l | tr -d ' '
}

update_pipeline_state() {
    local status="$1"
    shift
    if [ ! -f "scripts/update_pipeline_state.py" ]; then
        return
    fi

    python3 scripts/update_pipeline_state.py \
        --config "$CONFIG_FILE" \
        --status "$status" \
        --run-id "$RUN_ID" \
        --lock-file "$LOCK_FILE" \
        --triaged "$TRIAGE_COUNT" \
        --approved "$APPROVED_COUNT" \
        --pending "$PENDING_COUNT" \
        --recommendations "$RECO_COUNT" \
        --sent "$SENT_COUNT" \
        "$@" >/dev/null 2>&1 || true
}

run_budget_monitor() {
    if [ ! -f "scripts/check_ai_budget.py" ]; then
        return
    fi

    log_info ""
    log_info "=========================================="
    log_info "MONITOR: AI Budget Check"
    log_info "=========================================="

    set +e
    python3 scripts/check_ai_budget.py --config "$CONFIG_FILE" 2>&1 | tee -a "$LOG_DIR/monitor-$(date +%Y%m%d).log"
    local monitor_exit=${PIPESTATUS[0]}
    set -e

    if [ "$monitor_exit" -eq 0 ] || [ "$monitor_exit" -eq 2 ]; then
        log_info "Budget monitor complete"
    else
        log_warn "Budget monitor failed"
    fi
}

run_health_monitor() {
    if [ ! -f "scripts/check_pipeline_health.py" ]; then
        return
    fi

    log_info ""
    log_info "=========================================="
    log_info "MONITOR: Pipeline Health Check"
    log_info "=========================================="

    set +e
    python3 scripts/check_pipeline_health.py --config "$CONFIG_FILE" 2>&1 | tee -a "$LOG_DIR/health-monitor-$(date +%Y%m%d).log"
    local health_exit=${PIPESTATUS[0]}
    set -e

    if [ "$health_exit" -eq 0 ] || [ "$health_exit" -eq 2 ]; then
        log_info "Health monitor complete"
    else
        log_warn "Health monitor failed"
    fi
}

run_queue_monitor() {
    if [ ! -f "scripts/check_queue_health.py" ]; then
        return
    fi

    log_info ""
    log_info "=========================================="
    log_info "MONITOR: Queue Health Check"
    log_info "=========================================="

    set +e
    python3 scripts/check_queue_health.py --config "$CONFIG_FILE" 2>&1 | tee -a "$LOG_DIR/queue-monitor-$(date +%Y%m%d).log"
    local queue_exit=${PIPESTATUS[0]}
    set -e

    if [ "$queue_exit" -eq 0 ] || [ "$queue_exit" -eq 2 ]; then
        log_info "Queue monitor complete"
    else
        log_warn "Queue monitor failed"
    fi
}

run_daily_summary() {
    if [ ! -f "scripts/send_daily_summary.py" ]; then
        return
    fi

    log_info ""
    log_info "=========================================="
    log_info "MONITOR: Daily Summary"
    log_info "=========================================="

    set +e
    python3 scripts/send_daily_summary.py --config "$CONFIG_FILE" 2>&1 | tee -a "$LOG_DIR/daily-summary-$(date +%Y%m%d).log"
    local summary_exit=${PIPESTATUS[0]}
    set -e

    if [ "$summary_exit" -eq 0 ] || [ "$summary_exit" -eq 2 ]; then
        log_info "Daily summary complete"
    else
        log_warn "Daily summary failed"
    fi
}

pipeline_exit() {
    local exit_code="$1"
    if [ "$exit_code" -eq 0 ]; then
        update_pipeline_state completed --exit-code "$exit_code"
    else
        update_pipeline_state failed --exit-code "$exit_code" --failure-stage "$FAILURE_STAGE"
    fi
    run_budget_monitor
    run_health_monitor
    run_queue_monitor
    run_daily_summary
    exit "$exit_code"
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
touch "$RUN_MARKER"
trap "rm -f '$LOCK_FILE' '$RUN_MARKER'" EXIT
update_pipeline_state running

log_info "=========================================="
log_info "Alert Agent Pipeline Starting"
log_info "=========================================="
log_info "Config: $CONFIG_FILE"
log_info "Repo: $REPO_ROOT"
log_info "Source: $PIPELINE_SOURCE"
log_info "Run ID: $RUN_ID"
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

check_budget_enforcement

# Agent 1: Triage
log_info "=========================================="
log_info "AGENT 1: Triage (Rule-based + AI)"
log_info "=========================================="

TRIAGE_DRY_RUN=""
if [ "$BUDGET_ENFORCEMENT_ACTIVE" = "true" ] && [ "$BUDGET_ENFORCEMENT_MODE" = "disable_all_ai" ]; then
    TRIAGE_DRY_RUN="--dry-run"
    log_warn "Running triage in dry-run mode because budget enforcement disables all AI"
fi

set +e
python3 -m alert_agent.pipeline.triage --config "$CONFIG_FILE" --source "$PIPELINE_SOURCE" $TIME_ARG $TRIAGE_DRY_RUN 2>&1 | tee -a "$LOG_DIR/triage-$(date +%Y%m%d).log"
TRIAGE_EXIT=${PIPESTATUS[0]}
set -e

TRIAGE_COUNT=$(count_modified_files "output/alerts/triage" "*.json")
log_info "Triage complete: $TRIAGE_COUNT issues processed (exit code: $TRIAGE_EXIT)"

if [ $TRIAGE_EXIT -eq 1 ]; then
    FAILURE_STAGE="triage"
    log_error "Triage agent failed"
    pipeline_exit 1
elif [ $TRIAGE_EXIT -eq 0 ]; then
    log_success "No critical issues found, stopping pipeline"
    pipeline_exit 0
elif [ $TRIAGE_EXIT -eq 2 ]; then
    log_success "Critical issues found, continuing to review"
else
    log_warn "Unexpected exit code from triage: $TRIAGE_EXIT"
fi

if [ "$BUDGET_ENFORCEMENT_ACTIVE" = "true" ] && [ "$BUDGET_ENFORCEMENT_MODE" = "disable_all_ai" ]; then
    log_warn "Skipping review and recommendation because budget enforcement disables all AI"
    pipeline_exit 0
fi

# Agent 2: Review
log_info ""
log_info "=========================================="
log_info "AGENT 2: Review (AI assessment)"
log_info "=========================================="

set +e
python3 -m alert_agent.pipeline.review --config "$CONFIG_FILE" 2>&1 | tee -a "$LOG_DIR/review-$(date +%Y%m%d).log"
REVIEW_EXIT=${PIPESTATUS[0]}
set -e

APPROVED_COUNT=$(count_modified_files "output/alerts/approved" "*.json")
PENDING_COUNT=$(count_modified_files "output/alerts/pending" "*.json")
log_info "Review complete: $APPROVED_COUNT auto-approved, $PENDING_COUNT pending (exit code: $REVIEW_EXIT)"

if [ $REVIEW_EXIT -eq 1 ]; then
    FAILURE_STAGE="review"
    log_error "Review agent failed"
    pipeline_exit 1
elif [ $REVIEW_EXIT -eq 0 ]; then
    log_warn "No issues auto-approved, check pending/ for manual review"
    pipeline_exit 0
elif [ $REVIEW_EXIT -eq 2 ]; then
    log_success "Issues auto-approved, continuing to recommendations"
else
    log_warn "Unexpected exit code from review: $REVIEW_EXIT"
fi

if [ "$BUDGET_ENFORCEMENT_ACTIVE" = "true" ] && [ "$BUDGET_ENFORCEMENT_MODE" = "disable_recommendation_ai" ]; then
    RECOMMENDATION_DRY_RUN="--dry-run"
    log_warn "Running recommendation agent in fallback mode because budget enforcement disables recommendation AI"
fi

# Agent 3: Recommendation
log_info ""
log_info "=========================================="
log_info "AGENT 3: Recommendation (AI generation)"
log_info "=========================================="

set +e
python3 -m alert_agent.pipeline.recommendation --config "$CONFIG_FILE" $RECOMMENDATION_DRY_RUN 2>&1 | tee -a "$LOG_DIR/recommendation-$(date +%Y%m%d).log"
RECO_EXIT=${PIPESTATUS[0]}
set -e

RECO_COUNT=$(count_modified_files "output/alerts/recommendations" "*.md")
log_info "Recommendations generated: $RECO_COUNT (exit code: $RECO_EXIT)"

if [ $RECO_EXIT -eq 1 ]; then
    FAILURE_STAGE="recommendation"
    log_error "Recommendation agent failed"
    pipeline_exit 1
elif [ $RECO_EXIT -eq 0 ]; then
    log_warn "No recommendations generated"
    pipeline_exit 0
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

set +e
python3 -m alert_agent.pipeline.sender --config "$CONFIG_FILE" 2>&1 | tee -a "$LOG_DIR/sender-$(date +%Y%m%d).log"
SENDER_EXIT=${PIPESTATUS[0]}
set -e

SENT_COUNT=$(count_modified_files "output/alerts/sent" "*.md")
log_info "Sent to Teams: $SENT_COUNT (exit code: $SENDER_EXIT)"

if [ $SENDER_EXIT -eq 0 ]; then
    log_success "Sender complete"
else
    FAILURE_STAGE="sender"
    log_error "Sender failed"
    pipeline_exit 1
fi

# Summary
log_info ""
log_info "=========================================="
log_info "Pipeline Complete"
log_info "=========================================="
log_info "Triaged: $TRIAGE_COUNT | Auto-approved: $APPROVED_COUNT | Pending Review: $PENDING_COUNT | Sent: $SENT_COUNT"
log_success "All agents completed successfully"
pipeline_exit 0
