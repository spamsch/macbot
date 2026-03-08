#!/bin/bash
# ==============================================================================
# get-unread-summary.sh - Get a summary of unread emails
# ==============================================================================
# Description:
#   Retrieves a list of all unread emails from the inbox, showing subject,
#   sender, and date received.
#
# Usage:
#   ./get-unread-summary.sh [--count-only]
#
# Options:
#   --count-only    Only show the count of unread messages
#
# Output:
#   A formatted list of unread emails or just the count
#
# Example:
#   ./get-unread-summary.sh
#   ./get-unread-summary.sh --count-only
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Parse arguments
COUNT_ONLY=false
if [[ "$1" == "--count-only" ]]; then
    COUNT_ONLY=true
fi

if [[ "$COUNT_ONLY" == "true" ]]; then
    # Just return the count
    osascript -e '
    tell application "Mail"
        return count of (messages of inbox whose read status is false)
    end tell
    '
else
    # Return full summary (per-message iteration; bulk fetch fails on unified inbox)
    osascript <<'EOF'
tell application "Mail"
    set unreadMsgs to (messages of inbox whose read status is false)
    set msgCount to count of unreadMsgs

    if msgCount is 0 then
        return "No unread messages in inbox."
    end if

    set output to "=== UNREAD EMAILS (" & msgCount & ") ===" & return & return

    repeat with msg in unreadMsgs
        set output to output & "Message-ID: " & message id of msg & return
        set output to output & "Account: " & name of account of mailbox of msg & return
        set output to output & "Subject: " & subject of msg & return
        set output to output & "From: " & sender of msg & return
        set output to output & "Date: " & (date received of msg as string) & return
        set output to output & "---" & return
    end repeat

    return output
end tell
EOF
fi
