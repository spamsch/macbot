#!/bin/bash
# ==============================================================================
# scroll.sh - Scroll an element into view by ref
# ==============================================================================
# Description:
#   Scrolls the page to bring an element into view.
#
# Prerequisites:
#   - Run snapshot.sh first to generate refs
#
# Usage:
#   ./scroll.sh <ref>
#   ./scroll.sh e10
#
# Output:
#   JSON with success status
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/../lib/common.sh" ]]; then
    source "$SCRIPT_DIR/../lib/common.sh"
else
    error_exit() { echo "{\"success\": false, \"error\": \"$1\"}" >&2; exit 1; }
fi

REF=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            head -18 "$0" | tail -13
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

[[ -z "$REF" ]] && error_exit "Element ref is required"

# Check if Safari window exists
WINDOW_COUNT=$(osascript -e 'tell application "Safari" to count of windows' 2>/dev/null)
if [[ "$WINDOW_COUNT" == "0" ]] || [[ -z "$WINDOW_COUNT" ]]; then
    echo '{"success": false, "error": "No Safari window open"}'
    exit 1
fi

# Check if library is loaded
HAS_LIB=$(osascript -e 'tell application "Safari" to do JavaScript "typeof window.__ariaScrollTo === '\''function'\''" in current tab of front window' 2>/dev/null)
if [[ "$HAS_LIB" != "true" ]]; then
    echo '{"success": false, "error": "ARIA library not loaded. Run snapshot.sh --inject first."}'
    exit 1
fi

# Scroll to the element
RESULT=$(osascript -e "tell application \"Safari\" to do JavaScript \"JSON.stringify(window.__ariaScrollTo('$REF'))\" in current tab of front window" 2>&1)
EXIT_CODE=$?

if [[ $EXIT_CODE -eq 0 ]] && [[ -n "$RESULT" ]]; then
    echo "$RESULT"
else
    echo "{\"success\": false, \"error\": \"Scroll failed: $RESULT\"}"
    exit 1
fi
