#!/bin/bash
# Validates that Claude Code hooks are properly installed and working
#
# Usage:
#   ./scripts/validate-hooks.sh              # Validate local installation
#   ./scripts/validate-hooks.sh --container  # Validate container installation
#
# Exit codes:
#   0 - All validations passed
#   1 - One or more validations failed

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Logging functions
log_ok() { echo -e "${GREEN}✅${NC} $*"; }
log_fail() { echo -e "${RED}❌${NC} $*"; }
log_warn() { echo -e "${YELLOW}⚠️${NC} $*"; }
log_info() { echo -e "   $*"; }

# Default settings path (local)
SETTINGS_FILE="${HOME}/.claude/settings.json"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --container)
            SETTINGS_FILE="/home/claude/.claude/settings.json"
            shift
            ;;
        --settings)
            SETTINGS_FILE="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--container] [--settings PATH]"
            echo ""
            echo "Options:"
            echo "  --container    Use container settings path (/home/claude/.claude/settings.json)"
            echo "  --settings     Specify custom settings.json path"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=== Hook Installation Validation ==="
echo ""
echo "Settings file: ${SETTINGS_FILE}"
echo ""

FAILED=0

# Check 1: Settings file exists
if [[ ! -f "$SETTINGS_FILE" ]]; then
    log_fail "Settings file not found: ${SETTINGS_FILE}"
    exit 1
fi
log_ok "Settings file exists"

# Check 2: jq is available
if ! command -v jq &>/dev/null; then
    log_fail "jq not installed - required for validation"
    exit 1
fi
log_ok "jq available"

# Check 3: Hooks section exists
HOOKS=$(jq '.hooks // null' "$SETTINGS_FILE")
if [[ "$HOOKS" == "null" ]]; then
    log_fail "No hooks section in settings.json"
    exit 1
fi
log_ok "Hooks section exists"

# Check 4: Required hook types present
echo ""
echo "Checking required hook types..."
for HOOK in "PreToolUse" "PostToolUse" "SessionStart" "SessionEnd"; do
    if jq -e ".hooks.$HOOK" "$SETTINGS_FILE" > /dev/null 2>&1; then
        log_ok "$HOOK hooks present"
    else
        log_fail "Missing $HOOK hooks"
        FAILED=1
    fi
done

# Check 5: Bash hooks specifically
echo ""
echo "Checking Bash tool hooks..."
BASH_PRE=$(jq '.hooks.PreToolUse[]? | select(.matcher == "Bash")' "$SETTINGS_FILE" 2>/dev/null)
if [[ -n "$BASH_PRE" ]]; then
    log_ok "Bash PreToolUse hook configured"
else
    log_fail "Missing Bash PreToolUse hook"
    FAILED=1
fi

BASH_POST=$(jq '.hooks.PostToolUse[]? | select(.matcher == "Bash")' "$SETTINGS_FILE" 2>/dev/null)
if [[ -n "$BASH_POST" ]]; then
    log_ok "Bash PostToolUse hook configured"
else
    log_fail "Missing Bash PostToolUse hook"
    FAILED=1
fi

# Check 6: Write/Edit hooks
echo ""
echo "Checking Write/Edit tool hooks..."
EDIT_PRE=$(jq '.hooks.PreToolUse[]? | select(.matcher | test("Write|Edit"))' "$SETTINGS_FILE" 2>/dev/null)
if [[ -n "$EDIT_PRE" ]]; then
    log_ok "Write/Edit PreToolUse hook configured"
else
    log_warn "Missing Write/Edit PreToolUse hook (optional)"
fi

EDIT_POST=$(jq '.hooks.PostToolUse[]? | select(.matcher | test("Write|Edit"))' "$SETTINGS_FILE" 2>/dev/null)
if [[ -n "$EDIT_POST" ]]; then
    log_ok "Write/Edit PostToolUse hook configured"
else
    log_warn "Missing Write/Edit PostToolUse hook (optional)"
fi

# Check 7: Hook dependencies available (only for local installs)
if [[ "$SETTINGS_FILE" == "${HOME}/.claude/settings.json" ]]; then
    echo ""
    echo "Checking hook dependencies..."

    if command -v npx &> /dev/null; then
        log_ok "npx available"
    else
        log_fail "npx not found"
        FAILED=1
    fi

    if command -v python3 &> /dev/null; then
        log_ok "python3 available"
    else
        log_warn "python3 not found (some hooks may not work)"
    fi
fi

# Summary
echo ""
echo "=== Validation Summary ==="
if [[ $FAILED -eq 0 ]]; then
    log_ok "All required validations passed"
    exit 0
else
    log_fail "Some validations failed"
    exit 1
fi
