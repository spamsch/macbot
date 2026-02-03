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

VALUE_ESCAPED=$(echo "$VALUE" | sed "s/'/\\\\'/g")

osascript -e '
on run argv
    set ref to item 1 of argv
    set theValue to item 2 of argv

    tell application "Safari"
        if (count of windows) is 0 then
            return "{\"success\": false, \"error\": \"No Safari window open\"}"
        end if

        try
            set hasLib to do JavaScript "typeof window.__ariaSelect === '\''function'\''" in current tab of front window
            if hasLib is not true then
                return "{\"success\": false, \"error\": \"ARIA library not loaded.\"}"
            end if
        on error errMsg
            return "{\"success\": false, \"error\": \"" & errMsg & "\"}"
        end try

        set jsCode to "JSON.stringify(window.__ariaSelect('\''" & ref & "'\'', '\''" & theValue & "'\''))"

        try
            set result to do JavaScript jsCode in current tab of front window
            return result
        on error errMsg
            return "{\"success\": false, \"error\": \"Select failed: " & errMsg & "\"}"
        end try
    end tell
end run
' -- "$REF" "$VALUE_ESCAPED"
