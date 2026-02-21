#!/bin/bash
# ==============================================================================
# move-todo.sh - Move a Things3 to-do to a list or project
# ==============================================================================
# Description:
#   Moves a to-do to a different built-in list (Inbox, Today, Someday, etc.)
#   or to a project.
#
# Usage:
#   ./move-todo.sh --id "ABC123" --to-list "Today"
#   ./move-todo.sh --name "Buy milk" --to-project "Errands"
#
# Options:
#   --id <id>           Find to-do by ID (recommended)
#   --name <text>       Find to-do by exact name
#   --to-list <name>    Move to built-in list (Inbox, Today, Anytime, Someday)
#   --to-project <name> Move to project by name
#   --to-project-id <id> Move to project by ID (more reliable than name)
#
# Example:
#   ./move-todo.sh --id "ABC123" --to-list "Today"
#   ./move-todo.sh --name "Review doc" --to-project "Work"
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
TODO_ID=""
NAME=""
TO_LIST=""
TO_PROJECT=""
TO_PROJECT_ID=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --id)
            TODO_ID="$2"
            shift 2
            ;;
        --name)
            NAME="$2"
            shift 2
            ;;
        --to-list)
            TO_LIST="$2"
            shift 2
            ;;
        --to-project)
            TO_PROJECT="$2"
            shift 2
            ;;
        --to-project-id)
            TO_PROJECT_ID="$2"
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
[[ -z "$TODO_ID" && -z "$NAME" ]] && error_exit "Please specify --id or --name"
[[ -z "$TO_LIST" && -z "$TO_PROJECT" && -z "$TO_PROJECT_ID" ]] && error_exit "Please specify --to-list, --to-project, or --to-project-id"

# Upcoming is a virtual list — items appear there via schedule date, not move
if [[ "$TO_LIST" == "Upcoming" ]]; then
    error_exit "'Upcoming' is a virtual list in Things3 — to-dos appear there when they have a future schedule date. Use update_things_todo with set_schedule instead."
fi

NAME_ESCAPED=$(escape_for_applescript "$NAME")
TO_PROJECT_ESCAPED=$(escape_for_applescript "$TO_PROJECT")

osascript <<EOF
tell application "Things3"
    -- Find the to-do
    set t to missing value

    if "$TODO_ID" is not "" then
        try
            set t to to do id "$TODO_ID"
        on error
            return "Error: No to-do found with id '$TODO_ID'."
        end try
    else
        set matchingTodos to (to dos whose name is "$NAME_ESCAPED")
        if (count of matchingTodos) is 0 then
            return "Error: No to-do found with name '$NAME_ESCAPED'."
        end if
        set t to item 1 of matchingTodos
    end if

    set tName to name of t

    if "$TO_LIST" is not "" then
        try
            move t to list "$TO_LIST"
            return "Moved '" & tName & "' to list '$TO_LIST'."
        on error errMsg
            return "Error: Could not move to list '$TO_LIST'. " & errMsg
        end try
    else if "$TO_PROJECT_ID" is not "" then
        try
            set targetProject to project id "$TO_PROJECT_ID"
            set project of t to targetProject
            return "Moved '" & tName & "' to project (id: $TO_PROJECT_ID)."
        on error
            return "Error: Project with id '$TO_PROJECT_ID' not found."
        end try
    else if "$TO_PROJECT_ESCAPED" is not "" then
        try
            set targetProject to project "$TO_PROJECT_ESCAPED"
            set project of t to targetProject
            return "Moved '" & tName & "' to project '$TO_PROJECT_ESCAPED'."
        on error
            return "Error: Project '$TO_PROJECT_ESCAPED' not found."
        end try
    end if
end tell
EOF
