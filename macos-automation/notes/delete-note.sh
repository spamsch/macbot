#!/bin/bash
# ==============================================================================
# delete-note.sh - Delete a note in Notes.app
# ==============================================================================
# Usage:
#   ./delete-note.sh --title "My Note"
#   ./delete-note.sh --title "My Note" --folder "Work"
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

TITLE=""
FOLDER=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --title) TITLE="$2"; shift 2 ;;
        --folder) FOLDER="$2"; shift 2 ;;
        *) error_exit "Unknown option: $1" ;;
    esac
done

[[ -z "$TITLE" ]] && error_exit "--title is required"

TITLE_ESCAPED=$(escape_for_applescript "$TITLE")
FOLDER_ESCAPED=$(escape_for_applescript "$FOLDER")

osascript <<EOF
tell application "Notes"
    set foundNote to missing value
    if "$FOLDER_ESCAPED" is not "" then
        try
            set srcFolder to folder "$FOLDER_ESCAPED"
            repeat with n in notes of srcFolder
                if name of n contains "$TITLE_ESCAPED" then
                    set foundNote to n
                    exit repeat
                end if
            end repeat
        on error
            return "Error: Folder '$FOLDER_ESCAPED' not found."
        end try
    else
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
    delete foundNote
    return "Deleted note '" & noteName & "'"
end tell
EOF
