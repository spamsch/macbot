#!/bin/bash
# ==============================================================================
# move-note.sh - Move a note to a different folder
# ==============================================================================
# Usage:
#   ./move-note.sh --title "My Note" --to "Work"
#   ./move-note.sh --title "My Note" --from "Notes" --to "Work"
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

TITLE=""
FROM=""
TO=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --title) TITLE="$2"; shift 2 ;;
        --from) FROM="$2"; shift 2 ;;
        --to) TO="$2"; shift 2 ;;
        *) error_exit "Unknown option: $1" ;;
    esac
done

[[ -z "$TITLE" ]] && error_exit "--title is required"
[[ -z "$TO" ]] && error_exit "--to is required"

TITLE_ESCAPED=$(escape_for_applescript "$TITLE")
FROM_ESCAPED=$(escape_for_applescript "$FROM")
TO_ESCAPED=$(escape_for_applescript "$TO")

osascript <<EOF
tell application "Notes"
    -- Find destination folder
    try
        set destFolder to folder "$TO_ESCAPED"
    on error
        return "Error: Destination folder '$TO_ESCAPED' not found."
    end try

    -- Find the note
    set foundNote to missing value
    if "$FROM_ESCAPED" is not "" then
        try
            set srcFolder to folder "$FROM_ESCAPED"
            repeat with n in notes of srcFolder
                if name of n contains "$TITLE_ESCAPED" then
                    set foundNote to n
                    exit repeat
                end if
            end repeat
        on error
            return "Error: Source folder '$FROM_ESCAPED' not found."
        end try
    else
        -- Search all folders
        repeat with f in folders
            repeat with n in notes of f
                if name of n contains "$TITLE_ESCAPED" then
                    set foundNote to n
                    exit repeat
                end if
            end repeat
            if foundNote is not missing value then exit repeat
        end repeat
    end if

    if foundNote is missing value then
        return "Error: Note matching '$TITLE_ESCAPED' not found."
    end if

    set noteName to name of foundNote
    move foundNote to destFolder
    return "Moved '" & noteName & "' to folder '$TO_ESCAPED'"
end tell
EOF
