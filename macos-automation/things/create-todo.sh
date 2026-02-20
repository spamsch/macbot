#!/bin/bash
# ==============================================================================
# create-todo.sh - Create a new Things3 to-do
# ==============================================================================
# Description:
#   Creates a new to-do in Things3 with optional notes, due date, tags,
#   project assignment, and scheduling.
#
# Usage:
#   ./create-todo.sh --name "Buy groceries"
#   ./create-todo.sh --name "Submit report" --due "2026-02-28" --project "Work"
#   ./create-todo.sh --name "Call mom" --tags "personal,family" --schedule "today"
#
# Options:
#   --name <text>       To-do name (required)
#   --notes <text>      Notes/description
#   --due <date>        Due date as "YYYY-MM-DD"
#   --tags <csv>        Comma-separated tag names
#   --project <name>    Assign to project by name
#   --project-id <id>   Assign to project by ID (more reliable than name)
#   --list <name>       Add to built-in list (Inbox, Today, Anytime, Someday)
#   --schedule <when>   Schedule: "today", "evening", "tomorrow", "someday",
#                       "anytime", or "YYYY-MM-DD"
#   --heading <name>    Place under a heading within the project
#
# Example:
#   ./create-todo.sh --name "Buy milk" --list "Today" --tags "errands"
#   ./create-todo.sh --name "Quarterly report" --due "2026-03-31" --project "Work"
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
NAME=""
NOTES=""
DUE=""
TAGS=""
PROJECT=""
PROJECT_ID=""
LIST=""
SCHEDULE=""
HEADING=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --name)
            NAME="$2"
            shift 2
            ;;
        --notes)
            NOTES="$2"
            shift 2
            ;;
        --due)
            DUE="$2"
            shift 2
            ;;
        --tags)
            TAGS="$2"
            shift 2
            ;;
        --project)
            PROJECT="$2"
            shift 2
            ;;
        --project-id)
            PROJECT_ID="$2"
            shift 2
            ;;
        --list)
            LIST="$2"
            shift 2
            ;;
        --schedule)
            SCHEDULE="$2"
            shift 2
            ;;
        --heading)
            HEADING="$2"
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
[[ -z "$NAME" ]] && error_exit "--name is required"

# Escape for AppleScript
NAME_ESCAPED=$(escape_for_applescript "$NAME")
NOTES_ESCAPED=$(escape_for_applescript "$NOTES")
PROJECT_ESCAPED=$(escape_for_applescript "$PROJECT")
HEADING_ESCAPED=$(escape_for_applescript "$HEADING")

# Handle due date components
HAS_DUE=false
DUE_YEAR=2000
DUE_MONTH=1
DUE_DAY=1

if [[ -n "$DUE" ]]; then
    if [[ "$DUE" =~ ^([0-9]{4})-([0-9]{2})-([0-9]{2})$ ]]; then
        HAS_DUE=true
        DUE_YEAR="${BASH_REMATCH[1]}"
        DUE_MONTH=$((10#${BASH_REMATCH[2]}))
        DUE_DAY=$((10#${BASH_REMATCH[3]}))
    else
        error_exit "Invalid date format. Use 'YYYY-MM-DD'"
    fi
fi

# Build schedule value for AppleScript
SCHEDULE_AS=""
case "$SCHEDULE" in
    today)    SCHEDULE_AS="today" ;;
    evening)  SCHEDULE_AS="evening" ;;
    tomorrow) SCHEDULE_AS="tomorrow" ;;
    someday)  SCHEDULE_AS="someday" ;;
    anytime)  SCHEDULE_AS="anytime" ;;
    "")       SCHEDULE_AS="" ;;
    *)
        # Treat as a date YYYY-MM-DD
        if [[ "$SCHEDULE" =~ ^([0-9]{4})-([0-9]{2})-([0-9]{2})$ ]]; then
            SCHEDULE_AS="date:${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]}"
        else
            error_exit "Invalid schedule value. Use: today, evening, tomorrow, someday, anytime, or YYYY-MM-DD"
        fi
        ;;
esac

osascript <<EOF
tell application "Things3"
    -- Build properties
    set props to {name:"$NAME_ESCAPED"}

    -- Tag names (comma-separated)
    if "$TAGS" is not "" then
        set tag names of props to "$TAGS"
    end if

    -- Create the to-do
    if "$LIST" is not "" then
        try
            set newTodo to make new to do with properties props in list "$LIST"
        on error errMsg
            return "Error: Could not create to-do in list '$LIST'. " & errMsg
        end try
    else
        set newTodo to make new to do with properties props
    end if

    -- Set notes after creation (more reliable than in properties)
    if "$NOTES_ESCAPED" is not "" then
        set notes of newTodo to "$NOTES_ESCAPED"
    end if

    -- Assign to project (prefer ID over name; use "set project" not "move")
    if "$PROJECT_ID" is not "" then
        try
            set targetProject to project id "$PROJECT_ID"
            set project of newTodo to targetProject
        on error
            return "Error: Project with id '$PROJECT_ID' not found. To-do was created but not assigned to a project."
        end try
    else if "$PROJECT_ESCAPED" is not "" then
        try
            set targetProject to project "$PROJECT_ESCAPED"
            set project of newTodo to targetProject
        on error
            return "Error: Project '$PROJECT_ESCAPED' not found. To-do was created but not assigned to a project."
        end try
    end if

    -- Place under heading within project
    if "$HEADING_ESCAPED" is not "" and ("$PROJECT_ESCAPED" is not "" or "$PROJECT_ID" is not "") then
        -- Note: heading assignment requires the Things URL scheme; skip for now
    end if

    -- Set due date
    if "$HAS_DUE" is "true" then
        set dueDate to current date
        set year of dueDate to $DUE_YEAR
        set month of dueDate to $DUE_MONTH
        set day of dueDate to $DUE_DAY
        set hours of dueDate to 0
        set minutes of dueDate to 0
        set seconds of dueDate to 0
        set due date of newTodo to dueDate
    end if

    -- Schedule
    set schedVal to "$SCHEDULE_AS"
    if schedVal is not "" then
        if schedVal is "today" then
            -- Move to Today list
            move newTodo to list "Today"
        else if schedVal is "evening" then
            move newTodo to list "Today"
        else if schedVal is "tomorrow" then
            -- Set activation date to tomorrow
            set tmrw to (current date) + 1 * days
            set activation date of newTodo to tmrw
        else if schedVal is "someday" then
            move newTodo to list "Someday"
        else if schedVal is "anytime" then
            move newTodo to list "Anytime"
        else if schedVal starts with "date:" then
            -- Parse date from "date:YYYY-MM-DD"
            set dateStr to text 6 thru -1 of schedVal
            set sYear to text 1 thru 4 of dateStr as integer
            set sMonth to text 6 thru 7 of dateStr as integer
            set sDay to text 9 thru 10 of dateStr as integer
            set schedDate to current date
            set year of schedDate to sYear
            set month of schedDate to sMonth
            set day of schedDate to sDay
            set hours of schedDate to 0
            set minutes of schedDate to 0
            set seconds of schedDate to 0
            set activation date of newTodo to schedDate
        end if
    end if

    -- Build confirmation
    set todoID to id of newTodo
    set output to "Created to-do: " & name of newTodo
    if "$DUE" is not "" then
        set output to output & " (due: $DUE)"
    end if
    if "$PROJECT_ESCAPED" is not "" then
        set output to output & " [" & "$PROJECT_ESCAPED" & "]"
    end if
    if "$TAGS" is not "" then
        set output to output & " #" & "$TAGS"
    end if
    set output to output & return & "id: " & todoID
    return output
end tell
EOF
