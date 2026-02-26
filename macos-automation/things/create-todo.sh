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
PROJECT_ESCAPED=$(escape_for_applescript "$PROJECT")
HEADING_ESCAPED=$(escape_for_applescript "$HEADING")

# Write notes to a temp file — avoids heredoc escaping issues
# (newlines break AppleScript string literals; $, ` get expanded by bash)
NOTES_FILE=""
if [[ -n "$NOTES" ]]; then
    NOTES_FILE=$(mktemp /tmp/things-notes.XXXXXX)
    printf '%s' "$NOTES" > "$NOTES_FILE"
fi

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

# Read Things auth token from config (needed for URL scheme scheduling)
THINGS_AUTH_TOKEN="${MACBOT_THINGS_AUTH_TOKEN:-}"
if [[ -z "$THINGS_AUTH_TOKEN" && -f "$HOME/.macbot/.env" ]]; then
    THINGS_AUTH_TOKEN=$(grep -E '^MACBOT_THINGS_AUTH_TOKEN=' "$HOME/.macbot/.env" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'")
fi

TMPFILE=$(mktemp /tmp/things-create.XXXXXX)
trap 'rm -f "$TMPFILE" "$NOTES_FILE"' EXIT

osascript <<EOF > "$TMPFILE"
tell application "Things3"
    -- Create to-do (tag names must be inline — can't be set on a record after creation)
    if "$TAGS" is not "" then
        set newTodo to make new to do with properties {name:"$NAME_ESCAPED", tag names:"$TAGS"}
    else
        set newTodo to make new to do with properties {name:"$NAME_ESCAPED"}
    end if

    -- Set notes from temp file (avoids heredoc escaping issues with newlines, $, etc.)
    if "$NOTES_FILE" is not "" then
        try
            set notesContent to read POSIX file "$NOTES_FILE" as «class utf8»
            set notes of newTodo to notesContent
        end try
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

    -- Set due date (safe order: day 1 first to avoid month-wrap bug)
    if "$HAS_DUE" is "true" then
        set dueDate to current date
        set day of dueDate to 1
        set year of dueDate to $DUE_YEAR
        set month of dueDate to $DUE_MONTH
        set day of dueDate to $DUE_DAY
        set hours of dueDate to 0
        set minutes of dueDate to 0
        set seconds of dueDate to 0
        set due date of newTodo to dueDate
    end if

    -- Move to target list (create-then-move pattern, not "in list")
    if "$LIST" is not "" then
        try
            move newTodo to list "$LIST"
        on error errMsg
            -- Non-fatal: to-do was created, just couldn't move
        end try
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

# Convert AppleScript carriage returns (\r) to line feeds (\n)
RESULT=$(tr '\r' '\n' < "$TMPFILE")

# Check for errors from AppleScript
if [[ "$RESULT" == Error:* ]]; then
    echo "$RESULT"
    exit 1
fi

# Apply schedule via Things URL scheme (activation date is read-only in AppleScript)
if [[ -n "$SCHEDULE_AS" ]]; then
    # Extract to-do ID from result
    TODO_ID=$(echo "$RESULT" | grep '^id: ' | sed 's/^id: //')

    if [[ -z "$TODO_ID" ]]; then
        echo "$RESULT"
        echo "Warning: Could not extract to-do ID for scheduling."
        exit 0
    fi

    # Map schedule values to Things URL scheme 'when' parameter
    WHEN_VALUE=""
    case "$SCHEDULE_AS" in
        today)    WHEN_VALUE="today" ;;
        evening)  WHEN_VALUE="evening" ;;
        tomorrow) WHEN_VALUE="tomorrow" ;;
        someday)  WHEN_VALUE="someday" ;;
        anytime)  WHEN_VALUE="anytime" ;;
        date:*)   WHEN_VALUE="${SCHEDULE_AS#date:}" ;;
    esac

    if [[ -n "$WHEN_VALUE" ]]; then
        if [[ -n "$THINGS_AUTH_TOKEN" ]]; then
            open "things:///update?auth-token=${THINGS_AUTH_TOKEN}&id=${TODO_ID}&when=${WHEN_VALUE}"
            sleep 0.5
            RESULT=$(echo "$RESULT" | sed '/^id: /d')
            RESULT="${RESULT} (scheduled: ${WHEN_VALUE})
id: ${TODO_ID}"
        else
            RESULT="${RESULT}
Warning: Could not schedule (MACBOT_THINGS_AUTH_TOKEN not set). Set it in ~/.macbot/.env"
        fi
    fi
fi

echo "$RESULT"
