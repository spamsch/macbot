#!/bin/bash
# ==============================================================================
# update-project.sh - Update a Things3 project
# ==============================================================================
# Description:
#   Updates properties of an existing project in Things3. Finds the project by
#   ID or name, then applies the requested changes.
#
# Usage:
#   ./update-project.sh --id "ABC123" --set-notes "Updated description"
#   ./update-project.sh --name "Work" --set-due "2026-06-01"
#
# Options:
#   --id <id>           Find project by ID (recommended)
#   --name <text>       Find project by name
#   --set-name <text>   Set new name
#   --set-notes <text>  Set new notes
#   --clear-notes       Clear notes
#   --set-due <date>    Set due date as "YYYY-MM-DD"
#   --set-tags <csv>    Set tags (comma-separated, replaces existing)
#   --set-area <name>   Move to area
#   --set-status <s>    Set status: completed, canceled, open
#
# Example:
#   ./update-project.sh --id "ABC123" --set-notes "Q2 goals" --set-tags "work"
#   ./update-project.sh --name "Old Project" --set-name "Renamed Project"
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
PROJECT_ID=""
NAME=""
SET_NAME=""
SET_NOTES=""
CLEAR_NOTES=false
SET_DUE=""
SET_TAGS=""
SET_AREA=""
SET_STATUS=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --id)
            PROJECT_ID="$2"
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
        --clear-notes)
            CLEAR_NOTES=true
            shift
            ;;
        --set-due)
            SET_DUE="$2"
            shift 2
            ;;
        --set-tags)
            SET_TAGS="$2"
            shift 2
            ;;
        --set-area)
            SET_AREA="$2"
            shift 2
            ;;
        --set-status)
            SET_STATUS="$2"
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

# Validate
[[ -z "$PROJECT_ID" && -z "$NAME" ]] && error_exit "Please specify --id or --name"

# Escape for AppleScript
NAME_ESCAPED=$(escape_for_applescript "$NAME")
SET_NAME_ESCAPED=$(escape_for_applescript "$SET_NAME")
SET_NOTES_ESCAPED=$(escape_for_applescript "$SET_NOTES")
SET_AREA_ESCAPED=$(escape_for_applescript "$SET_AREA")

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

osascript <<EOF
tell application "Things3"
    -- Find the project
    set p to missing value

    if "$PROJECT_ID" is not "" then
        try
            set p to project id "$PROJECT_ID"
        on error
            return "Error: No project found with id '$PROJECT_ID'."
        end try
    else
        set matchingProjects to (every project whose name is "$NAME_ESCAPED")
        if (count of matchingProjects) is 0 then
            return "Error: No project found with name '$NAME_ESCAPED'."
        end if
        set p to item 1 of matchingProjects
    end if

    set changes to {}
    set output to "Updated project: " & name of p & return

    -- Set name
    if "$SET_NAME_ESCAPED" is not "" then
        set name of p to "$SET_NAME_ESCAPED"
        set end of changes to "  name → $SET_NAME_ESCAPED"
    end if

    -- Set notes
    if "$SET_NOTES_ESCAPED" is not "" then
        set notes of p to "$SET_NOTES_ESCAPED"
        set end of changes to "  notes → (updated)"
    end if

    -- Clear notes
    if $CLEAR_NOTES then
        set notes of p to ""
        set end of changes to "  notes → (cleared)"
    end if

    -- Set due date
    if "$HAS_SET_DUE" is "true" then
        set dueDate to current date
        set year of dueDate to $DUE_YEAR
        set month of dueDate to $DUE_MONTH
        set day of dueDate to $DUE_DAY
        set hours of dueDate to 0
        set minutes of dueDate to 0
        set seconds of dueDate to 0
        set due date of p to dueDate
        set end of changes to "  due → $SET_DUE"
    end if

    -- Set tags
    if "$SET_TAGS" is not "" then
        set tag names of p to "$SET_TAGS"
        set end of changes to "  tags → $SET_TAGS"
    end if

    -- Set area
    if "$SET_AREA_ESCAPED" is not "" then
        try
            set targetArea to area "$SET_AREA_ESCAPED"
            set area of p to targetArea
            set end of changes to "  area → $SET_AREA_ESCAPED"
        on error
            set end of changes to "  area → ERROR: '$SET_AREA_ESCAPED' not found"
        end try
    end if

    -- Set status
    if "$SET_STATUS" is "completed" then
        set status of p to completed
        set end of changes to "  status → completed"
    else if "$SET_STATUS" is "canceled" then
        set status of p to canceled
        set end of changes to "  status → canceled"
    else if "$SET_STATUS" is "open" then
        set status of p to open
        set end of changes to "  status → open"
    end if

    -- Build output
    if (count of changes) is 0 then
        return "No changes specified."
    end if

    repeat with c in changes
        set output to output & c & return
    end repeat
    set output to output & "id: " & id of p

    return output
end tell
EOF
