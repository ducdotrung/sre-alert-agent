#!/bin/bash
#
# POC Test Script - Test agents locally without full installation
#
# This script tests each agent individually with dry-run modes
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[✓]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $*"; }
log_error() { echo -e "${RED}[✗]${NC} $*"; }

echo ""
echo "╔═══════════════════════════════════════════╗"
echo "║  Sentry Alert Agent - POC Test           ║"
echo "╔═══════════════════════════════════════════╗"
echo ""

# Check .env exists
if [ ! -f ".env" ]; then
    log_error ".env file not found"
    log_info "Copy .env.example and configure it:"
    log_info "  cp .env.example .env"
    log_info "  nano .env"
    exit 1
fi

# Load environment
log_info "Loading environment from .env..."
set -a
# Use export to make vars available to subprocesses
export $(grep -v '^#' .env | grep -v '^$' | xargs)
set +a
log_success "Environment loaded"

# Check required variables
MISSING_VARS=0

check_var() {
    VAR_NAME=$1
    if [ -z "${!VAR_NAME:-}" ]; then
        log_error "$VAR_NAME is not set"
        MISSING_VARS=1
    else
        log_success "$VAR_NAME is set"
    fi
}

log_info "Checking required environment variables..."
check_var "SENTRY_BASE_URL"
check_var "SENTRY_AUTH_TOKEN"

AI_PROVIDER="${AI_PROVIDER:-azure-openai-responses}"
AI_MODEL="${AI_MODEL:-}"

case "$AI_PROVIDER" in
    azure-openai|azure-openai-chat|azure-openai-responses)
        check_var "AZURE_OPENAI_API_KEY"
        check_var "AZURE_OPENAI_BASE_URL"
        ;;
    deepseek)
        check_var "DEEPSEEK_API_KEY"
        ;;
    openai)
        check_var "OPENAI_API_KEY"
        ;;
    google|gemini)
        check_var "GEMINI_API_KEY"
        ;;
    *)
        if [ -z "${AI_API_KEY:-}" ]; then
            log_warn "AI_PROVIDER=$AI_PROVIDER is set, but no provider-specific key check is defined"
            log_warn "Set AI_API_KEY or ensure pi can read the provider credentials from your environment"
        else
            log_success "AI_API_KEY is set"
        fi
        ;;
esac

if [ $MISSING_VARS -eq 1 ]; then
    log_error "Missing required environment variables"
    log_info "Edit .env and set the missing variables"
    exit 1
fi

echo ""

# Test 1: pi CLI
log_info "═══════════════════════════════════════"
log_info "Test 1: pi CLI Connection"
log_info "═══════════════════════════════════════"

PI_CMD=(pi --provider "$AI_PROVIDER" --print "What is 2+2? Reply with just the number.")
if [ -n "$AI_MODEL" ]; then
    PI_CMD=(pi --provider "$AI_PROVIDER" --model "$AI_MODEL" --print "What is 2+2? Reply with just the number.")
fi

if "${PI_CMD[@]}" 2>&1 | grep -q "4"; then
    log_success "pi CLI is working with provider: $AI_PROVIDER"
else
    log_error "pi CLI test failed"
    log_info "Check AI_PROVIDER/AI_MODEL and the matching API credentials in .env"
    exit 1
fi

echo ""

# Test 2: Sentry API
log_info "═══════════════════════════════════════"
log_info "Test 2: Sentry API Connection"
log_info "═══════════════════════════════════════"

SENTRY_TEST=$(curl -s -w "%{http_code}" -o /tmp/sentry-test.json \
    -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
    "$SENTRY_BASE_URL/api/0/" 2>/dev/null || echo "000")

if [ "$SENTRY_TEST" = "200" ]; then
    log_success "Sentry API connection successful"
else
    log_error "Sentry API connection failed (HTTP $SENTRY_TEST)"
    log_info "Check SENTRY_BASE_URL and SENTRY_AUTH_TOKEN in .env"
    exit 1
fi

echo ""

# Test 3: Triage Agent (dry-run, no AI)
log_info "═══════════════════════════════════════"
log_info "Test 3: Triage Agent (dry-run)"
log_info "═══════════════════════════════════════"

log_info "Running triage agent (no AI calls)..."
env $(grep -v '^#' .env | grep -v '^$' | xargs) python3 agents/triage_agent.py --hours 24 --dry-run 2>&1 | tee /tmp/triage-test.log
TRIAGE_EXIT=$?

TRIAGE_COUNT=$(ls -1 output/alerts/triage/*.json 2>/dev/null | wc -l | tr -d ' ')

if [ $TRIAGE_EXIT -eq 0 ]; then
    log_success "Triage agent completed: $TRIAGE_COUNT issues processed (no critical issues)"
elif [ $TRIAGE_EXIT -eq 2 ]; then
    log_success "Triage agent completed: $TRIAGE_COUNT issues processed (critical issues found!)"
else
    log_error "Triage agent failed with exit code $TRIAGE_EXIT"
    cat /tmp/triage-test.log
    exit 1
fi

if [ "$TRIAGE_COUNT" -gt 0 ]; then
    log_info "Sample triage result:"
    ls -1 output/alerts/triage/*.json | head -1 | xargs cat | jq '.final' 2>/dev/null || cat
fi

echo ""

# Test 4: Review Agent (if critical issues found)
log_info "═══════════════════════════════════════"
log_info "Test 4: Review Agent (AI-Powered)"
log_info "═══════════════════════════════════════"

# Check if any P0/P1 issues exist
P0_P1_COUNT=$(jq -r 'select(.final.priority == "P0" or .final.priority == "P1") | .issue_id' output/alerts/triage/*.json 2>/dev/null | wc -l | tr -d ' ')

if [ "$P0_P1_COUNT" -gt 0 ]; then
    log_info "Found $P0_P1_COUNT critical issues, running review agent..."

    env $(grep -v '^#' .env | grep -v '^$' | xargs) python3 agents/review_agent.py 2>&1 | tee /tmp/review-test.log
    REVIEW_EXIT=$?

    APPROVED_COUNT=$(ls -1 output/alerts/approved/*.json 2>/dev/null | wc -l | tr -d ' ')
    PENDING_COUNT=$(ls -1 output/alerts/pending/*.json 2>/dev/null | wc -l | tr -d ' ')

    if [ $REVIEW_EXIT -eq 0 ]; then
        log_success "Review agent completed: $APPROVED_COUNT approved, $PENDING_COUNT pending (no auto-approvals)"
    elif [ $REVIEW_EXIT -eq 2 ]; then
        log_success "Review agent completed: $APPROVED_COUNT approved, $PENDING_COUNT pending (issues auto-approved!)"
    else
        log_error "Review agent failed with exit code $REVIEW_EXIT"
        cat /tmp/review-test.log
        exit 1
    fi

    if [ "$APPROVED_COUNT" -gt 0 ]; then
        log_info "Auto-approved issues:"
        ls -1 output/alerts/approved/*.json | head -5 | while read -r file; do
            ISSUE_ID=$(jq -r '.issue_id' "$file")
            PRIORITY=$(jq -r '.final.priority' "$file")
            CONFIDENCE=$(jq -r '.review.confidence' "$file")
            DECISION=$(jq -r '.review.decision' "$file")
            echo "  - $ISSUE_ID [$PRIORITY] confidence: $CONFIDENCE, decision: $DECISION"
        done
    fi

    if [ "$PENDING_COUNT" -gt 0 ]; then
        log_info "Pending review issues (need manual approval):"
        ls -1 output/alerts/pending/*.json | head -5 | while read -r file; do
            ISSUE_ID=$(jq -r '.issue_id' "$file")
            PRIORITY=$(jq -r '.final.priority' "$file")
            CONFIDENCE=$(jq -r '.review.confidence' "$file")
            DECISION=$(jq -r '.review.decision' "$file")
            echo "  - $ISSUE_ID [$PRIORITY] confidence: $CONFIDENCE, decision: $DECISION"
        done
    fi
else
    log_warn "No critical (P0/P1) issues found, skipping review agent test"
    log_info "This is normal if your Sentry instance has no critical issues"
fi

echo ""

# Test 5: Recommendation Agent (if approved issues found)
log_info "═══════════════════════════════════════"
log_info "Test 5: Recommendation Agent"
log_info "═══════════════════════════════════════"

APPROVED_COUNT=$(ls -1 output/alerts/approved/*.json 2>/dev/null | wc -l | tr -d ' ')

if [ "$APPROVED_COUNT" -gt 0 ]; then
    log_info "Found $APPROVED_COUNT approved issues, testing recommendation agent..."

    if env $(grep -v '^#' .env | grep -v '^$' | xargs) python3 agents/recommendation_agent.py 2>&1 | tee /tmp/recommendation-test.log; then
        RECO_COUNT=$(ls -1 output/alerts/recommendations/*.md 2>/dev/null | wc -l | tr -d ' ')
        log_success "Recommendation agent completed: $RECO_COUNT recommendations generated"

        if [ "$RECO_COUNT" -gt 0 ]; then
            log_info "Sample recommendation:"
            ls -1 output/alerts/recommendations/*.md | head -1 | xargs head -30
        fi
    else
        log_error "Recommendation agent failed"
        cat /tmp/recommendation-test.log
        exit 1
    fi
else
    log_warn "No approved issues found, skipping recommendation agent test"
fi

echo ""

# Test 6: Sender (dry-run)
log_info "═══════════════════════════════════════"
log_info "Test 6: Sender (dry-run, no Teams)"
log_info "═══════════════════════════════════════"

RECO_COUNT=$(ls -1 output/alerts/recommendations/*.md 2>/dev/null | wc -l | tr -d ' ')

if [ "$RECO_COUNT" -gt 0 ]; then
    log_info "Testing sender (dry-run, will not actually send to Teams)..."

    if env $(grep -v '^#' .env | grep -v '^$' | xargs) python3 agents/sender.py --dry-run 2>&1 | tee /tmp/sender-test.log; then
        log_success "Sender test completed (dry-run)"
        log_info "Teams message card preview shown above"
    else
        log_error "Sender test failed"
        cat /tmp/sender-test.log
        exit 1
    fi
else
    log_warn "No recommendations found, skipping sender test"
fi

echo ""

# Summary
log_info "═══════════════════════════════════════"
log_info "POC Test Summary"
log_info "═══════════════════════════════════════"

TRIAGE_COUNT=$(ls -1 output/alerts/triage/*.json 2>/dev/null | wc -l | tr -d ' ')
APPROVED_COUNT=$(ls -1 output/alerts/approved/*.json 2>/dev/null | wc -l | tr -d ' ')
PENDING_COUNT=$(ls -1 output/alerts/pending/*.json 2>/dev/null | wc -l | tr -d ' ')
RECO_COUNT=$(ls -1 output/alerts/recommendations/*.md 2>/dev/null | wc -l | tr -d ' ')

echo "Results:"
echo "  Triaged: $TRIAGE_COUNT issues"
echo "  Auto-approved: $APPROVED_COUNT issues"
echo "  Pending review: $PENDING_COUNT issues"
echo "  Recommendations: $RECO_COUNT generated"
echo ""

if [ "$APPROVED_COUNT" -gt 0 ]; then
    log_success "POC test successful! System is working end-to-end."
    echo ""
    log_info "Next steps:"
    echo "1. Review approved issues in: output/alerts/approved/"
    echo "2. Review recommendations in: output/alerts/recommendations/"
    echo "3. Test actual Teams sending:"
    echo "   python3 agents/sender.py"
    echo "4. Set up cron for production:"
    echo "   crontab -e"
    echo "   0 * * * * cd $(pwd) && ./scripts/run_triage.sh"
elif [ "$TRIAGE_COUNT" -gt 0 ]; then
    log_success "POC test successful! No critical issues in last 24h."
    echo ""
    log_info "This is normal if your Sentry has no recent critical errors."
    log_info "Try with longer lookback:"
    echo "  python3 agents/triage_agent.py --hours 168  # 7 days"
else
    log_warn "No issues found. Check your Sentry configuration."
    log_info "Verify SENTRY_ORG, SENTRY_PROJECTS in .env"
fi

echo ""
log_success "All tests completed!"
