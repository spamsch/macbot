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

# Use different strategy based on search criteria
if [[ -n "$MESSAGE_ID" ]]; then
    # Message-ID search: use whose clause for direct, reliable lookup
    osascript <<EOF
tell application "Mail"
    set movedCount to 0
    set destType to "$DEST_LOWER"
    set targetId to "$MESSAGE_ID_ESCAPED"
    set foundMsgs to {}

    -- Search in specified mailbox or inbox
    if "$ACCOUNT_ESCAPED" is not "" then
        try
            set acct to account "$ACCOUNT_ESCAPED"
            if "$MAILBOX_ESCAPED" is not "" then
                set mbToSearch to mailbox "$MAILBOX_ESCAPED" of acct
            else
                set mbToSearch to inbox of acct
            end if
            set foundMsgs to (messages of mbToSearch whose message id is targetId)
        on error
            return "Error: Account '$ACCOUNT_ESCAPED' not found."
        end try
    else if "$MAILBOX_ESCAPED" is not "" then
        -- Search specified mailbox across all accounts
        repeat with acct in accounts
            try
                set mbToSearch to mailbox "$MAILBOX_ESCAPED" of acct
                set acctMsgs to (messages of mbToSearch whose message id is targetId)
                if (count of acctMsgs) > 0 then
                    set foundMsgs to acctMsgs
                    exit repeat
                end if
            end try
        end repeat
    else
        -- Search unified inbox
        set foundMsgs to (messages of inbox whose message id is targetId)
    end if

    if (count of foundMsgs) is 0 then
        return "No matching messages found."
    end if

    repeat with msg in foundMsgs
        set msgAcct to account of mailbox of msg
        set moved to false

        if destType is "archive" then
            -- Try Archive, then All Mail (Gmail)
            repeat with archiveName in {"Archive", "All Mail"}
                try
                    set destMailbox to mailbox archiveName of msgAcct
                    move msg to destMailbox
                    set movedCount to movedCount + 1
                    set moved to true
                    exit repeat
                end try
            end repeat
        else if destType is "trash" then
            -- Try trash mailbox property, then common trash names
            try
                set destMailbox to trash mailbox of msgAcct
                move msg to destMailbox
                set movedCount to movedCount + 1
                set moved to true
            on error
                repeat with trashName in {"Deleted Items", "Trash", "Bin"}
                    try
                        set destMailbox to mailbox trashName of msgAcct
                        move msg to destMailbox
                        set movedCount to movedCount + 1
                        set moved to true
                        exit repeat
                    end try
                end repeat
            end try
        else
            try
                set destMailbox to mailbox "$DESTINATION_ESCAPED" of msgAcct
                move msg to destMailbox
                set movedCount to movedCount + 1
                set moved to true
            end try
        end if

        if movedCount >= $LIMIT then exit repeat
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
else
    # Sender/Subject search: collect IDs first, then move by ID
    osascript <<EOF
tell application "Mail"
    set matchingIds to {}
    set mailboxesToSearch to {}

    -- Determine which mailboxes to search
    if "$ACCOUNT_ESCAPED" is not "" then
        try
            set acct to account "$ACCOUNT_ESCAPED"
            if "$MAILBOX_ESCAPED" is not "" then
                set mailboxesToSearch to {mailbox "$MAILBOX_ESCAPED" of acct}
            else
                set mailboxesToSearch to {inbox of acct}
            end if
        on error
            return "Error: Account '$ACCOUNT_ESCAPED' not found."
        end try
    else
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

    -- Collect matching message IDs and their mailboxes
    repeat with mb in mailboxesToSearch
        try
            repeat with msg in messages of mb
                set includeMsg to true

                if "$SENDER_ESCAPED" is not "" then
                    if sender of msg does not contain "$SENDER_ESCAPED" then
                        set includeMsg to false
                    end if
                end if

                if includeMsg and "$SUBJECT_ESCAPED" is not "" then
                    if subject of msg does not contain "$SUBJECT_ESCAPED" then
                        set includeMsg to false
                    end if
                end if

                if includeMsg then
                    set end of matchingIds to {msgId:message id of msg, msgMailbox:mb}
                    if (count of matchingIds) >= $LIMIT then exit repeat
                end if
            end repeat
            if (count of matchingIds) >= $LIMIT then exit repeat
        end try
    end repeat

    if (count of matchingIds) is 0 then
        return "No matching messages found."
    end if

    -- Move messages by ID (fresh lookup for each)
    set movedCount to 0
    set destType to "$DEST_LOWER"

    repeat with msgInfo in matchingIds
        set targetId to msgId of msgInfo
        set srcMailbox to msgMailbox of msgInfo

        set foundMsgs to (messages of srcMailbox whose message id is targetId)
        if (count of foundMsgs) > 0 then
            set msg to item 1 of foundMsgs
            set msgAcct to account of srcMailbox
            set moved to false

            if destType is "archive" then
                repeat with archiveName in {"Archive", "All Mail"}
                    try
                        set destMailbox to mailbox archiveName of msgAcct
                        move msg to destMailbox
                        set movedCount to movedCount + 1
                        set moved to true
                        exit repeat
                    end try
                end repeat
            else if destType is "trash" then
                try
                    set destMailbox to trash mailbox of msgAcct
                    move msg to destMailbox
                    set movedCount to movedCount + 1
                    set moved to true
                on error
                    repeat with trashName in {"Deleted Items", "Trash", "Bin"}
                        try
                            set destMailbox to mailbox trashName of msgAcct
                            move msg to destMailbox
                            set movedCount to movedCount + 1
                            set moved to true
                            exit repeat
                        end try
                    end repeat
                end try
            else
                try
                    set destMailbox to mailbox "$DESTINATION_ESCAPED" of msgAcct
                    move msg to destMailbox
                    set movedCount to movedCount + 1
                    set moved to true
                end try
            end if
        end if
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
fi
