#!/bin/bash
# ==============================================================================
# snapshot.sh - Get ARIA snapshot of current Safari page
# ==============================================================================
# Description:
#   Extracts an accessibility tree snapshot from the current Safari page.
#   Returns numbered refs (e1, e2, etc.) that can be used for interactions.
#
# Prerequisites:
#   - Page must be loaded via navigate.sh first (injects ARIA library)
#   - Or call with --inject to inject library first
#
# Usage:
#   ./snapshot.sh
#   ./snapshot.sh --inject
#   ./snapshot.sh --all          # Include non-interactive elements
#   ./snapshot.sh --max 100      # Limit number of elements
#
# Options:
#   --inject            Inject ARIA library before snapshot
#   --all               Include all elements, not just interactive
#   --max <n>           Maximum elements to include (default: 200)
#
# Output:
#   JSON with snapshot text and refs mapping
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common utilities if available
if [[ -f "$SCRIPT_DIR/../lib/common.sh" ]]; then
    source "$SCRIPT_DIR/../lib/common.sh"
else
    error_exit() { echo "{\"success\": false, \"error\": \"$1\"}" >&2; exit 1; }
fi

# Default values
INJECT=false
INTERACTIVE_ONLY=true
MAX_ELEMENTS=200

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --inject)
            INJECT=true
            shift
            ;;
        --all)
            INTERACTIVE_ONLY=false
            shift
            ;;
        --max)
            MAX_ELEMENTS="$2"
            shift 2
            ;;
        -h|--help)
            head -32 "$0" | tail -27
            exit 0
            ;;
        *)
            error_exit "Unknown option: $1"
            ;;
    esac
done

# Path to ARIA library (for --inject)
ARIA_LIB_PATH="$SCRIPT_DIR/lib/aria-snapshot.js"

# Run AppleScript
osascript << EOF
set shouldInject to "$INJECT"
set interactiveOnly to $INTERACTIVE_ONLY
set maxElements to $MAX_ELEMENTS
set libPath to "$ARIA_LIB_PATH"

tell application "Safari"
    if (count of windows) is 0 then
        return "{\"success\": false, \"error\": \"No Safari window open\"}"
    end if

    -- Inject library if requested
    if shouldInject is "true" then
        try
            set ariaLib to read POSIX file libPath
            do JavaScript ariaLib in current tab of front window
        on error errMsg
            return "{\"success\": false, \"error\": \"Failed to inject ARIA library: " & errMsg & "\"}"
        end try
    end if

    -- Check if library is available
    try
        set hasLib to do JavaScript "typeof window.__ariaSnapshot === 'function'" in current tab of front window
        if hasLib is not true then
            return "{\"success\": false, \"error\": \"ARIA library not loaded. Use navigate.sh first or --inject flag.\"}"
        end if
    on error errMsg
        if errMsg contains "Allow JavaScript from Apple Events" then
            return "{\"success\": false, \"error\": \"JavaScript from Apple Events not enabled in Safari.\"}"
        end if
        return "{\"success\": false, \"error\": \"" & errMsg & "\"}"
    end try

    -- Generate snapshot
    set jsOptions to "{ interactiveOnly: " & interactiveOnly & ", maxElements: " & maxElements & " }"
    set jsCode to "JSON.stringify(window.__ariaSnapshot(" & jsOptions & "))"

    try
        set result to do JavaScript jsCode in current tab of front window
        return result
    on error errMsg
        return "{\"success\": false, \"error\": \"Snapshot failed: " & errMsg & "\"}"
    end try
end tell
EOF
