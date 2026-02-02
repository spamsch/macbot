#!/bin/bash
# ==============================================================================
# download-attachments.sh - Download email attachments to a folder
# ==============================================================================
# Description:
#   Downloads attachments from emails matching the criteria to a specified folder.
#   Emails are identified by message-id (most reliable), sender, or subject.
#
# Usage:
#   ./download-attachments.sh --message-id "<abc123@mail.example.com>" --output ~/Downloads
#   ./download-attachments.sh --subject "Invoice" --sender "billing@" --output ~/Documents/Invoices
#
# Options:
#   --message-id <id>     Match specific email by Message-ID header (recommended)
#   --sender <pattern>    Match emails from sender containing pattern
#   --subject <pattern>   Match emails with subject containing pattern
#   --account <name>      Only search in specified account
#   --mailbox <name>      Only search in specified mailbox (default: Inbox)
#   --output <folder>     Destination folder for attachments (required)
#   --limit <n>           Limit number of emails to process (default: 5)
#
# Examples:
#   ./download-attachments.sh --message-id "<abc@example.com>" --output ~/Downloads
#   ./download-attachments.sh --subject "Report" --output ~/Documents --limit 10
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
SENDER_PATTERN=""
SUBJECT_PATTERN=""
MESSAGE_ID=""
ACCOUNT=""
MAILBOX=""
OUTPUT_DIR=""
LIMIT=5

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
        --output)
            OUTPUT_DIR="$2"
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

if [[ -z "$OUTPUT_DIR" ]]; then
    error_exit "Please specify --output <folder>"
fi

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR" || error_exit "Failed to create output directory: $OUTPUT_DIR"

# Get absolute path for output
OUTPUT_DIR_ABS=$(cd "$OUTPUT_DIR" && pwd)

# Escape patterns for AppleScript
SENDER_ESCAPED=$(escape_for_applescript "$SENDER_PATTERN")
SUBJECT_ESCAPED=$(escape_for_applescript "$SUBJECT_PATTERN")
MESSAGE_ID_ESCAPED=$(escape_for_applescript "$MESSAGE_ID")
ACCOUNT_ESCAPED=$(escape_for_applescript "$ACCOUNT")
MAILBOX_ESCAPED=$(escape_for_applescript "$MAILBOX")
OUTPUT_ESCAPED=$(escape_for_applescript "$OUTPUT_DIR_ABS")

osascript <<EOF
use AppleScript version "2.4"
use scripting additions
use framework "Foundation"

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

    -- Search for matching messages
    repeat with mb in mailboxesToSearch
        try
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

    -- Process attachments
    set savedCount to 0
    set attachmentList to {}
    set outputFolder to "$OUTPUT_ESCAPED"

    repeat with msg in matchingMsgs
        set attachments_of_msg to mail attachments of msg
        if (count of attachments_of_msg) > 0 then
            repeat with att in attachments_of_msg
                set attName to name of att
                set destPath to outputFolder & "/" & attName

                -- Handle duplicate filenames by adding number
                set counter to 1
                set baseName to attName
                set ext to ""
                if attName contains "." then
                    set tid to AppleScript's text item delimiters
                    set AppleScript's text item delimiters to "."
                    set parts to text items of attName
                    set AppleScript's text item delimiters to tid
                    if (count of parts) > 1 then
                        set ext to "." & (last item of parts)
                        set baseName to (items 1 thru -2 of parts as text)
                    end if
                end if

                -- Check if file exists and increment counter
                tell application "System Events"
                    repeat while (exists file destPath)
                        set destPath to outputFolder & "/" & baseName & "_" & counter & ext
                        set counter to counter + 1
                    end repeat
                end tell

                try
                    save att in POSIX file destPath
                    set savedCount to savedCount + 1
                    set end of attachmentList to attName
                end try
            end repeat
        end if
    end repeat

    if savedCount is 0 then
        return "No attachments found in " & msgCount & " matching message(s)."
    else
        return "Saved " & savedCount & " attachment(s) to " & outputFolder & ": " & (attachmentList as text)
    end if
end tell
EOF
