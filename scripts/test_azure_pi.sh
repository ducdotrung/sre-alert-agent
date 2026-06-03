#!/bin/bash
#
# Azure OpenAI smoke test for pi
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[✓]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $*"; }
log_error() { echo -e "${RED}[✗]${NC} $*"; }

if [ ! -f ".env" ]; then
    log_error ".env file not found"
    log_info "Expected: $REPO_ROOT/.env"
    exit 1
fi

set -a
source .env
set +a

REQUIRED_VARS=(
    AI_PROVIDER
    AI_MODEL
    AZURE_OPENAI_API_KEY
    AZURE_OPENAI_BASE_URL
)

MISSING=0
for VAR_NAME in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!VAR_NAME:-}" ]; then
        log_error "$VAR_NAME is not set"
        MISSING=1
    else
        log_success "$VAR_NAME is set"
    fi
done

if [ "${AI_PROVIDER:-}" != "azure-openai-responses" ]; then
    log_warn "AI_PROVIDER is '${AI_PROVIDER:-}', expected 'azure-openai-responses'"
fi

if [ $MISSING -eq 1 ]; then
    log_error "Fill the Azure OpenAI values in .env before testing"
    exit 1
fi

export PI_CODING_AGENT_DIR="${PI_CODING_AGENT_DIR:-/tmp/pi-test}"
mkdir -p "$PI_CODING_AGENT_DIR"

log_info "Testing Azure OpenAI via pi"
log_info "Provider: $AI_PROVIDER"
log_info "Model: $AI_MODEL"

pi --no-session --provider "$AI_PROVIDER" --model "$AI_MODEL" --print "What is 2+2? Reply with just the number."

if [ -n "${AZURE_OPENAI_DEPLOYMENT_NAME_MAP:-}" ]; then
    log_info "Deployment map: $AZURE_OPENAI_DEPLOYMENT_NAME_MAP"
else
    log_warn "AZURE_OPENAI_DEPLOYMENT_NAME_MAP is empty"
    log_warn "Set it if your Azure deployment name differs from the model id"
fi
