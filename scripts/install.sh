#!/bin/bash
#
# Sentry Alert Agent - Installation Script
#
# This script installs and configures the Sentry Alert Agent on a workstation.
# Can be run on local machine for POC or on remote workstation for production.
#

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="${INSTALL_DIR:-/opt/sre-alert-agent}"
DATA_DIR="${DATA_DIR:-$INSTALL_DIR/output}"
LOG_DIR="${LOG_DIR:-$INSTALL_DIR/output/logs}"
ENV_FILE="${ENV_FILE:-$HOME/.config/sre-alert-agent.env}"
REPO_URL="${REPO_URL:-}" # Set if cloning from remote

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[!]${NC} $*"
}

log_error() {
    echo -e "${RED}[✗]${NC} $*"
}

check_command() {
    if command -v "$1" &> /dev/null; then
        log_success "$1 is installed"
        return 0
    else
        log_error "$1 is NOT installed"
        return 1
    fi
}

version_ge() {
    # Compare dotted versions: returns 0 if $1 >= $2
    [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]
}

# Banner
echo ""
echo "╔═══════════════════════════════════════════╗"
echo "║  Sentry Alert Agent - Installation        ║"
echo "╔═══════════════════════════════════════════╗"
echo ""

# Check if running as root for privileged install locations
if [[ "$INSTALL_DIR" == /opt/* || "$ENV_FILE" == /etc/* || "$DATA_DIR" == /var/* || "$LOG_DIR" == /var/* ]] && [ "$EUID" -ne 0 ]; then
    log_warn "Privileged install locations require root privileges"
    log_info "Run with sudo, or set INSTALL_DIR/ENV_FILE/DATA_DIR/LOG_DIR to user-writable locations:"
    log_info "  export INSTALL_DIR=\$HOME/sre-alert-agent"
    log_info "  export ENV_FILE=\$HOME/.config/sre-alert-agent.env"
    log_info "  ./scripts/install.sh"
    exit 1
fi

# Step 1: Check prerequisites
log_info "Step 1/7: Checking prerequisites..."

MISSING_DEPS=0

# Check Python 3.12+
if check_command python3; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    log_info "Python version: $PYTHON_VERSION"
    if ! version_ge "$PYTHON_VERSION" "3.12"; then
        log_error "Python 3.12 or newer is required"
        MISSING_DEPS=1
    fi
else
    log_error "Python 3 is required"
    MISSING_DEPS=1
fi

# Check jq
if ! check_command jq; then
    log_error "jq is required for JSON parsing"
    log_info "Install with: sudo apt-get install jq"
    MISSING_DEPS=1
fi

# Check pip3
if ! check_command pip3; then
    log_warn "pip3 not found, Python package installation may fail"
fi

# Check pi CLI
if check_command pi; then
    PI_VERSION=$(pi --version 2>&1 | head -1)
    log_info "pi CLI version: $PI_VERSION"
else
    log_error "pi CLI is required for AI functionality"
    log_info "Install with: npm install -g --ignore-scripts @earendil-works/pi-coding-agent"
    MISSING_DEPS=1
fi

# Check git
if ! check_command git; then
    log_error "git is required"
    log_info "Install with: sudo apt-get install git"
    MISSING_DEPS=1
fi

if [ $MISSING_DEPS -eq 1 ]; then
    log_error "Missing required dependencies. Please install them first."
    exit 1
fi

log_success "All prerequisites met"
echo ""

# Step 2: Install repository
log_info "Step 2/7: Installing repository..."

if [ -n "$REPO_URL" ]; then
    # Clone from remote
    log_info "Cloning from $REPO_URL..."
    if [ -d "$INSTALL_DIR" ]; then
        log_warn "Install directory already exists: $INSTALL_DIR"
        read -p "Remove and re-clone? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$INSTALL_DIR"
        else
            log_error "Installation aborted"
            exit 1
        fi
    fi
    git clone "$REPO_URL" "$INSTALL_DIR"
else
    # Copy from current directory (POC mode)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SOURCE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

    log_info "Installing from local directory: $SOURCE_DIR"

    if [ "$SOURCE_DIR" = "$INSTALL_DIR" ]; then
        log_info "Already in install directory, skipping copy"
    else
        if [ -d "$INSTALL_DIR" ]; then
            log_warn "Install directory already exists: $INSTALL_DIR"
            read -p "Remove and reinstall? (y/N) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                rm -rf "$INSTALL_DIR"
            else
                log_error "Installation aborted"
                exit 1
            fi
        fi

        mkdir -p "$INSTALL_DIR"
        cp -a "$SOURCE_DIR"/. "$INSTALL_DIR"/
        log_success "Copied files to $INSTALL_DIR"
    fi
fi

cd "$INSTALL_DIR"
log_success "Repository installed"
echo ""

# Step 3: Install Python dependencies
log_info "Step 3/7: Installing Python dependencies..."

# Check if PyYAML is installed
if python3 -c "import yaml" 2>/dev/null; then
    log_success "PyYAML already installed"
else
    log_info "Installing PyYAML..."
    pip3 install --user PyYAML || {
        log_error "Failed to install PyYAML"
        log_info "Please install manually: pip3 install PyYAML"
        exit 1
    }
    log_success "PyYAML installed"
fi

echo ""

# Step 4: Create directories
log_info "Step 4/7: Creating directories..."

# Create data directory
if [ ! -d "$DATA_DIR" ]; then
    mkdir -p "$DATA_DIR"
    log_success "Created data directory: $DATA_DIR"
fi

# Create output subdirectories
mkdir -p "$DATA_DIR/alerts"/{triage,reviewed,pending,approved,rejected,recommendations,sent,ignored}
mkdir -p "$DATA_DIR/logs"
log_success "Created output directories"

# Create log directory
if [ ! -d "$LOG_DIR" ]; then
    mkdir -p "$LOG_DIR"
    log_success "Created log directory: $LOG_DIR"
fi

# Create symlink from output/ to data directory
if [ "$INSTALL_DIR" != "$SOURCE_DIR" ]; then
    ln -sf "$DATA_DIR" "$INSTALL_DIR/output"
    log_success "Linked output/ -> $DATA_DIR"
fi

# Create env directory
ENV_DIR="$(dirname "$ENV_FILE")"
if [ ! -d "$ENV_DIR" ]; then
    mkdir -p "$ENV_DIR"
    log_success "Created env directory: $ENV_DIR"
fi

echo ""

# Step 5: Configure environment
log_info "Step 5/7: Configuring environment..."

if [ ! -f "$ENV_FILE" ]; then
    log_info "Creating environment file: $ENV_FILE"

    # Copy template
    cp "$INSTALL_DIR/.env.example" "$ENV_FILE"

    # Update paths in env file
    sed -i "s|SENTRY_OUTPUT_DIR=./output|SENTRY_OUTPUT_DIR=$DATA_DIR|g" "$ENV_FILE"

    log_success "Created environment file"
    log_warn "IMPORTANT: Edit $ENV_FILE with your credentials"
    log_info "Required variables:"
    log_info "  - SENTRY_BASE_URL"
    log_info "  - SENTRY_AUTH_TOKEN"
    log_info "  - SENTRY_ORG"
    log_info "  - AI_PROVIDER / AI_MODEL"
    log_info "  - Provider credentials (for example AZURE_OPENAI_API_KEY)"
    log_info "  - TEAMS_WEBHOOK_URL"
else
    log_info "Environment file already exists: $ENV_FILE"
fi

# Create .env symlink for easier access
if [ ! -f "$INSTALL_DIR/.env" ]; then
    ln -s "$ENV_FILE" "$INSTALL_DIR/.env"
    log_success "Linked .env -> $ENV_FILE"
fi

echo ""

# Step 6: Set permissions
log_info "Step 6/7: Setting permissions..."

# Make scripts executable
chmod +x "$INSTALL_DIR/scripts"/*.sh
chmod +x "$INSTALL_DIR/agents"/*.py
log_success "Made scripts executable"

# Set ownership (if running as root)
if [ "$EUID" -eq 0 ]; then
    OWNER="${SUDO_USER:-$USER}"
    log_info "Setting ownership to $OWNER..."
    chown -R "$OWNER:$OWNER" "$INSTALL_DIR" "$DATA_DIR" "$LOG_DIR"
    chmod 600 "$ENV_FILE"
    log_success "Set ownership and permissions"
else
    chmod 600 "$ENV_FILE"
    log_success "Set file permissions"
fi

echo ""

# Step 7: Test installation
log_info "Step 7/7: Testing installation..."

# Test pi CLI
if pi --print "test" > /dev/null 2>&1; then
    log_success "pi CLI is working"
else
    log_warn "pi CLI test failed (check API key configuration)"
fi

# Test Python imports
if python3 -c "import sys; sys.path.insert(0, '$INSTALL_DIR/agents'); from shared.config_loader import get_repo_root" 2>/dev/null; then
    log_success "Python imports working"
else
    log_warn "Python imports test failed"
fi

echo ""
echo "╔═══════════════════════════════════════════╗"
echo "║  Installation Complete!                   ║"
echo "╔═══════════════════════════════════════════╗"
echo ""

log_info "Installation directory: $INSTALL_DIR"
log_info "Data directory: $DATA_DIR"
log_info "Log directory: $LOG_DIR"
log_info "Environment file: $ENV_FILE"
echo ""

log_warn "Next Steps:"
echo "1. Edit environment file with your credentials:"
echo "   nano $ENV_FILE"
echo ""
echo "2. Test the configuration:"
echo "   cd $INSTALL_DIR"
echo "   source $ENV_FILE"
echo "   python3 agents/triage_agent.py --dry-run"
echo ""
echo "3. Run a test triage:"
echo "   ./scripts/run_triage.sh"
echo ""
echo "4. Set up cron for polling:"
echo "   crontab -e"
echo "   # Add this line:"
echo "   */15 * * * * cd $INSTALL_DIR && ./scripts/run_triage.sh --minutes 20 >> /var/log/alert-agent.log 2>&1"
echo ""

log_success "Installation script completed successfully!"
