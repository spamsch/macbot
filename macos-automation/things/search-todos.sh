#!/bin/bash
# ==============================================================================
# search-todos.sh - Search Things3 to-dos by name or notes
# ==============================================================================
# Description:
#   Searches to-dos in Things3 by matching text in the name or notes fields.
#
# Usage:
#   ./search-todos.sh --query "groceries"
#   ./search-todos.sh --query "report" --status completed
#
# Options:
#   --query <text>          Search text (required)
#   --status <status>       Filter by status: open, completed, canceled (default: open)
#   --include-completed     Include completed to-dos in search
#   --limit <n>             Maximum number of results (default: 20)
#
# Example:
#   ./search-todos.sh --query "meeting"
#   ./search-todos.sh --query "project" --include-completed --limit 10
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
QUERY=""
STATUS="open"
INCLUDE_COMPLETED=false
LIMIT=20

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --query)
            QUERY="$2"
            shift 2
            ;;
        --status)
            STATUS="$2"
            shift 2
            ;;
        --include-completed)
            INCLUDE_COMPLETED=true
            shift
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        -h|--help)
            head -22 "$0" | tail -17
            exit 0
            ;;
        *)
            error_exit "Unknown option: $1"
            ;;
    esac
done

# Validate
[[ -z "$QUERY" ]] && error_exit "--query is required"

QUERY_ESCAPED=$(escape_for_applescript "$QUERY")

osascript <<EOF
tell application "Things3"
    set output to ""
    set displayCount to 0

    -- Search across all to-dos
    set allTodos to to dos

    set output to "=== THINGS3: Search '$QUERY_ESCAPED' ===" & return & return

    repeat with t in allTodos
        if displayCount ≥ $LIMIT then exit repeat

        set tName to name of t
        set tStatus to status of t

        -- Check status filter
        set statusMatch to false
        if $INCLUDE_COMPLETED then
            set statusMatch to true
        else if "$STATUS" is "open" and tStatus is open then
            set statusMatch to true
        else if "$STATUS" is "completed" and tStatus is completed then
            set statusMatch to true
        else if "$STATUS" is "canceled" and tStatus is canceled then
            set statusMatch to true
        end if

        if not statusMatch then
            -- Skip
        else
            -- Check if name or notes contain query
            set nameMatch to false
            set notesMatch to false

            -- Case-insensitive name match
            if tName contains "$QUERY_ESCAPED" then
                set nameMatch to true
            end if

            set tNotesText to ""
            try
                set tNotesText to notes of t
                if tNotesText is missing value then set tNotesText to ""
            end try

            if tNotesText contains "$QUERY_ESCAPED" then
                set notesMatch to true
            end if

            if nameMatch or notesMatch then
                set displayCount to displayCount + 1
                set tTags to tag names of t
                set tID to id of t

                -- Get project name
                set tProject to ""
                try
                    set tProject to name of project of t
                end try

                -- Get due date
                set tDue to ""
                try
                    set d to due date of t
                    if d is not missing value then
                        set tDue to short date string of d
                    end if
                end try

                -- Notes preview
                set tNotes to ""
                if tNotesText is not "" then
                    if length of tNotesText > 60 then
                        set tNotes to text 1 thru 60 of tNotesText & "..."
                    else
                        set tNotes to tNotesText
                    end if
                end if

                -- Build output line
                if tStatus is open then
                    set todoLine to "  □ " & tName
                else if tStatus is completed then
                    set todoLine to "  ✓ " & tName
                else
                    set todoLine to "  ✗ " & tName
                end if

                if tProject is not "" then
                    set todoLine to todoLine & "  [" & tProject & "]"
                end if
                if tDue is not "" then
                    set todoLine to todoLine & "  (due: " & tDue & ")"
                end if
                if tTags is not "" then
                    set todoLine to todoLine & "  #" & tTags
                end if
                if tNotes is not "" then
                    set todoLine to todoLine & return & "    " & tNotes
                end if
                set todoLine to todoLine & return & "    id: " & tID

                set output to output & todoLine & return
            end if
        end if
    end repeat

    if displayCount is 0 then
        return "No to-dos found matching '$QUERY_ESCAPED'."
    end if

    set output to output & return & displayCount & " result(s) found."

    return output
end tell
EOF
