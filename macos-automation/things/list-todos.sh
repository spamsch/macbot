#!/bin/bash
# ==============================================================================
# list-todos.sh - List Things3 to-dos with filters
# ==============================================================================
# Description:
#   Lists to-dos from Things3 with optional filters by list, project, tag,
#   and status. Supports built-in lists: Inbox, Today, Upcoming, Anytime,
#   Someday, Logbook, Trash.
#
# Usage:
#   ./list-todos.sh
#   ./list-todos.sh --list "Today"
#   ./list-todos.sh --project "Work" --tag "urgent"
#
# Options:
#   --list <name>       Filter by built-in list (Inbox, Today, Upcoming, Anytime, Someday, Logbook, Trash)
#   --project <name>    Filter by project name
#   --tag <name>        Filter by tag name
#   --status <status>   Filter by status: open, completed, canceled (default: open)
#   --limit <n>         Maximum number of results (default: 50)
#
# Example:
#   ./list-todos.sh --list "Today"
#   ./list-todos.sh --project "Work" --status open --limit 10
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
LIST_NAME=""
PROJECT_NAME=""
TAG_NAME=""
STATUS="open"
LIMIT=50

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --list)
            LIST_NAME="$2"
            shift 2
            ;;
        --project)
            PROJECT_NAME="$2"
            shift 2
            ;;
        --tag)
            TAG_NAME="$2"
            shift 2
            ;;
        --status)
            STATUS="$2"
            shift 2
            ;;
        --limit)
            LIMIT="$2"
            shift 2
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

# Escape for AppleScript
PROJECT_ESCAPED=$(escape_for_applescript "$PROJECT_NAME")
TAG_ESCAPED=$(escape_for_applescript "$TAG_NAME")

osascript <<EOF
tell application "Things3"
    set output to ""
    set displayCount to 0

    -- Determine source collection
    if "$LIST_NAME" is not "" then
        try
            set todoCollection to to dos of list "$LIST_NAME"
            set output to output & "=== THINGS3: $LIST_NAME ===" & return
        on error
            return "Error: List '$LIST_NAME' not found. Valid lists: Inbox, Today, Upcoming, Anytime, Someday, Logbook, Trash."
        end try
    else if "$PROJECT_ESCAPED" is not "" then
        try
            set targetProject to project "$PROJECT_ESCAPED"
            set todoCollection to to dos of targetProject
            set output to output & "=== THINGS3: Project '$PROJECT_ESCAPED' ===" & return
        on error
            return "Error: Project '$PROJECT_ESCAPED' not found."
        end try
    else if "$TAG_ESCAPED" is not "" then
        try
            set targetTag to tag "$TAG_ESCAPED"
            set todoCollection to to dos of targetTag
            set output to output & "=== THINGS3: Tag '$TAG_ESCAPED' ===" & return
        on error
            return "Error: Tag '$TAG_ESCAPED' not found."
        end try
    else
        set todoCollection to to dos
        set output to output & "=== THINGS3: ALL TO-DOS ===" & return
    end if

    set totalCount to count of todoCollection
    set output to output & totalCount & " to-do(s) total" & return & return

    repeat with t in todoCollection
        if displayCount ≥ $LIMIT then
            set output to output & return & "(showing " & displayCount & " of " & totalCount & ")" & return
            exit repeat
        end if

        set tName to name of t
        set tStatus to status of t
        set tTags to tag names of t
        set tID to id of t

        -- Filter by status
        set statusMatch to false
        if "$STATUS" is "open" and tStatus is open then
            set statusMatch to true
        else if "$STATUS" is "completed" and tStatus is completed then
            set statusMatch to true
        else if "$STATUS" is "canceled" and tStatus is canceled then
            set statusMatch to true
        end if

        if not statusMatch then
            -- Skip non-matching status but don't count against limit
        else
            set displayCount to displayCount + 1

            -- Get project name if assigned
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

            -- Get notes preview
            set tNotes to ""
            try
                set n to notes of t
                if n is not "" and n is not missing value then
                    if length of n > 60 then
                        set tNotes to text 1 thru 60 of n & "..."
                    else
                        set tNotes to n
                    end if
                end if
            end try

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
    end repeat

    if displayCount is 0 then
        return "No to-dos found matching the criteria."
    end if

    return output
end tell
EOF
