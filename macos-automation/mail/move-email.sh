#!/bin/bash
# ==============================================================================
# move-email.sh - Move emails to Archive, Trash, or another mailbox
# ==============================================================================
# Description:
#   Moves emails matching the criteria to Archive, Trash, or a specified mailbox.
#   Emails are identified by message-id (most reliable), sender, or subject.
#
# Usage:
#   ./move-email.sh --message-id "<abc123@mail.example.com>" --to archive
#   ./move-email.sh --subject "Newsletter" --sender "news@" --to trash
#   ./move-email.sh --message-id "<abc123>" --to "Receipts" --account "Work"
#
# Options:
#   --message-id <id>     Match specific email by Message-ID header (recommended)
#   --sender <pattern>    Match emails from sender containing pattern
#   --subject <pattern>   Match emails with subject containing pattern
#   --account <name>      Only search in specified account
#   --mailbox <name>      Only search in specified mailbox (default: Inbox)
#   --to <destination>    Where to move: archive, trash, or mailbox name (required)
#   --limit <n>           Limit number of messages to move (default: 10)
#
# Examples:
#   ./move-email.sh --message-id "<abc@example.com>" --to archive
#   ./move-email.sh --subject "Unsubscribe" --to trash --limit 50
#   ./move-email.sh --sender "receipts@" --to "Receipts" --account "Personal"
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
SENDER_PATTERN=""
SUBJECT_PATTERN=""
MESSAGE_ID=""
ACCOUNT=""
MAILBOX=""
DESTINATION=""
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
        --to)
            DESTINATION="$2"
            shift 2
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

# Validate required arguments
if [[ -z "$SENDER_PATTERN" && -z "$SUBJECT_PATTERN" && -z "$MESSAGE_ID" ]]; then
    error_exit "Please specify --sender, --subject, or --message-id"
fi

if [[ -z "$DESTINATION" ]]; then
    error_exit "Please specify --to (archive, trash, or mailbox name)"
fi

# Normalize destination
DEST_LOWER=$(echo "$DESTINATION" | tr '[:upper:]' '[:lower:]')

# Escape patterns for AppleScript
SENDER_ESCAPED=$(escape_for_applescript "$SENDER_PATTERN")
SUBJECT_ESCAPED=$(escape_for_applescript "$SUBJECT_PATTERN")
MESSAGE_ID_ESCAPED=$(escape_for_applescript "$MESSAGE_ID")
ACCOUNT_ESCAPED=$(escape_for_applescript "$ACCOUNT")
MAILBOX_ESCAPED=$(escape_for_applescript "$MAILBOX")
DESTINATION_ESCAPED=$(escape_for_applescript "$DESTINATION")

osascript <<EOF
tell application "Mail"
    set matchingMsgs to {}
    set mailboxesToSearch to {}
    set sourceAccount to missing value

    -- Determine which mailboxes to search
    if "$ACCOUNT_ESCAPED" is not "" then
        try
            set sourceAccount to account "$ACCOUNT_ESCAPED"
            if "$MAILBOX_ESCAPED" is not "" then
                set mailboxesToSearch to {mailbox "$MAILBOX_ESCAPED" of sourceAccount}
            else
                -- Search inbox by default for the account
                set mailboxesToSearch to {inbox of sourceAccount}
            end if
        on error
            return "Error: Account '$ACCOUNT_ESCAPED' not found."
        end try
    else
        -- Search all inboxes if no account specified
        if "$MAILBOX_ESCAPED" is not "" then
            repeat with acct in accounts
                try
                    set end of mailboxesToSearch to mailbox "$MAILBOX_ESCAPED" of acct
                end try
            end repeat
        else
            set mailboxesToSearch to {inbox}
        end if
    end if

    -- Search for matching messages
    repeat with mb in mailboxesToSearch
        try
            set msgAccount to account of mb
            repeat with msg in messages of mb
                set includeMsg to true

                -- Check message ID (most specific)
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
                    set end of matchingMsgs to {theMsg:msg, theAccount:msgAccount}
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

    -- Move messages to destination
    set movedCount to 0
    set destType to "$DEST_LOWER"

    repeat with msgInfo in matchingMsgs
        set msg to theMsg of msgInfo
        set msgAcct to theAccount of msgInfo

        try
            if destType is "archive" then
                -- Move to account's Archive mailbox
                set destMailbox to mailbox "Archive" of msgAcct
                move msg to destMailbox
            else if destType is "trash" then
                -- Move to account's Trash
                set destMailbox to trash mailbox of msgAcct
                move msg to destMailbox
            else
                -- Move to named mailbox in same account
                set destMailbox to mailbox "$DESTINATION_ESCAPED" of msgAcct
                move msg to destMailbox
            end if
            set movedCount to movedCount + 1
        on error errMsg
            -- Try without account context for special mailboxes
            try
                if destType is "archive" then
                    -- Some accounts use "All Mail" instead
                    set destMailbox to mailbox "All Mail" of msgAcct
                    move msg to destMailbox
                    set movedCount to movedCount + 1
                end if
            end try
        end try
    end repeat

    if movedCount is 0 then
        return "Error: Could not move messages. Destination mailbox may not exist."
    else if destType is "archive" then
        return "Moved " & movedCount & " message(s) to Archive."
    else if destType is "trash" then
        return "Moved " & movedCount & " message(s) to Trash."
    else
        return "Moved " & movedCount & " message(s) to '$DESTINATION_ESCAPED'."
    end if
end tell
EOF
