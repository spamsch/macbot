#!/bin/bash
# ==============================================================================
# mark-processed.sh - Mark emails as processed by MacBot
# ==============================================================================
# Description:
#   Marks emails with a colored flag to indicate they've been processed by
#   MacBot. Uses green flag (index 3) by default. Can also unflag messages.
#
# Usage:
#   ./mark-processed.sh --subject "Meeting notes"
#   ./mark-processed.sh --sender "john@example.com" --account "Work"
#   ./mark-processed.sh --message-id "<abc123@mail.example.com>"
#   ./mark-processed.sh --subject "Old topic" --unflag
#
# Options:
#   --sender <pattern>    Match emails from sender containing pattern
#   --subject <pattern>   Match emails with subject containing pattern
#   --message-id <id>     Match specific email by Message-ID header
#   --account <name>      Only search in specified account
#   --mailbox <name>      Only search in specified mailbox
#   --flag-color <color>  Flag color: red, orange, yellow, green, blue, purple, gray (default: green)
#   --unflag              Remove flag instead of setting it
#   --limit <n>           Limit number of messages to mark (default: 10)
#
# Example:
#   ./mark-processed.sh --sender "aws" --subject "invoice" --flag-color green
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
SENDER_PATTERN=""
SUBJECT_PATTERN=""
MESSAGE_ID=""
ACCOUNT=""
MAILBOX=""
FLAG_COLOR="green"
UNFLAG=false
LIMIT=10

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --sender)
            SENDER_PATTERN="$2"
            shift 2
            ;;
        --subject)
            SUBJECT_PATTERN="$2"
            shift 2
            ;;
        --message-id)
            MESSAGE_ID="$2"
            shift 2
            ;;
        --account)
            ACCOUNT="$2"
            shift 2
            ;;
        --mailbox)
            MAILBOX="$2"
            shift 2
            ;;
        --flag-color)
            FLAG_COLOR="$2"
            shift 2
            ;;
        --unflag)
            UNFLAG=true
            shift
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        -h|--help)
            head -35 "$0" | tail -30
            exit 0
            ;;
        *)
            error_exit "Unknown option: $1"
            ;;
    esac
done

# Validate
if [[ -z "$SENDER_PATTERN" && -z "$SUBJECT_PATTERN" && -z "$MESSAGE_ID" ]]; then
    error_exit "Please specify --sender, --subject, or --message-id"
fi

# Convert flag color to index
case "$FLAG_COLOR" in
    red)    FLAG_INDEX=0 ;;
    orange) FLAG_INDEX=1 ;;
    yellow) FLAG_INDEX=2 ;;
    green)  FLAG_INDEX=3 ;;
    blue)   FLAG_INDEX=4 ;;
    purple) FLAG_INDEX=5 ;;
    gray)   FLAG_INDEX=6 ;;
    *)      error_exit "Invalid flag color. Use: red, orange, yellow, green, blue, purple, gray" ;;
esac

# Escape patterns
SENDER_ESCAPED=$(escape_for_applescript "$SENDER_PATTERN")
SUBJECT_ESCAPED=$(escape_for_applescript "$SUBJECT_PATTERN")
MESSAGE_ID_ESCAPED=$(escape_for_applescript "$MESSAGE_ID")
ACCOUNT_ESCAPED=$(escape_for_applescript "$ACCOUNT")
MAILBOX_ESCAPED=$(escape_for_applescript "$MAILBOX")

osascript <<EOF
tell application "Mail"
    set matchingMsgs to {}
    set mailboxesToSearch to {}

    -- Determine which mailboxes to search
    if "$ACCOUNT_ESCAPED" is not "" then
        try
            set acct to account "$ACCOUNT_ESCAPED"
            if "$MAILBOX_ESCAPED" is not "" then
                set mailboxesToSearch to {mailbox "$MAILBOX_ESCAPED" of acct}
            else
                set mailboxesToSearch to mailboxes of acct
            end if
        on error
            return "Error: Account '$ACCOUNT_ESCAPED' not found."
        end try
    else
        -- Search inbox and common mailboxes
        set mailboxesToSearch to {inbox}
        repeat with acct in accounts
            try
                set mailboxesToSearch to mailboxesToSearch & {mailbox "Archive" of acct}
            end try
        end repeat
    end if

    -- Search for matching messages
    repeat with mb in mailboxesToSearch
        try
            repeat with msg in messages of mb
                set includeMsg to true

                -- Check message ID
                if "$MESSAGE_ID_ESCAPED" is not "" then
                    if message id of msg is not "$MESSAGE_ID_ESCAPED" then
                        set includeMsg to false
                    end if
                else
                    -- Check sender filter
                    if "$SENDER_ESCAPED" is not "" then
                        if sender of msg does not contain "$SENDER_ESCAPED" then
                            set includeMsg to false
                        end if
                    end if

                    -- Check subject filter
                    if includeMsg and "$SUBJECT_ESCAPED" is not "" then
                        if subject of msg does not contain "$SUBJECT_ESCAPED" then
                            set includeMsg to false
                        end if
                    end if
                end if

                if includeMsg then
                    set end of matchingMsgs to msg
                    if (count of matchingMsgs) >= $LIMIT then
                        exit repeat
                    end if
                end if
            end repeat
            if (count of matchingMsgs) >= $LIMIT then
                exit repeat
            end if
        end try
    end repeat

    set msgCount to count of matchingMsgs
    if msgCount is 0 then
        return "No matching messages found."
    end if

    -- Apply flag changes
    set markedCount to 0
    repeat with msg in matchingMsgs
        if $UNFLAG then
            set flag index of msg to -1
            set flagged status of msg to false
        else
            set flag index of msg to $FLAG_INDEX
            set flagged status of msg to true
        end if
        set markedCount to markedCount + 1
    end repeat

    if $UNFLAG then
        return "Unflagged " & markedCount & " message(s)."
    else
        return "Marked " & markedCount & " message(s) with $FLAG_COLOR flag."
    end if
end tell
EOF
