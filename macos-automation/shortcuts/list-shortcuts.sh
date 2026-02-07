#!/bin/bash
# ==============================================================================
# list-shortcuts.sh - List available macOS Shortcuts
# ==============================================================================
# Lists shortcuts from the Shortcuts app. Can filter by folder or list folders.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Defaults
FOLDER=""
LIST_FOLDERS=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --folder)
            FOLDER="$2"
            shift 2
            ;;
        --folders)
            LIST_FOLDERS=true
            shift
            ;;
        *)
            error_exit "Unknown argument: $1"
            ;;
    esac
done

# Check that shortcuts CLI exists
if ! command -v shortcuts &>/dev/null; then
    error_exit "shortcuts command not found. Requires macOS 12 (Monterey) or later."
fi

if [[ "$LIST_FOLDERS" == true ]]; then
    echo "=== Shortcut Folders ==="
    output=$(shortcuts list --folders 2>&1) || error_exit "Failed to list folders: $output"
    echo "$output"
else
    args=()
    if [[ -n "$FOLDER" ]]; then
        args+=(--folder "$FOLDER")
    fi

    echo "=== Available Shortcuts ==="
    output=$(shortcuts list "${args[@]}" 2>&1) || error_exit "Failed to list shortcuts: $output"
    if [[ -z "$output" ]]; then
        echo "No shortcuts found."
    else
        echo "$output"
    fi
fi
