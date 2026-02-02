#!/bin/bash
# ==============================================================================
# list-notes.sh - List notes with various options
# ==============================================================================
# Description:
#   Lists notes from Notes.app. Can list all notes, notes from a specific
#   folder, or recently modified notes.
#
# Usage:
#   ./list-notes.sh
#   ./list-notes.sh --folder "Work"
#   ./list-notes.sh --recent 7
#   ./list-notes.sh --with-attachments
#
# Options:
#   --folder <name>      Only list notes from specified folder
#   --recent <days>      Only show notes modified in last n days
#   --with-attachments   Only show notes that have attachments
#   --limit <n>          Limit results (default: 50)
#   --show-folders       Group notes by folder
#
# Example:
#   ./list-notes.sh --folder "Work" --limit 10
#   ./list-notes.sh --recent 7 --show-folders
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
FOLDER=""
RECENT=""
WITH_ATTACHMENTS=false
LIMIT=50
SHOW_FOLDERS=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --folder)
            FOLDER="$2"
            shift 2
            ;;
        --recent)
            RECENT="$2"
            shift 2
            ;;
        --with-attachments)
            WITH_ATTACHMENTS=true
            shift
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        --show-folders)
            SHOW_FOLDERS=true
            shift
            ;;
        -h|--help)
            head -28 "$0" | tail -23
            exit 0
            ;;
        *)
            error_exit "Unknown option: $1"
            ;;
    esac
done

# Escape user input for AppleScript
FOLDER_ESCAPED=$(escape_for_applescript "$FOLDER")

osascript <<EOF
tell application "Notes"
    set output to "=== NOTES ===" & return & return
    set noteCount to 0
    set cutoffDate to missing value

    if "$RECENT" is not "" then
        set cutoffDate to (current date) - ($RECENT * 24 * 60 * 60)
        set output to "=== NOTES (last $RECENT days) ===" & return & return
    end if

    set folderList to {}
    if "$FOLDER_ESCAPED" is not "" then
        try
            set folderList to {folder "$FOLDER_ESCAPED"}
            set output to "=== NOTES: $FOLDER_ESCAPED ===" & return & return
        on error
            return "Folder '$FOLDER_ESCAPED' not found."
        end try
    else
        set folderList to folders
    end if

    repeat with f in folderList
        -- Skip Recently Deleted
        if name of f is not "Recently Deleted" then
            set folderOutput to ""
            set folderNoteCount to 0

            if $SHOW_FOLDERS or "$FOLDER" is "" then
                set folderOutput to "📁 " & name of f & return
            end if

            repeat with n in notes of f
                set include to true

                -- Apply date filter
                if cutoffDate is not missing value then
                    if modification date of n < cutoffDate then
                        set include to false
                    end if
                end if

                -- Apply attachment filter
                if $WITH_ATTACHMENTS then
                    if (count of attachments of n) is 0 then
                        set include to false
                    end if
                end if

                if include and noteCount < $LIMIT then
                    set noteCount to noteCount + 1
                    set folderNoteCount to folderNoteCount + 1

                    set noteLine to "  📝 " & name of n

                    -- Add attachment indicator
                    set attCount to count of attachments of n
                    if attCount > 0 then
                        set noteLine to noteLine & " 📎" & attCount
                    end if

                    set folderOutput to folderOutput & noteLine & return

                    -- Show modification date for recent filter
                    if "$RECENT" is not "" then
                        set folderOutput to folderOutput & "     Modified: " & (modification date of n as string) & return
                    end if
                end if
            end repeat

            if folderNoteCount > 0 then
                set output to output & folderOutput & return
            end if
        end if
    end repeat

    if noteCount is 0 then
        return "No notes found matching the criteria."
    end if

    set output to output & "Total: " & noteCount & " note(s)"
    if noteCount >= $LIMIT then
        set output to output & " (limit reached)"
    end if

    return output
end tell
EOF
