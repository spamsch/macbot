#!/bin/bash
# ==============================================================================
# visual-snapshot.sh - Take a screenshot with ref labels overlaid
# ==============================================================================
# Description:
#   Overlays ref labels (e1, e2, etc.) on interactive elements and takes a
#   screenshot. This combines visual context with precise element references,
#   allowing LLMs to see what's on the page and know which ref to use.
#
# Usage:
#   ./visual-snapshot.sh
#   ./visual-snapshot.sh --output /path/to/screenshot.png
#   ./visual-snapshot.sh --max 50
#
# Options:
#   --output <path>   Save screenshot to file (default: /tmp/visual_snapshot.png)
#   --max <n>         Maximum number of elements to label (default: 80)
#
# Output:
#   JSON with screenshot path and element refs
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/../lib/common.sh" ]]; then
    source "$SCRIPT_DIR/../lib/common.sh"
else
    error_exit() { echo "{\"success\": false, \"error\": \"$1\"}" >&2; exit 1; }
fi

OUTPUT="/tmp/visual_snapshot.png"
MAX_ELEMENTS=80

while [[ $# -gt 0 ]]; do
    case $1 in
        --output)
            OUTPUT="$2"
            shift 2
            ;;
        --max)
            MAX_ELEMENTS="$2"
            shift 2
            ;;
        -h|--help)
            head -24 "$0" | tail -19
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

# Show labels and get snapshot
LABEL_RESULT=$(osascript -e "tell application \"Safari\" to do JavaScript \"JSON.stringify(window.__ariaShowLabels({max_elements: $MAX_ELEMENTS}))\" in current tab of front window" 2>&1)

if [[ $? -ne 0 ]]; then
    echo "{\"success\": false, \"error\": \"Failed to show labels: $LABEL_RESULT\"}"
    exit 1
fi

# Small delay for labels to render
sleep 0.3

# Take screenshot
screencapture -l$(osascript -e 'tell application "Safari" to id of front window' 2>/dev/null) "$OUTPUT" 2>/dev/null

# Hide labels (suppress output)
osascript -e 'tell application "Safari" to do JavaScript "window.__ariaHideLabels()" in current tab of front window' >/dev/null 2>&1

if [[ -f "$OUTPUT" ]]; then
    # Parse the label result to get label count
    LABELS_ADDED=$(echo "$LABEL_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('labels_added', 0))" 2>/dev/null)
    if [[ -z "$LABELS_ADDED" ]]; then
        LABELS_ADDED=0
    fi

    # Output clean JSON result
    printf '{"success": true, "screenshot": "%s", "labels_count": %s}\n' "$OUTPUT" "$LABELS_ADDED"
else
    echo '{"success": false, "error": "Failed to capture screenshot"}'
    exit 1
fi
