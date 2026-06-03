#!/bin/bash
#
# Clear Sentry Alert Agent cache
#
# Usage:
#   ./scripts/clear_cache.sh [--all|--projects|--help]
#

set -euo pipefail

CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/sentry-alert-agent"

show_help() {
    cat << EOF
Clear Sentry Alert Agent cache

Usage:
  $0 [OPTIONS]

Options:
  --all        Clear all cached data
  --projects   Clear project ID mappings only (default)
  --help       Show this help message

Cache location: $CACHE_DIR

Examples:
  $0                    # Clear project cache
  $0 --all              # Clear everything
EOF
}

clear_projects() {
    if [ -d "$CACHE_DIR" ]; then
        rm -f "$CACHE_DIR"/projects_*.json
        echo "✓ Cleared project cache: $CACHE_DIR/projects_*.json"
    else
        echo "✓ Cache directory doesn't exist: $CACHE_DIR"
    fi
}

clear_all() {
    if [ -d "$CACHE_DIR" ]; then
        rm -rf "$CACHE_DIR"
        echo "✓ Cleared all cache: $CACHE_DIR"
    else
        echo "✓ Cache directory doesn't exist: $CACHE_DIR"
    fi
}

# Parse arguments
case "${1:-}" in
    --all)
        clear_all
        ;;
    --projects|"")
        clear_projects
        ;;
    --help|-h)
        show_help
        ;;
    *)
        echo "Error: Unknown option: $1"
        echo ""
        show_help
        exit 1
        ;;
esac
