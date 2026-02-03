#!/bin/bash
# ==============================================================================
# dismiss-cookies.sh - Dismiss cookie consent banners
# ==============================================================================
# Description:
#   Attempts to find and dismiss cookie consent banners/popups on the current
#   page. Uses common patterns to identify accept/dismiss buttons.
#
# Usage:
#   ./dismiss-cookies.sh
#
# Output:
#   JSON with success status and whether a banner was dismissed
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/../lib/common.sh" ]]; then
    source "$SCRIPT_DIR/../lib/common.sh"
else
    error_exit() { echo "{\"success\": false, \"error\": \"$1\"}" >&2; exit 1; }
fi

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            head -16 "$0" | tail -11
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
HAS_LIB=$(osascript -e 'tell application "Safari" to do JavaScript "typeof window.__ariaDismissCookies === '\''function'\''" in current tab of front window' 2>/dev/null)
if [[ "$HAS_LIB" != "true" ]]; then
    echo '{"success": false, "error": "ARIA library not loaded. Run snapshot.sh --inject first."}'
    exit 1
fi

# Dismiss cookies
RESULT=$(osascript -e 'tell application "Safari" to do JavaScript "JSON.stringify(window.__ariaDismissCookies())" in current tab of front window' 2>&1)

if [[ $? -eq 0 ]]; then
    echo "$RESULT"
else
    echo "{\"success\": false, \"error\": \"Dismiss cookies failed: $RESULT\"}"
    exit 1
fi
