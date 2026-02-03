#!/bin/bash
# ==============================================================================
# search-emails.sh - Search emails by sender, subject, or content
# ==============================================================================
# Description:
#   Searches emails matching specified criteria. Can filter by sender, subject,
#   date range, account, and mailbox.
#
# Usage:
#   ./search-emails.sh --sender <pattern>
#   ./search-emails.sh --subject <pattern>
#   ./search-emails.sh --sender <pattern> --today
#   ./search-emails.sh --sender <pattern> --days 7
#   ./search-emails.sh --sender <pattern> --mailbox "Archive"
#
# Options:
#   --sender <pattern>   Search for emails from sender containing pattern
#   --subject <pattern>  Search for emails with subject containing pattern
#   --account <name>     Only search in specified account
#   --mailbox <name>     Search specific mailbox (default: all mailboxes)
#   --today              Only show emails from today
#   --days <n>           Only show emails from last n days
#   --limit <n>          Limit results to n messages (default: 20)
#   --all-mailboxes      Search all mailboxes including Archive, Sent, etc.
#
# Example:
#   ./search-emails.sh --sender "john@example.com" --today
#   ./search-emails.sh --subject "Invoice" --days 7 --limit 10
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
SENDER_PATTERN=""
SUBJECT_PATTERN=""
ACCOUNT=""
MAILBOX=""
TODAY_ONLY=false
DAYS=""
LIMIT=20
ALL_MAILBOXES=false

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
        --account)
            ACCOUNT="$2"
            shift 2
            ;;
        --mailbox)
            MAILBOX="$2"
            shift 2
            ;;
        --today)
            TODAY_ONLY=true
            shift
            ;;
        --days)
            DAYS="$2"
            shift 2
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        --all-mailboxes)
            ALL_MAILBOXES=true
            shift
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

# Allow searching without sender/subject if account is specified with date filter
if [[ -z "$SENDER_PATTERN" && -z "$SUBJECT_PATTERN" && -z "$ACCOUNT" ]]; then
    error_exit "Please specify --sender, --subject, or --account with date filter"
fi

# Escape patterns for AppleScript
SENDER_ESCAPED=$(escape_for_applescript "$SENDER_PATTERN")
SUBJECT_ESCAPED=$(escape_for_applescript "$SUBJECT_PATTERN")
ACCOUNT_ESCAPED=$(escape_for_applescript "$ACCOUNT")
MAILBOX_ESCAPED=$(escape_for_applescript "$MAILBOX")

# Calculate days for date filter (default 0 = no filter)
DAYS_NUM=${DAYS:-0}
if [[ "$TODAY_ONLY" == "true" ]]; then
    DAYS_NUM=1
fi

osascript <<EOF
tell application "Mail"
    set matchingMsgs to {}
    set cutoffDate to missing value

    -- Calculate cutoff date if filtering by days
    if $DAYS_NUM > 0 then
        set cutoffDate to (current date) - ($DAYS_NUM * 24 * 60 * 60)
    end if

    -- Determine which mailboxes to search
    set mailboxesToSearch to {}

    if "$ACCOUNT_ESCAPED" is not "" then
        -- Search specific account (by name or email address)
        set acct to missing value
        set searchTerm to "$ACCOUNT_ESCAPED"

        -- First try exact match by name
        try
            set acct to account searchTerm
        end try

        -- If not found, search by email address or partial name match
        if acct is missing value then
            repeat with a in accounts
                -- Check if email addresses contain the search term
                try
                    set addrList to email addresses of a
                    repeat with addr in addrList
                        set addrStr to addr as text
                        if addrStr contains searchTerm then
                            set acct to a
                            exit repeat
                        end if
                    end repeat
                end try
                -- Also check if account name contains the search term (case-insensitive)
                if acct is missing value then
                    set acctName to name of a
                    set lcName to do shell script "echo " & quoted form of acctName & " | tr '[:upper:]' '[:lower:]'"
                    set lcSearch to do shell script "echo " & quoted form of searchTerm & " | tr '[:upper:]' '[:lower:]'"
                    if lcName contains lcSearch or lcSearch contains lcName then
                        set acct to a
                    end if
                end if
                if acct is not missing value then exit repeat
            end repeat
        end if

        if acct is missing value then
            -- List available accounts in error message
            set acctNames to {}
            repeat with a in accounts
                set end of acctNames to name of a
            end repeat
            set AppleScript's text item delimiters to ", "
            set acctList to acctNames as text
            return "Account '" & searchTerm & "' not found. Available accounts: " & acctList
        end if

        if "$MAILBOX_ESCAPED" is not "" then
            set mailboxesToSearch to {mailbox "$MAILBOX_ESCAPED" of acct}
        else if $ALL_MAILBOXES then
            set mailboxesToSearch to mailboxes of acct
        else
            -- Default: search Inbox and Archive of the account
            try
                set mailboxesToSearch to mailboxesToSearch & {mailbox "Inbox" of acct}
            end try
            try
                set mailboxesToSearch to mailboxesToSearch & {mailbox "INBOX" of acct}
            end try
            try
                set mailboxesToSearch to mailboxesToSearch & {mailbox "Archive" of acct}
            end try
        end if
    else if "$MAILBOX_ESCAPED" is not "" then
        -- Search specific mailbox name across all accounts
        repeat with acct in accounts
            try
                set mailboxesToSearch to mailboxesToSearch & {mailbox "$MAILBOX_ESCAPED" of acct}
            end try
        end repeat
    else if $ALL_MAILBOXES then
        -- Search all mailboxes in all accounts
        repeat with acct in accounts
            set mailboxesToSearch to mailboxesToSearch & (mailboxes of acct)
        end repeat
    else
        -- Default: search inbox and Archive
        set mailboxesToSearch to {inbox}
        repeat with acct in accounts
            try
                set mailboxesToSearch to mailboxesToSearch & {mailbox "Archive" of acct}
            end try
        end repeat
    end if

    -- Search each mailbox
    repeat with mb in mailboxesToSearch
        try
            set mbMsgs to messages of mb

            repeat with msg in mbMsgs
                set includeMsg to true

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

                -- Check date filter
                if includeMsg and cutoffDate is not missing value then
                    if date received of msg < cutoffDate then
                        set includeMsg to false
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
        return "No messages found matching criteria."
    end if

    set output to "=== FOUND " & msgCount & " MESSAGES ===" & return & return

    repeat with msg in matchingMsgs
        set output to output & "Message-ID: " & message id of msg & return
        set output to output & "Subject: " & subject of msg & return
        set output to output & "From: " & sender of msg & return
        set output to output & "Date: " & (date received of msg as string) & return
        set output to output & "Read: " & read status of msg & return
        set output to output & "---" & return
    end repeat

    return output
end tell
EOF
