#!/bin/bash
# ==============================================================================
# list-reminders.sh - List reminders with various filters
# ==============================================================================
# Description:
#   Lists reminders with flexible filtering options. Can show all incomplete
#   reminders, flagged reminders, high priority items, or by specific list.
#
# Usage:
#   ./list-reminders.sh
#   ./list-reminders.sh --list "Work Tasks"
#   ./list-reminders.sh --flagged
#   ./list-reminders.sh --high-priority
#   ./list-reminders.sh --overdue
#   ./list-reminders.sh --completed --limit 10
#
# Options:
#   --list <name>      Only show reminders from specified list
#   --flagged          Only show flagged reminders
#   --high-priority    Only show high priority reminders (priority 1-4)
#   --overdue          Only show overdue reminders
#   --completed        Show completed reminders instead of incomplete
#   --limit <n>        Limit results to n reminders (default: 50)
#
# Example:
#   ./list-reminders.sh --flagged --high-priority
#   ./list-reminders.sh --list "Shopping" --limit 20
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
LIST_NAME=""
FLAGGED=false
HIGH_PRIORITY=false
OVERDUE=false
COMPLETED=false
LIMIT=50

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --list)
            LIST_NAME="$2"
            shift 2
            ;;
        --flagged)
            FLAGGED=true
            shift
            ;;
        --high-priority)
            HIGH_PRIORITY=true
            shift
            ;;
        --overdue)
            OVERDUE=true
            shift
            ;;
        --completed)
            COMPLETED=true
            shift
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        -h|--help)
            head -32 "$0" | tail -27
            exit 0
            ;;
        *)
            error_exit "Unknown option: $1"
            ;;
    esac
done

osascript <<EOF
tell application "Reminders"
    set now to current date
    set output to ""
    set displayCount to 0

    set listCollection to {}
    if "$LIST_NAME" is not "" then
        try
            set listCollection to {list "$LIST_NAME"}
            set output to output & "=== REMINDERS: $LIST_NAME ===" & return & return
        on error
            return "List '$LIST_NAME' not found."
        end try
    else
        set listCollection to every list
        set output to output & "=== ALL REMINDERS ===" & return & return
    end if

    -- Phase 1: batch-count total reminders per list to skip empty ones (fast)
    set totalCounts to {}
    repeat with l in listCollection
        set end of totalCounts to count of reminders of l
    end repeat

    -- Phase 2: only query properties for lists that have reminders
    set listIdx to 0
    repeat with l in listCollection
        set listIdx to listIdx + 1
        if item listIdx of totalCounts > 0 then
            set listOutput to ""
            set listCount to 0

            if "$LIST_NAME" is "" then
                set listOutput to "📋 " & name of l & return
            end if

            -- Bulk-fetch per property with "whose" pre-filter (each is fast;
            -- multi-property in one call causes error -1728 in Reminders.app)
            if $COMPLETED then
                set allNames to name of (every reminder of l whose completed is true)
            else
                set allNames to name of (every reminder of l whose completed is false)
            end if

            set rCount to count of allNames
            if rCount > 0 then
                if $COMPLETED then
                    set allPriorities to priority of (every reminder of l whose completed is true)
                    set allFlagged to flagged of (every reminder of l whose completed is true)
                    set allDueDates to due date of (every reminder of l whose completed is true)
                else
                    set allPriorities to priority of (every reminder of l whose completed is false)
                    set allFlagged to flagged of (every reminder of l whose completed is false)
                    set allDueDates to due date of (every reminder of l whose completed is false)
                end if

                repeat with i from 1 to rCount
                    set rName to item i of allNames
                    set rPriority to item i of allPriorities
                    set rFlag to item i of allFlagged
                    set rDue to item i of allDueDates

                    -- Apply remaining filters
                    set include to true

                    if $FLAGGED and not rFlag then
                        set include to false
                    end if

                    if $HIGH_PRIORITY and (rPriority is 0 or rPriority > 4) then
                        set include to false
                    end if

                    if $OVERDUE then
                        try
                            if rDue is missing value or rDue ≥ now then
                                set include to false
                            end if
                        on error
                            set include to false
                        end try
                    end if

                    if include and displayCount < $LIMIT then
                        set displayCount to displayCount + 1
                        set listCount to listCount + 1

                        -- Build reminder line
                        set rLine to "  "
                        if $COMPLETED then
                            set rLine to rLine & "✓ "
                        else
                            set rLine to rLine & "□ "
                        end if
                        set rLine to rLine & rName

                        -- Add indicators
                        if rPriority > 0 and rPriority < 5 then
                            set rLine to rLine & " ❗"
                        end if
                        if rFlag then
                            set rLine to rLine & " 🚩"
                        end if

                        set listOutput to listOutput & rLine & return

                        -- Add due date if set
                        if rDue is not missing value then
                            set listOutput to listOutput & "     Due: " & (rDue as string) & return
                            -- Check if overdue
                            if rDue < now and not $COMPLETED then
                                set listOutput to listOutput & "     ⚠️ OVERDUE" & return
                            end if
                        end if
                    end if
                end repeat
            end if

            if listCount > 0 then
                set output to output & listOutput & return
            end if
        end if
    end repeat

    if displayCount is 0 then
        return "No reminders found matching the criteria."
    end if

    set output to output & "Showing " & displayCount & " reminder(s)"
    if displayCount >= $LIMIT then
        set output to output & " (limit reached)"
    end if

    return output
end tell
EOF
