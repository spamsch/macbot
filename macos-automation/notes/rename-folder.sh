#!/bin/bash
# ==============================================================================
# rename-folder.sh - Rename a folder in Notes.app
# ==============================================================================
# Usage:
#   ./rename-folder.sh --name "Old Name" --new-name "New Name"
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

NAME=""
NEW_NAME=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --name) NAME="$2"; shift 2 ;;
        --new-name) NEW_NAME="$2"; shift 2 ;;
        *) error_exit "Unknown option: $1" ;;
    esac
done

[[ -z "$NAME" ]] && error_exit "--name is required"
[[ -z "$NEW_NAME" ]] && error_exit "--new-name is required"

NAME_ESCAPED=$(escape_for_applescript "$NAME")
NEW_NAME_ESCAPED=$(escape_for_applescript "$NEW_NAME")

osascript <<EOF
tell application "Notes"
    try
        set f to folder "$NAME_ESCAPED"
        set name of f to "$NEW_NAME_ESCAPED"
        return "Renamed folder '$NAME_ESCAPED' to '$NEW_NAME_ESCAPED'"
    on error
        return "Error: Folder '$NAME_ESCAPED' not found."
    end try
end tell
EOF
