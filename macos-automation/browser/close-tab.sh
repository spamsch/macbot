#!/bin/bash
# ==============================================================================
# close-tab.sh - Close the current Safari tab
# ==============================================================================
# Description:
#   Closes the current tab in Safari. If it's the last tab, closes the window.
#
# Usage:
#   ./close-tab.sh
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

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            head -14 "$0" | tail -9
            exit 0
            ;;
        *)
            error_exit "Unknown option: $1"
            ;;
    esac
done

osascript -e '
tell application "Safari"
    if (count of windows) is 0 then
        return "{\"success\": true, \"message\": \"No window to close\"}"
    end if

    try
        close current tab of front window
        return "{\"success\": true}"
    on error errMsg
        return "{\"success\": false, \"error\": \"" & errMsg & "\"}"
    end try
end tell
'
