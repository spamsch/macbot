#!/bin/bash
# ==============================================================================
# screenshot.sh - Take a screenshot of the current Safari page
# ==============================================================================
# Description:
#   Captures a screenshot of the current Safari window or visible tab.
#
# Usage:
#   ./screenshot.sh
#   ./screenshot.sh --output /path/to/screenshot.png
#
# Options:
#   --output <path>   Save screenshot to file (default: stdout as base64)
#
# Output:
#   JSON with base64 screenshot data or file path
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/../lib/common.sh" ]]; then
    source "$SCRIPT_DIR/../lib/common.sh"
else
    error_exit() { echo "{\"success\": false, \"error\": \"$1\"}" >&2; exit 1; }
fi

OUTPUT=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --output)
            OUTPUT="$2"
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

# Use screencapture for the Safari window
if [[ -n "$OUTPUT" ]]; then
    # Capture to file
    osascript -e '
    tell application "Safari"
        if (count of windows) is 0 then
            return "{\"success\": false, \"error\": \"No Safari window open\"}"
        end if
        set windowId to id of front window
        return windowId
    end tell
    ' > /dev/null 2>&1

    # Get Safari window bounds and capture
    screencapture -l$(osascript -e 'tell application "Safari" to id of front window') "$OUTPUT" 2>/dev/null

    if [[ -f "$OUTPUT" ]]; then
        echo "{\"success\": true, \"path\": \"$OUTPUT\"}"
    else
        # Fallback: use window capture
        screencapture -w "$OUTPUT" 2>/dev/null
        if [[ -f "$OUTPUT" ]]; then
            echo "{\"success\": true, \"path\": \"$OUTPUT\"}"
        else
            echo "{\"success\": false, \"error\": \"Failed to capture screenshot\"}"
        fi
    fi
else
    # Capture to temp file and return base64
    TEMP_FILE=$(mktemp /tmp/screenshot_XXXXXX.png)

    screencapture -l$(osascript -e 'tell application "Safari" to id of front window' 2>/dev/null) "$TEMP_FILE" 2>/dev/null

    if [[ -f "$TEMP_FILE" ]] && [[ -s "$TEMP_FILE" ]]; then
        BASE64_DATA=$(base64 < "$TEMP_FILE")
        rm -f "$TEMP_FILE"
        echo "{\"success\": true, \"data\": \"$BASE64_DATA\", \"format\": \"png\"}"
    else
        rm -f "$TEMP_FILE"
        echo "{\"success\": false, \"error\": \"Failed to capture screenshot\"}"
    fi
fi
