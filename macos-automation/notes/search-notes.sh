#!/bin/bash
# ==============================================================================
# search-notes.sh - Search notes by title or content
# ==============================================================================
# Description:
#   Searches for notes matching a pattern in title or content. Returns note
#   names, folders, and optionally a preview of matching content.
#
# Usage:
#   ./search-notes.sh --query "project"
#   ./search-notes.sh --query "meeting" --folder "Work"
#   ./search-notes.sh --query "TODO" --show-preview
#   ./search-notes.sh --title-only --query "Report"
#
# Options:
#   --query <text>      Search text (required)
#   --folder <name>     Only search in specified folder
#   --title-only        Only search in note titles (faster)
#   --show-preview      Show a preview of note content
#   --limit <n>         Limit results (default: 20)
#
# Example:
#   ./search-notes.sh --query "meeting notes"
#   ./search-notes.sh --query "budget" --folder "Finance" --show-preview
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
QUERY=""
FOLDER=""
TITLE_ONLY=false
SHOW_PREVIEW=false
LIMIT=20

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --query)
            QUERY="$2"
            shift 2
            ;;
        --folder)
            FOLDER="$2"
            shift 2
            ;;
        --title-only)
            TITLE_ONLY=true
            shift
            ;;
        --show-preview)
            SHOW_PREVIEW=true
            shift
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        -h|--help)
            head -30 "$0" | tail -25
            exit 0
            ;;
        *)
            error_exit "Unknown option: $1"
            ;;
    esac
done

# Validate
[[ -z "$QUERY" ]] && error_exit "--query is required"

# Escape user input for AppleScript
QUERY_ESCAPED=$(escape_for_applescript "$QUERY")
FOLDER_ESCAPED=$(escape_for_applescript "$FOLDER")

osascript <<EOF
tell application "Notes"
    set output to "=== SEARCH: $QUERY_ESCAPED ===" & return & return
    set matchCount to 0

    set folderList to {}
    if "$FOLDER_ESCAPED" is not "" then
        try
            set folderList to {folder "$FOLDER_ESCAPED"}
        on error
            return "Folder '$FOLDER_ESCAPED' not found."
        end try
    else
        set folderList to folders
    end if

    repeat with f in folderList
        -- Skip Recently Deleted
        if name of f is not "Recently Deleted" then
            repeat with n in notes of f
                set matched to false

                if $TITLE_ONLY then
                    if name of n contains "$QUERY_ESCAPED" then
                        set matched to true
                    end if
                else
                    if name of n contains "$QUERY_ESCAPED" or plaintext of n contains "$QUERY_ESCAPED" then
                        set matched to true
                    end if
                end if

                if matched and matchCount < $LIMIT then
                    set matchCount to matchCount + 1

                    set output to output & "📝 " & name of n & return
                    set output to output & "   Folder: " & name of f & return
                    set output to output & "   Modified: " & (modification date of n as string) & return

                    if $SHOW_PREVIEW then
                        set noteText to plaintext of n
                        if length of noteText > 200 then
                            set preview to text 1 thru 200 of noteText
                            set preview to preview & "..."
                        else
                            set preview to noteText
                        end if
                        -- Remove line breaks for cleaner display
                        set output to output & "   Preview: " & preview & return
                    end if

                    set output to output & return
                end if
            end repeat
        end if
    end repeat

    if matchCount is 0 then
        return "No notes found matching '$QUERY_ESCAPED'."
    end if

    set output to output & "Found " & matchCount & " note(s)"
    if matchCount >= $LIMIT then
        set output to output & " (showing first $LIMIT)"
    end if

    return output
end tell
EOF
