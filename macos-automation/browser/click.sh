#!/bin/bash
# ==============================================================================
# click.sh - Click an element by ref in Safari
# ==============================================================================
# Description:
#   Clicks an element identified by its ref from a previous snapshot.
#   The element is scrolled into view before clicking.
#
# Prerequisites:
#   - Run snapshot.sh first to generate refs
#
# Usage:
#   ./click.sh <ref>
#   ./click.sh e1
#   ./click.sh e5
#
# Arguments:
#   ref     Element reference from snapshot (e.g., e1, e2, e3)
#
# Output:
#   JSON with success status
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common utilities if available
if [[ -f "$SCRIPT_DIR/../lib/common.sh" ]]; then
    source "$SCRIPT_DIR/../lib/common.sh"
else
    error_exit() { echo "{\"success\": false, \"error\": \"$1\"}" >&2; exit 1; }
fi

# Parse arguments
REF=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            head -26 "$0" | tail -21
            exit 0
            ;;
        -*)
            error_exit "Unknown option: $1"
            ;;
        *)
            REF="$1"
            shift
            ;;
    esac
done

# Validate ref
[[ -z "$REF" ]] && error_exit "Element ref is required (e.g., e1)"

# Check if Safari window exists
WINDOW_COUNT=$(osascript -e 'tell application "Safari" to count of windows' 2>/dev/null)
if [[ "$WINDOW_COUNT" == "0" ]] || [[ -z "$WINDOW_COUNT" ]]; then
    echo '{"success": false, "error": "No Safari window open"}'
    exit 1
fi

# Check if library is loaded
HAS_LIB=$(osascript -e 'tell application "Safari" to do JavaScript "typeof window.__ariaClick === '\''function'\''" in current tab of front window' 2>/dev/null)
if [[ "$HAS_LIB" != "true" ]]; then
    echo '{"success": false, "error": "ARIA library not loaded. Run snapshot.sh --inject first."}'
    exit 1
fi

# Small random delay before action (50-200ms) - more human-like
sleep 0.$((RANDOM % 15 + 5))

# Click the element
RESULT=$(osascript -e "tell application \"Safari\" to do JavaScript \"JSON.stringify(window.__ariaClick('$REF'))\" in current tab of front window" 2>&1)
EXIT_CODE=$?

# Small delay after click for page to respond
sleep 0.$((RANDOM % 10 + 3))

if [[ $EXIT_CODE -eq 0 ]]; then
    echo "$RESULT"
else
    echo "{\"success\": false, \"error\": \"Click failed: $RESULT\"}"
    exit 1
fi
