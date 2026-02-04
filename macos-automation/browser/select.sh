#!/bin/bash
# ==============================================================================
# select.sh - Select an option in a dropdown by ref
# ==============================================================================
# Description:
#   Selects an option in a <select> element by value or text.
#
# Prerequisites:
#   - Run snapshot.sh first to generate refs
#
# Usage:
#   ./select.sh <ref> <value>
#   ./select.sh e3 "Option Text"
#
# Arguments:
#   ref     Element reference for the select (e.g., e3)
#   value   Option value or text to select
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
VALUE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            head -24 "$0" | tail -19
            exit 0
            ;;
        -*)
            error_exit "Unknown option: $1"
            ;;
        *)
            if [[ -z "$REF" ]]; then
                REF="$1"
            else
                VALUE="$1"
            fi
            shift
            ;;
    esac
done

[[ -z "$REF" ]] && error_exit "Element ref is required"
[[ -z "$VALUE" ]] && error_exit "Value is required"

# Check if Safari window exists
WINDOW_COUNT=$(osascript -e 'tell application "Safari" to count of windows' 2>/dev/null)
if [[ "$WINDOW_COUNT" == "0" ]] || [[ -z "$WINDOW_COUNT" ]]; then
    echo '{"success": false, "error": "No Safari window open"}'
    exit 1
fi

# Check if library is loaded
HAS_LIB=$(osascript -e 'tell application "Safari" to do JavaScript "typeof window.__ariaSelect === '\''function'\''" in current tab of front window' 2>/dev/null)
if [[ "$HAS_LIB" != "true" ]]; then
    echo '{"success": false, "error": "ARIA library not loaded. Run snapshot.sh --inject first."}'
    exit 1
fi

# Escape single quotes in value for JavaScript
VALUE_ESCAPED=$(echo "$VALUE" | sed "s/'/\\\\'/g")

# Select the option
RESULT=$(osascript -e "tell application \"Safari\" to do JavaScript \"JSON.stringify(window.__ariaSelect('$REF', '$VALUE_ESCAPED'))\" in current tab of front window" 2>&1)
EXIT_CODE=$?

if [[ $EXIT_CODE -eq 0 ]] && [[ -n "$RESULT" ]]; then
    echo "$RESULT"
else
    echo "{\"success\": false, \"error\": \"Select failed: $RESULT\"}"
    exit 1
fi
