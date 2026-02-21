#!/bin/bash
# ==============================================================================
# send-email.sh - Send an email via Mail.app
# ==============================================================================
# Description:
#   Creates and sends an email using Apple Mail. Can optionally open the
#   compose window for review before sending.
#
# Usage:
#   ./send-email.sh --to <email> --subject <subject> --body <body>
#   ./send-email.sh --to <email> --subject <subject> --body-file <file>
#   ./send-email.sh --to <email> --subject <subject> --body <body> --cc <email>
#   ./send-email.sh --to <email> --subject <subject> --body <body> --draft
#
# Options:
#   --to <email>        Recipient email address (required)
#   --subject <text>    Email subject (required)
#   --body <text>       Email body text
#   --body-file <file>  Read body from file
#   --cc <email>        CC recipient (optional)
#   --bcc <email>       BCC recipient (optional)
#   --attachment <path> File to attach (repeatable for multiple files)
#   --draft             Save as draft (silently, without opening window)
#   --draft-visible     Save as draft and open compose window for review
#
# Example:
#   ./send-email.sh --to "john@example.com" --subject "Hello" --body "Hi there!"
#   ./send-email.sh --to "team@example.com" --subject "Report" --body-file report.txt --draft
#   ./send-email.sh --to "john@example.com" --subject "Invoice" --body "See attached" --attachment "/path/to/invoice.pdf" --draft-visible
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
TO=""
SUBJECT=""
BODY=""
CC=""
BCC=""
DRAFT=false
DRAFT_VISIBLE=false
ATTACHMENTS=()

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --to)
            TO="$2"
            shift 2
            ;;
        --subject)
            SUBJECT="$2"
            shift 2
            ;;
        --body)
            BODY="$2"
            shift 2
            ;;
        --body-file)
            if [[ -f "$2" ]]; then
                BODY=$(cat "$2")
            else
                error_exit "Body file not found: $2"
            fi
            shift 2
            ;;
        --cc)
            CC="$2"
            shift 2
            ;;
        --bcc)
            BCC="$2"
            shift 2
            ;;
        --draft)
            DRAFT=true
            shift
            ;;
        --draft-visible)
            DRAFT=true
            DRAFT_VISIBLE=true
            shift
            ;;
        --attachment)
            [[ -f "$2" ]] || error_exit "Attachment file not found: $2"
            ATTACHMENTS+=("$2")
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

# Validate required fields
[[ -z "$TO" ]] && error_exit "--to is required"
[[ -z "$SUBJECT" ]] && error_exit "--subject is required"
[[ -z "$BODY" ]] && error_exit "--body or --body-file is required"

# Escape special characters
SUBJECT_ESCAPED=$(escape_for_applescript "$SUBJECT")
BODY_ESCAPED=$(escape_for_applescript "$BODY")

# Build AppleScript
APPLESCRIPT="tell application \"Mail\"
    set newMsg to make new outgoing message with properties {subject:\"$SUBJECT_ESCAPED\", content:\"$BODY_ESCAPED\", visible:$DRAFT_VISIBLE}

    tell newMsg
        make new to recipient at end of to recipients with properties {address:\"$TO\"}"

if [[ -n "$CC" ]]; then
    APPLESCRIPT="$APPLESCRIPT
        make new cc recipient at end of cc recipients with properties {address:\"$CC\"}"
fi

if [[ -n "$BCC" ]]; then
    APPLESCRIPT="$APPLESCRIPT
        make new bcc recipient at end of bcc recipients with properties {address:\"$BCC\"}"
fi

# Add attachments (must use POSIX path for Mail.app)
for attachment in "${ATTACHMENTS[@]}"; do
    ATT_ESCAPED=$(escape_for_applescript "$attachment")
    APPLESCRIPT="$APPLESCRIPT
        make new attachment with properties {file name:(POSIX file \"$ATT_ESCAPED\" as alias)} at after the last paragraph"
done

APPLESCRIPT="$APPLESCRIPT
    end tell"

if [[ "$DRAFT" == "false" ]]; then
    APPLESCRIPT="$APPLESCRIPT
    send newMsg
    return \"Email sent to $TO\""
else
    if [[ "$DRAFT_VISIBLE" == "true" ]]; then
        APPLESCRIPT="$APPLESCRIPT
    activate"
    fi
    APPLESCRIPT="$APPLESCRIPT
    return \"Draft saved for $TO (in Drafts folder)\""
fi

APPLESCRIPT="$APPLESCRIPT
end tell"

osascript -e "$APPLESCRIPT"
