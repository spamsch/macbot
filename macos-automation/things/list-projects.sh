#!/bin/bash
# ==============================================================================
# list-projects.sh - List Things3 projects
# ==============================================================================
# Description:
#   Lists projects in Things3 with optional status filtering and to-do counts.
#
# Usage:
#   ./list-projects.sh
#   ./list-projects.sh --with-todos --status open
#
# Options:
#   --status <status>   Filter by status: open, completed, canceled (default: open)
#   --with-todos        Include open to-do counts for each project
#   --limit <n>         Maximum number of projects (default: 50)
#
# Example:
#   ./list-projects.sh --with-todos
#   ./list-projects.sh --status completed --limit 10
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
STATUS="open"
WITH_TODOS=false
LIMIT=50

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --status)
            STATUS="$2"
            shift 2
            ;;
        --with-todos)
            WITH_TODOS=true
            shift
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        -h|--help)
            head -20 "$0" | tail -15
            exit 0
            ;;
        *)
            error_exit "Unknown option: $1"
            ;;
    esac
done

osascript <<EOF
tell application "Things3"
    -- Get projects filtered by status
    if "$STATUS" is "open" then
        set allProjects to every project whose status is open
    else if "$STATUS" is "completed" then
        set allProjects to every project whose status is completed
    else if "$STATUS" is "canceled" then
        set allProjects to every project whose status is canceled
    else
        set allProjects to every project
    end if

    set projectCount to count of allProjects

    if projectCount is 0 then
        return "No projects found with status '$STATUS'."
    end if

    set output to "=== THINGS3: PROJECTS ===" & return
    set output to output & projectCount & " project(s) ($STATUS)" & return & return

    set displayCount to 0
    repeat with p in allProjects
        if displayCount ≥ $LIMIT then exit repeat
        set displayCount to displayCount + 1

        set pName to name of p
        set pStatus to status of p
        set pTags to tag names of p
        set pID to id of p

        -- Get due date
        set pDue to ""
        try
            set d to due date of p
            if d is not missing value then
                set pDue to short date string of d
            end if
        end try

        -- Get notes preview
        set pNotes to ""
        try
            set n to notes of p
            if n is not "" and n is not missing value then
                if length of n > 60 then
                    set pNotes to text 1 thru 60 of n & "..."
                else
                    set pNotes to n
                end if
            end if
        end try

        -- Build output line
        set todoLine to "  " & pName

        if $WITH_TODOS then
            set openCount to count of (to dos of p whose status is open)
            set todoLine to todoLine & " (" & openCount & " open)"
        end if

        if pDue is not "" then
            set todoLine to todoLine & "  (due: " & pDue & ")"
        end if
        if pTags is not "" then
            set todoLine to todoLine & "  #" & pTags
        end if
        if pNotes is not "" then
            set todoLine to todoLine & return & "    " & pNotes
        end if
        set todoLine to todoLine & return & "    id: " & pID

        set output to output & todoLine & return
    end repeat

    return output
end tell
EOF
