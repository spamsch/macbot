#!/bin/bash
# ==============================================================================
# show-labels.sh - Show ref labels on interactive elements
# ==============================================================================
# Description:
#   Overlays visual labels (e1, e2, etc.) on all interactive elements.
#   Useful for taking screenshots that show both visual context and refs.
#
# Usage:
#   ./show-labels.sh
#   ./show-labels.sh --max 50
#
# Options:
#   --max <n>    Maximum number of elements to label (default: 100)
#
# Output:
#   JSON with snapshot and label count
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/../lib/common.sh" ]]; then
    source "$SCRIPT_DIR/../lib/common.sh"
else
    error_exit() { echo "{\"success\": false, \"error\": \"$1\"}" >&2; exit 1; }
fi

MAX_ELEMENTS=100

while [[ $# -gt 0 ]]; do
    case $1 in
        --max)
            MAX_ELEMENTS="$2"
            shift 2
            ;;
        -h|--help)
            head -20 "$0" | tail -15
            exit 0
            ;;
        *)
            error_exit "Unknown option: $1"
            ;;
    esac
done

# Check Safari window
WINDOW_COUNT=$(osascript -e 'tell application "Safari" to count of windows' 2>/dev/null)
if [[ "$WINDOW_COUNT" == "0" ]] || [[ -z "$WINDOW_COUNT" ]]; then
    echo '{"success": false, "error": "No Safari window open"}'
    exit 1
fi

# Check library
HAS_LIB=$(osascript -e 'tell application "Safari" to do JavaScript "typeof window.__ariaShowLabels === '\''function'\''" in current tab of front window' 2>/dev/null)
if [[ "$HAS_LIB" != "true" ]]; then
    echo '{"success": false, "error": "ARIA library not loaded. Run navigate first."}'
    exit 1
fi

# Show labels
RESULT=$(osascript -e "tell application \"Safari\" to do JavaScript \"JSON.stringify(window.__ariaShowLabels({max_elements: $MAX_ELEMENTS}))\" in current tab of front window" 2>&1)

if [[ $? -eq 0 ]]; then
    echo "$RESULT"
else
    echo "{\"success\": false, \"error\": \"Show labels failed: $RESULT\"}"
    exit 1
fi
