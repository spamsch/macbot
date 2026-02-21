#!/bin/bash
# ==============================================================================
# show-today.sh - Show Things3 Today list
# ==============================================================================
# Description:
#   Shows all to-dos in the Things3 Today list, including their project,
#   tags, and due dates.
#
# Usage:
#   ./show-today.sh
#
# Example:
#   ./show-today.sh
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            head -14 "$0" | tail -9
            exit 0
            ;;
        *)
            error_exit "Unknown option: $1"
            ;;
    esac
done

osascript <<'EOF'
tell application "Things3"
    set todayTodos to to dos of list "Today"
    set todoCount to count of todayTodos

    if todoCount is 0 then
        return "No to-dos in Today."
    end if

    set output to "=== THINGS3: TODAY ===" & return
    set output to output & todoCount & " to-do(s)" & return & return

    repeat with t in todayTodos
        set tName to name of t
        set tStatus to status of t
        set tTags to tag names of t
        set tID to id of t

        -- Get project name if assigned
        set tProject to ""
        try
            set tProject to name of project of t
        end try

        -- Get due date (may be missing value)
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
        else
            set todoLine to "  ✓ " & tName
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
    end repeat

    return output
end tell
EOF
