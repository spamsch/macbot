#!/bin/bash
# ==============================================================================
# navigate.sh - Navigate Safari to a URL
# ==============================================================================
# Description:
#   Opens Safari and navigates to the specified URL. Waits for page to load.
#   Injects the ARIA snapshot library for subsequent interactions.
#
# Prerequisites:
#   Safari > Settings > Advanced > Show Develop menu
#   Develop > Allow JavaScript from Apple Events
#
# Usage:
#   ./navigate.sh <url>
#   ./navigate.sh --new-tab <url>
#   ./navigate.sh --timeout 30 <url>
#
# Options:
#   --new-tab       Open URL in a new tab
#   --timeout <s>   Wait timeout in seconds (default: 20)
#
# Output:
#   JSON with success status and page info
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source common utilities if available
if [[ -f "$SCRIPT_DIR/../lib/common.sh" ]]; then
    source "$SCRIPT_DIR/../lib/common.sh"
else
    error_exit() { echo "{\"success\": false, \"error\": \"$1\"}" >&2; exit 1; }
fi

# Default values
NEW_TAB=false
TIMEOUT=20
URL=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --new-tab)
            NEW_TAB=true
            shift
            ;;
        --timeout)
            TIMEOUT="$2"
            shift 2
            ;;
        -h|--help)
            head -30 "$0" | tail -25
            exit 0
            ;;
        -*)
            error_exit "Unknown option: $1"
            ;;
        *)
            URL="$1"
            shift
            ;;
    esac
done

# Validate URL
[[ -z "$URL" ]] && error_exit "URL is required"

# Path to ARIA library
ARIA_LIB_PATH="$SCRIPT_DIR/lib/aria-snapshot.js"
if [[ ! -f "$ARIA_LIB_PATH" ]]; then
    error_exit "Could not find aria-snapshot.js library"
fi

# Run AppleScript
osascript << EOF
set targetUrl to "$URL"
set newTab to "$NEW_TAB"
set timeoutSec to $TIMEOUT
set libPath to "$ARIA_LIB_PATH"

tell application "Safari"
    activate

    if newTab is "true" then
        if (count of windows) is 0 then
            make new document with properties {URL:targetUrl}
        else
            tell front window
                set newT to make new tab with properties {URL:targetUrl}
                set current tab to newT
            end tell
        end if
    else
        if (count of windows) is 0 then
            make new document with properties {URL:targetUrl}
        else
            set URL of current tab of front window to targetUrl
        end if
    end if

    -- Wait for page to load
    set startTime to current date
    set loaded to false

    repeat
        try
            set readyState to do JavaScript "document.readyState" in current tab of front window
            if readyState is "complete" then
                set loaded to true
                exit repeat
            end if
        on error errMsg
            if errMsg contains "Allow JavaScript from Apple Events" then
                return "{\"success\": false, \"error\": \"JavaScript from Apple Events not enabled in Safari. Enable in Develop menu.\"}"
            end if
        end try

        delay 0.5

        if ((current date) - startTime) > timeoutSec then
            exit repeat
        end if
    end repeat

    if not loaded then
        return "{\"success\": false, \"error\": \"Page load timeout after " & timeoutSec & " seconds\"}"
    end if

    -- Longer delay for dynamic content (helps avoid bot detection)
    delay 1.5

    -- Inject ARIA snapshot library by reading from file
    try
        set ariaLib to read POSIX file libPath
        do JavaScript ariaLib in current tab of front window
    on error errMsg
        return "{\"success\": false, \"error\": \"Failed to inject ARIA library: " & errMsg & "\"}"
    end try

    -- Wait for page stability (dynamic content to finish loading)
    delay 0.5

    -- Try to dismiss cookie consent banners
    try
        do JavaScript "window.__ariaDismissCookies()" in current tab of front window
        delay 0.5
    end try

    -- Get page info
    set pageUrl to URL of current tab of front window
    set pageTitle to name of current tab of front window

    -- Simple JSON output (title may have issues with quotes)
    return "{" & quote & "success" & quote & ": true, " & quote & "url" & quote & ": " & quote & pageUrl & quote & ", " & quote & "title" & quote & ": " & quote & pageTitle & quote & "}"
end tell
EOF
