#!/bin/bash
# ==============================================================================
# delete-folder.sh - Delete a folder in Notes.app
# ==============================================================================
# Usage:
#   ./delete-folder.sh --name "Old Folder"
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

NAME=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --name) NAME="$2"; shift 2 ;;
        *) error_exit "Unknown option: $1" ;;
    esac
done

[[ -z "$NAME" ]] && error_exit "--name is required"

NAME_ESCAPED=$(escape_for_applescript "$NAME")

osascript <<EOF
tell application "Notes"
    try
        set f to folder "$NAME_ESCAPED"
        set noteCount to count of notes of f
        if noteCount > 0 then
            return "Error: Folder '$NAME_ESCAPED' has " & noteCount & " note(s). Move or delete them first."
        end if
        delete f
        return "Deleted folder '$NAME_ESCAPED'"
    on error
        return "Error: Folder '$NAME_ESCAPED' not found."
    end try
end tell
EOF
