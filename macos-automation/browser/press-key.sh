#!/bin/bash
# ==============================================================================
# press-key.sh - Press a keyboard key
# ==============================================================================
# Description:
#   Simulates pressing a keyboard key. Useful for dismissing overlays (Escape),
#   submitting forms (Enter), or navigation (Tab, Arrow keys).
#
# Usage:
#   ./press-key.sh <key>
#   ./press-key.sh escape
#   ./press-key.sh enter
#   ./press-key.sh tab
#
# Supported keys:
#   escape, enter, tab, space, backspace, arrowdown, arrowup, arrowleft, arrowright
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

KEY=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            head -22 "$0" | tail -17
            exit 0
            ;;
        -*)
            error_exit "Unknown option: $1"
            ;;
        *)
            KEY="$1"
            shift
            ;;
    esac
done

[[ -z "$KEY" ]] && error_exit "Key is required (e.g., escape, enter, tab)"

# Check Safari window
WINDOW_COUNT=$(osascript -e 'tell application "Safari" to count of windows' 2>/dev/null)
if [[ "$WINDOW_COUNT" == "0" ]] || [[ -z "$WINDOW_COUNT" ]]; then
    echo '{"success": false, "error": "No Safari window open"}'
    exit 1
fi

# Check library
HAS_LIB=$(osascript -e 'tell application "Safari" to do JavaScript "typeof window.__ariaPressKey === '\''function'\''" in current tab of front window' 2>/dev/null)
if [[ "$HAS_LIB" != "true" ]]; then
    echo '{"success": false, "error": "ARIA library not loaded. Run navigate or snapshot --inject first."}'
    exit 1
fi

# Small delay before action
sleep 0.$((RANDOM % 10 + 5))

# Press key
RESULT=$(osascript -e "tell application \"Safari\" to do JavaScript \"JSON.stringify(window.__ariaPressKey('$KEY'))\" in current tab of front window" 2>&1)
EXIT_CODE=$?

sleep 0.$((RANDOM % 10 + 3))

if [[ $EXIT_CODE -eq 0 ]]; then
    echo "$RESULT"
else
    echo "{\"success\": false, \"error\": \"Press key failed: $RESULT\"}"
    exit 1
fi
