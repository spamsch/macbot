#!/bin/bash
# ==============================================================================
# update-todo.sh - Update a Things3 to-do
# ==============================================================================
# Description:
#   Updates properties of an existing to-do in Things3. Finds the to-do by
#   ID or name, then applies the requested changes.
#
# Usage:
#   ./update-todo.sh --id "ABC123" --set-name "New name"
#   ./update-todo.sh --name "Buy milk" --set-due "2026-03-01"
#
# Options:
#   --id <id>           Find to-do by ID (recommended)
#   --name <text>       Find to-do by exact name
#   --set-name <text>   Set new name
#   --set-notes <text>  Set new notes
#   --set-due <date>    Set due date as "YYYY-MM-DD"
#   --clear-due         Remove due date
#   --set-tags <csv>    Set tags (comma-separated, replaces existing)
#   --set-project <name> Move to project by name
#   --set-project-id <id> Move to project by ID (more reliable than name)
#   --set-status <s>    Set status: completed, canceled, open
#   --set-schedule <w>  Set schedule: "today", "evening", "tomorrow", "someday",
#                       "anytime", or "YYYY-MM-DD" (requires MACBOT_THINGS_AUTH_TOKEN)
#
# Example:
#   ./update-todo.sh --id "ABC123" --set-due "2026-03-15" --set-tags "work,urgent"
#   ./update-todo.sh --name "Old task" --set-name "Updated task"
#   ./update-todo.sh --id "ABC123" --set-schedule "2026-04-01"
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
TODO_ID=""
NAME=""
SET_NAME=""
SET_NOTES=""
SET_DUE=""
CLEAR_DUE=false
SET_TAGS=""
SET_PROJECT=""
SET_PROJECT_ID=""
SET_STATUS=""
SET_SCHEDULE=""

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
        --set-name)
            SET_NAME="$2"
            shift 2
            ;;
        --set-notes)
            SET_NOTES="$2"
            shift 2
            ;;
        --set-due)
            SET_DUE="$2"
            shift 2
            ;;
        --clear-due)
            CLEAR_DUE=true
            shift
            ;;
        --set-tags)
            SET_TAGS="$2"
            shift 2
            ;;
        --set-project)
            SET_PROJECT="$2"
            shift 2
            ;;
        --set-project-id)
            SET_PROJECT_ID="$2"
            shift 2
            ;;
        --set-status)
            SET_STATUS="$2"
            shift 2
            ;;
        --set-schedule)
            SET_SCHEDULE="$2"
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
[[ -z "$TODO_ID" && -z "$NAME" ]] && error_exit "Please specify --id or --name"

# Validate schedule value
SCHEDULE_WHEN=""
if [[ -n "$SET_SCHEDULE" ]]; then
    case "$SET_SCHEDULE" in
        today|evening|tomorrow|someday|anytime)
            SCHEDULE_WHEN="$SET_SCHEDULE"
            ;;
        *)
            if [[ "$SET_SCHEDULE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
                SCHEDULE_WHEN="$SET_SCHEDULE"
            else
                error_exit "Invalid schedule value. Use: today, evening, tomorrow, someday, anytime, or YYYY-MM-DD"
            fi
            ;;
    esac
fi

# Read Things auth token (needed for URL scheme scheduling)
THINGS_AUTH_TOKEN="${MACBOT_THINGS_AUTH_TOKEN:-}"
if [[ -z "$THINGS_AUTH_TOKEN" && -f "$HOME/.macbot/.env" ]]; then
    THINGS_AUTH_TOKEN=$(grep -E '^MACBOT_THINGS_AUTH_TOKEN=' "$HOME/.macbot/.env" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'")
fi

# Escape for AppleScript
NAME_ESCAPED=$(escape_for_applescript "$NAME")
SET_NAME_ESCAPED=$(escape_for_applescript "$SET_NAME")
SET_NOTES_ESCAPED=$(escape_for_applescript "$SET_NOTES")
SET_PROJECT_ESCAPED=$(escape_for_applescript "$SET_PROJECT")

# Handle due date components
HAS_SET_DUE=false
DUE_YEAR=2000
DUE_MONTH=1
DUE_DAY=1

if [[ -n "$SET_DUE" ]]; then
    if [[ "$SET_DUE" =~ ^([0-9]{4})-([0-9]{2})-([0-9]{2})$ ]]; then
        HAS_SET_DUE=true
        DUE_YEAR="${BASH_REMATCH[1]}"
        DUE_MONTH=$((10#${BASH_REMATCH[2]}))
        DUE_DAY=$((10#${BASH_REMATCH[3]}))
    else
        error_exit "Invalid date format. Use 'YYYY-MM-DD'"
    fi
fi

TMPFILE=$(mktemp /tmp/things-update.XXXXXX)
trap 'rm -f "$TMPFILE"' EXIT

osascript <<EOF > "$TMPFILE"
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

    set changes to {}
    set output to "Updated: " & name of t & return

    -- Set name
    if "$SET_NAME_ESCAPED" is not "" then
        set name of t to "$SET_NAME_ESCAPED"
        set end of changes to "  name → $SET_NAME_ESCAPED"
    end if

    -- Set notes
    if "$SET_NOTES_ESCAPED" is not "" then
        set notes of t to "$SET_NOTES_ESCAPED"
        set end of changes to "  notes → (updated)"
    end if

    -- Set due date (safe order: day 1 first to avoid month-wrap bug)
    if "$HAS_SET_DUE" is "true" then
        set dueDate to current date
        set day of dueDate to 1
        set year of dueDate to $DUE_YEAR
        set month of dueDate to $DUE_MONTH
        set day of dueDate to $DUE_DAY
        set hours of dueDate to 0
        set minutes of dueDate to 0
        set seconds of dueDate to 0
        set due date of t to dueDate
        set end of changes to "  due → $SET_DUE"
    end if

    -- Clear due date
    if $CLEAR_DUE then
        set due date of t to missing value
        set end of changes to "  due → (cleared)"
    end if

    -- Set tags
    if "$SET_TAGS" is not "" then
        set tag names of t to "$SET_TAGS"
        set end of changes to "  tags → $SET_TAGS"
    end if

    -- Set project (prefer ID over name; use "set project" not "move")
    if "$SET_PROJECT_ID" is not "" then
        try
            set targetProject to project id "$SET_PROJECT_ID"
            set project of t to targetProject
            set end of changes to "  project → (id: $SET_PROJECT_ID)"
        on error
            set end of changes to "  project → ERROR: id '$SET_PROJECT_ID' not found"
        end try
    else if "$SET_PROJECT_ESCAPED" is not "" then
        try
            set targetProject to project "$SET_PROJECT_ESCAPED"
            set project of t to targetProject
            set end of changes to "  project → $SET_PROJECT_ESCAPED"
        on error
            set end of changes to "  project → ERROR: '$SET_PROJECT_ESCAPED' not found"
        end try
    end if

    -- Set status
    if "$SET_STATUS" is "completed" then
        set status of t to completed
        set end of changes to "  status → completed"
    else if "$SET_STATUS" is "canceled" then
        set status of t to canceled
        set end of changes to "  status → canceled"
    else if "$SET_STATUS" is "open" then
        set status of t to open
        set end of changes to "  status → open"
    end if

    -- Schedule is handled outside AppleScript (activation date is read-only)
    if "$SCHEDULE_WHEN" is not "" then
        set end of changes to "  schedule → $SCHEDULE_WHEN (pending)"
    end if

    -- Build output
    if (count of changes) is 0 then
        return "No changes specified."
    end if

    repeat with c in changes
        set output to output & c & return
    end repeat
    set output to output & "id: " & id of t

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
if [[ -n "$SCHEDULE_WHEN" ]]; then
    # Extract to-do ID from result (use provided ID or extract from output)
    RESOLVED_ID="$TODO_ID"
    if [[ -z "$RESOLVED_ID" ]]; then
        RESOLVED_ID=$(echo "$RESULT" | grep '^id: ' | sed 's/^id: //')
    fi

    if [[ -z "$RESOLVED_ID" ]]; then
        echo "$RESULT"
        echo "Warning: Could not determine to-do ID for scheduling."
        exit 0
    fi

    if [[ -n "$THINGS_AUTH_TOKEN" ]]; then
        open "things:///update?auth-token=${THINGS_AUTH_TOKEN}&id=${RESOLVED_ID}&when=${SCHEDULE_WHEN}"
        sleep 0.5
        # Replace pending marker with confirmed
        RESULT=$(echo "$RESULT" | sed "s/schedule → $SCHEDULE_WHEN (pending)/schedule → $SCHEDULE_WHEN/")
    else
        RESULT=$(echo "$RESULT" | sed "s/schedule → $SCHEDULE_WHEN (pending)/schedule → ERROR: MACBOT_THINGS_AUTH_TOKEN not set/")
    fi
fi

echo "$RESULT"
