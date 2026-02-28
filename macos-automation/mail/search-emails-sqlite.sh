#!/bin/bash
# ==============================================================================
# search-emails-sqlite.sh - Fast email metadata search via SQLite
# ==============================================================================
# Description:
#   Searches the Mail.app Envelope Index SQLite database for email metadata.
#   Much faster than AppleScript (~100ms vs 10-30s) but cannot retrieve email
#   body content. Falls back gracefully (exit code 2) when DB is unavailable.
#
# Usage:
#   ./search-emails-sqlite.sh --sender <pattern>
#   ./search-emails-sqlite.sh --subject <pattern> --days 7
#   ./search-emails-sqlite.sh --message-id "<id>"
#
# Options:
#   --sender <pattern>   Search for emails from sender containing pattern
#   --subject <pattern>  Search for emails with subject containing pattern
#   --message-id <id>    Search for specific email by RFC Message-ID string
#   --account <name>     Only search in specified account
#   --mailbox <name>     Search specific mailbox (e.g., "Archive", "Sent Items")
#   --today              Only show emails from today
#   --days <n>           Only show emails from last n days
#   --limit <n>          Limit results to n messages (default: 20)
#   --all-mailboxes      Search all mailboxes including Sent, Trash, etc.
#
# Exit codes:
#   0 - Success (results printed to stdout)
#   1 - No search criteria provided
#   2 - DB not found / not readable (caller should fall back to AppleScript)
#
# Example:
#   ./search-emails-sqlite.sh --sender "john@example.com" --today
#   ./search-emails-sqlite.sh --subject "Invoice" --days 7 --limit 10
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Default values
SENDER_PATTERN=""
SUBJECT_PATTERN=""
MESSAGE_ID=""
ACCOUNT=""
MAILBOX=""
TODAY_ONLY=false
DAYS=""
LIMIT=20
ALL_MAILBOXES=false

# Parse arguments (same CLI as search-emails.sh)
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
        --with-content|--with-links)
            # Ignored — SQLite doesn't have email body content
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

# Require at least one search criterion
if [[ -z "$SENDER_PATTERN" && -z "$SUBJECT_PATTERN" && -z "$ACCOUNT" && -z "$MESSAGE_ID" && "$TODAY_ONLY" == "false" && -z "$DAYS" ]]; then
    error_exit "Please specify --sender, --subject, --account, --message-id, --today, or --days"
fi

# --message-id requires matching the RFC Message-ID string which lives in
# .emlx files on disk, not in the SQLite DB. Fall back to AppleScript for this.
if [[ -n "$MESSAGE_ID" ]]; then
    exit 2
fi

# Auto-detect DB path: pick highest Mail version directory
MAIL_DIR=""
DB_PATH=""
for d in "$HOME"/Library/Mail/V*/MailData/"Envelope Index"; do
    if [[ -f "$d" ]]; then
        DB_PATH="$d"
        MAIL_DIR="${d%/MailData/Envelope Index}"
    fi
done

if [[ -z "$DB_PATH" ]]; then
    # DB not found — signal caller to fall back
    exit 2
fi

if [[ ! -r "$DB_PATH" ]]; then
    # Not readable (needs Full Disk Access) — signal fallback
    exit 2
fi

# Build dynamic WHERE clauses
CONDITIONS=()

# Sender filter (match address or display name)
if [[ -n "$SENDER_PATTERN" ]]; then
    SENDER_SQL="${SENDER_PATTERN//\'/\'\'}"
    CONDITIONS+=("(a.address LIKE '%${SENDER_SQL}%' OR a.comment LIKE '%${SENDER_SQL}%')")
fi

# Subject filter
if [[ -n "$SUBJECT_PATTERN" ]]; then
    SUBJ_SQL="${SUBJECT_PATTERN//\'/\'\'}"
    CONDITIONS+=("s.subject LIKE '%${SUBJ_SQL}%'")
fi

# Date filters (date_sent is Unix epoch in this DB version)
if [[ "$TODAY_ONLY" == "true" ]]; then
    CONDITIONS+=("m.date_sent > CAST(strftime('%s', 'now', 'start of day', 'localtime') AS INTEGER)")
elif [[ -n "$DAYS" ]]; then
    CONDITIONS+=("m.date_sent > CAST(strftime('%s', 'now', '-${DAYS} days') AS INTEGER)")
fi

# Mailbox / account filters
if [[ -n "$MAILBOX" ]]; then
    MB_SQL="${MAILBOX//\'/\'\'}"
    CONDITIONS+=("mb.url LIKE '%/${MB_SQL}'")
elif [[ -n "$ACCOUNT" ]]; then
    ACCT_SQL="${ACCOUNT//\'/\'\'}"
    CONDITIONS+=("mb.url LIKE '%${ACCT_SQL}%'")
    if [[ "$ALL_MAILBOXES" != "true" ]]; then
        CONDITIONS+=("(mb.url LIKE '%/INBOX' OR mb.url LIKE '%/Inbox' OR mb.url LIKE '%/Archive' OR mb.url LIKE '%/All%20Mail' OR mb.url LIKE '%/All Mail')")
    fi
elif [[ "$ALL_MAILBOXES" != "true" ]]; then
    # Default: INBOX + Archive + Gmail's All Mail (case variants)
    # Gmail moves archived/filtered emails out of INBOX into [Gmail]/All Mail
    # URLs are percent-encoded in SQLite, so match both encoded and decoded forms
    CONDITIONS+=("(mb.url LIKE '%/INBOX' OR mb.url LIKE '%/Inbox' OR mb.url LIKE '%/Archive' OR mb.url LIKE '%/All%20Mail' OR mb.url LIKE '%/All Mail')")
fi

# Exclude deleted messages
CONDITIONS+=("m.deleted = 0")

# Join conditions with AND
WHERE_CLAUSE=""
for i in "${!CONDITIONS[@]}"; do
    if [[ $i -eq 0 ]]; then
        WHERE_CLAUSE="${CONDITIONS[$i]}"
    else
        WHERE_CLAUSE="${WHERE_CLAUSE} AND ${CONDITIONS[$i]}"
    fi
done

# Safety: if no conditions besides deleted=0, exit
if [[ -z "$WHERE_CLAUSE" ]]; then
    exit 2
fi

# Query the Envelope Index (read-only — WAL mode allows concurrent reads without blocking Mail.app)
RESULT=$(sqlite3 "file:${DB_PATH}?mode=ro" <<SQL 2>&1
.headers off
.mode list
.separator "|"
SELECT
    m.ROWID,
    s.subject,
    CASE WHEN a.comment IS NOT NULL AND a.comment != ''
         THEN a.comment || ' <' || a.address || '>'
         ELSE COALESCE(a.address, '')
    END AS sender_display,
    datetime(m.date_sent, 'unixepoch', 'localtime') AS date_str,
    CASE WHEN m.read = 1 THEN 'true' ELSE 'false' END AS read_status
FROM messages m
LEFT JOIN subjects s ON m.subject = s.ROWID
LEFT JOIN addresses a ON m.sender = a.ROWID
LEFT JOIN mailboxes mb ON m.mailbox = mb.ROWID
WHERE ${WHERE_CLAUSE}
ORDER BY m.date_sent DESC
LIMIT ${LIMIT};
SQL
)

RC=$?
if [[ $RC -ne 0 ]]; then
    # Any SQLite error — signal fallback to AppleScript
    exit 2
fi

if [[ -z "$RESULT" ]]; then
    echo "No messages found matching criteria."
    exit 0
fi

# Extract RFC Message-ID from .emlx files on disk.
# .emlx files are stored at:
#   {MAIL_DIR}/{account-uuid}/{mailbox}.mbox/*/Data/{d1}/{d2}/Messages/{ROWID}[.partial].emlx
# where d1 = (ROWID/1000)%10, d2 = ROWID/10000
extract_message_id() {
    local rowid="$1"
    local d1=$(( (rowid / 1000) % 10 ))
    local d2=$(( rowid / 10000 ))
    local emlx
    # Try flat mailbox structure first (most accounts)
    emlx=$(ls "${MAIL_DIR}"/*/*.mbox/*/Data/${d1}/${d2}/Messages/${rowid}.*emlx 2>/dev/null | head -1)
    # Try nested structure (Gmail: [Gmail].mbox/All Mail.mbox/…)
    if [[ -z "$emlx" ]]; then
        emlx=$(ls "${MAIL_DIR}"/*/*.mbox/*.mbox/*/Data/${d1}/${d2}/Messages/${rowid}.*emlx 2>/dev/null | head -1)
    fi
    if [[ -n "$emlx" ]]; then
        sed -n '/^[Mm]essage-[Ii][Dd]:[[:space:]]*/{
            s/^[Mm]essage-[Ii][Dd]:[[:space:]]*//
            /./{ p; q; }
            n
            s/^[[:space:]]*//
            p; q
        }' "$emlx"
    fi
}

# Count results
MSG_COUNT=0
while IFS= read -r _; do
    MSG_COUNT=$((MSG_COUNT + 1))
done <<< "$RESULT"

# Format output to match AppleScript search-emails.sh format
echo "=== FOUND ${MSG_COUNT} MESSAGES ==="
echo ""

while IFS='|' read -r rowid subject sender date_str read_status; do
    rfc_msg_id=$(extract_message_id "$rowid")
    echo "Message-ID: ${rfc_msg_id:-unknown-${rowid}}"
    echo "Subject: ${subject}"
    echo "From: ${sender}"
    echo "Date: ${date_str}"
    echo "Read: ${read_status}"
    echo "---"
done <<< "$RESULT"
