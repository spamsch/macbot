#!/bin/bash
# ==============================================================================
# type.sh - Type text into an element by ref in Safari
# ==============================================================================
# Description:
#   Types text into an input element identified by its ref from a snapshot.
#   By default clears the field first. Can optionally submit the form.
#
# Prerequisites:
#   - Run snapshot.sh first to generate refs
#
# Usage:
#   ./type.sh <ref> <text>
#   ./type.sh e2 "Hello World"
#   ./type.sh --no-clear e2 " appended text"
#   ./type.sh --submit e2 "search query"
#
# Options:
#   --no-clear    Don't clear the field before typing
#   --submit      Submit the form after typing (Enter key)
#
# Arguments:
#   ref     Element reference from snapshot (e.g., e1, e2)
#   text    Text to type into the element
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

CLEAR=true
SUBMIT=false
REF=""
TEXT=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-clear)
            CLEAR=false
            shift
            ;;
        --submit)
            SUBMIT=true
            shift
            ;;
        -h|--help)
            head -32 "$0" | tail -27
            exit 0
            ;;
        -*)
            error_exit "Unknown option: $1"
            ;;
        *)
            if [[ -z "$REF" ]]; then
                REF="$1"
            else
                TEXT="$1"
            fi
            shift
            ;;
    esac
done

[[ -z "$REF" ]] && error_exit "Element ref is required (e.g., e1)"
[[ -z "$TEXT" ]] && error_exit "Text is required"

# Check Safari window
WINDOW_COUNT=$(osascript -e 'tell application "Safari" to count of windows' 2>/dev/null)
if [[ "$WINDOW_COUNT" == "0" ]] || [[ -z "$WINDOW_COUNT" ]]; then
    echo '{"success": false, "error": "No Safari window open"}'
    exit 1
fi

# Check library
HAS_LIB=$(osascript -e 'tell application "Safari" to do JavaScript "typeof window.__ariaType === '\''function'\''" in current tab of front window' 2>/dev/null)
if [[ "$HAS_LIB" != "true" ]]; then
    echo '{"success": false, "error": "ARIA library not loaded. Run snapshot.sh --inject first."}'
    exit 1
fi

# Escape text for JavaScript (basic escaping)
TEXT_ESCAPED=$(echo "$TEXT" | sed "s/'/\\\\'/g" | sed 's/\\/\\\\/g')

# Small random delay before action - more human-like
sleep 0.$((RANDOM % 15 + 5))

# Type the text
RESULT=$(osascript -e "tell application \"Safari\" to do JavaScript \"JSON.stringify(window.__ariaType('$REF', '$TEXT_ESCAPED', {clear: $CLEAR, submit: $SUBMIT}))\" in current tab of front window" 2>&1)
EXIT_CODE=$?

# Delay after typing (simulate user pausing to review)
sleep 0.$((RANDOM % 20 + 10))

if [[ $EXIT_CODE -eq 0 ]]; then
    echo "$RESULT"
else
    echo "{\"success\": false, \"error\": \"Type failed: $RESULT\"}"
    exit 1
fi
