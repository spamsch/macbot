#!/bin/bash
# ==============================================================================
# scroll.sh - Scroll an element into view by ref
# ==============================================================================
# Description:
#   Scrolls the page to bring an element into view.
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
            head -16 "$0" | tail -11
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

osascript -e '
on run argv
    set ref to item 1 of argv

    tell application "Safari"
        if (count of windows) is 0 then
            return "{\"success\": false, \"error\": \"No Safari window open\"}"
        end if

        try
            set hasLib to do JavaScript "typeof window.__ariaScrollTo === '\''function'\''" in current tab of front window
            if hasLib is not true then
                return "{\"success\": false, \"error\": \"ARIA library not loaded.\"}"
            end if
        on error errMsg
            return "{\"success\": false, \"error\": \"" & errMsg & "\"}"
        end try

        set jsCode to "JSON.stringify(window.__ariaScrollTo('\''" & ref & "'\''))"

        try
            set result to do JavaScript jsCode in current tab of front window
            return result
        on error errMsg
            return "{\"success\": false, \"error\": \"Scroll failed: " & errMsg & "\"}"
        end try
    end tell
end run
' -- "$REF"
