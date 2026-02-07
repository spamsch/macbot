#!/bin/bash
# ==============================================================================
# search.sh - Search using macOS Spotlight index (mdfind)
# ==============================================================================
# Fast indexed search for emails, files, and documents.
# Much faster than AppleScript iteration for email search.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Defaults
SEARCH_QUERY=""
CONTENT_TYPE=""
EMAIL_FROM=""
EMAIL_TO=""
EMAIL_SUBJECT=""
BODY_TEXT=""
FILE_NAME=""
DAYS=""
LAST_USED=false
EXCLUDE_APPS=false
UNREAD_ONLY=false
FLAGGED_ONLY=false
HAS_ATTACHMENTS=false
SEARCH_DIR=""
LIMIT=20

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --query)   SEARCH_QUERY="$2"; shift 2 ;;
        --type)    CONTENT_TYPE="$2"; shift 2 ;;
        --from)    EMAIL_FROM="$2"; shift 2 ;;
        --to)      EMAIL_TO="$2"; shift 2 ;;
        --subject) EMAIL_SUBJECT="$2"; shift 2 ;;
        --body)    BODY_TEXT="$2"; shift 2 ;;
        --name)    FILE_NAME="$2"; shift 2 ;;
        --days)    DAYS="$2"; shift 2 ;;
        --last-used) LAST_USED=true; shift ;;
        --exclude-apps) EXCLUDE_APPS=true; shift ;;
        --unread)  UNREAD_ONLY=true; shift ;;
        --flagged) FLAGGED_ONLY=true; shift ;;
        --has-attachments) HAS_ATTACHMENTS=true; shift ;;
        --dir)     SEARCH_DIR="$2"; shift 2 ;;
        --limit)   LIMIT="$2"; shift 2 ;;
        *) error_exit "Unknown option: $1" ;;
    esac
done

# Need at least one search criterion
if [[ -z "$SEARCH_QUERY" && -z "$EMAIL_FROM" && -z "$EMAIL_TO" && \
      -z "$EMAIL_SUBJECT" && -z "$BODY_TEXT" && -z "$FILE_NAME" && \
      -z "$CONTENT_TYPE" && -z "$DAYS" && \
      "$LAST_USED" == false && \
      "$UNREAD_ONLY" == false && "$FLAGGED_ONLY" == false && \
      "$HAS_ATTACHMENTS" == false ]]; then
    error_exit "Must specify at least one search criterion (--query, --type, --from, --subject, --body, --name, --days, --last-used, --unread, --flagged, --has-attachments)"
fi

# --last-used requires --days to define the time window
if [[ "$LAST_USED" == true && -z "$DAYS" ]]; then
    DAYS=1
fi

# Build mdfind query from parameters
build_query() {
    local parts=()

    # Content type filter
    case "$CONTENT_TYPE" in
        email|mail)
            parts+=('kMDItemContentType == "com.apple.mail.email"')
            ;;
        pdf)
            parts+=('kMDItemContentType == "com.adobe.pdf"')
            ;;
        image)
            parts+=('kMDItemContentTypeTree == "public.image"')
            ;;
        document)
            parts+=('(kMDItemContentTypeTree == "public.composite-content" || kMDItemContentTypeTree == "public.text")')
            ;;
        presentation)
            parts+=('kMDItemContentTypeTree == "public.presentation"')
            ;;
        spreadsheet)
            parts+=('kMDItemContentTypeTree == "public.spreadsheet"')
            ;;
    esac

    # Email-specific filters
    if [[ -n "$EMAIL_FROM" ]]; then
        parts+=("kMDItemAuthorEmailAddresses == '*${EMAIL_FROM}*'cd")
    fi
    if [[ -n "$EMAIL_TO" ]]; then
        parts+=("kMDItemRecipientEmailAddresses == '*${EMAIL_TO}*'cd")
    fi
    if [[ -n "$EMAIL_SUBJECT" ]]; then
        parts+=("kMDItemSubject == '*${EMAIL_SUBJECT}*'cd")
    fi

    # Body/content text
    if [[ -n "$BODY_TEXT" ]]; then
        parts+=("kMDItemTextContent == '*${BODY_TEXT}*'cd")
    fi

    # File name
    if [[ -n "$FILE_NAME" ]]; then
        parts+=("kMDItemDisplayName == '*${FILE_NAME}*'cd")
    fi

    # Date filter
    if [[ -n "$DAYS" ]]; then
        local cutoff
        cutoff=$(date -v-"${DAYS}"d "+%Y-%m-%dT00:00:00Z")
        if $LAST_USED; then
            parts+=("kMDItemLastUsedDate >= \$time.iso(${cutoff})")
        elif [[ "$CONTENT_TYPE" == "email" || "$CONTENT_TYPE" == "mail" || \
              -n "$EMAIL_FROM" || -n "$EMAIL_TO" || -n "$EMAIL_SUBJECT" || \
              "$UNREAD_ONLY" == true || "$FLAGGED_ONLY" == true ]]; then
            parts+=("com_apple_mail_dateReceived >= \$time.iso(${cutoff})")
        else
            parts+=("kMDItemContentModificationDate >= \$time.iso(${cutoff})")
        fi
    fi

    # Note: --exclude-apps is handled in post-processing (mdfind doesn't support !=)

    # Email status filters
    if $UNREAD_ONLY; then
        # Implicitly filter to emails
        if [[ -z "$CONTENT_TYPE" ]]; then
            parts+=('kMDItemContentType == "com.apple.mail.email"')
        fi
        parts+=("com_apple_mail_read == 0")
    fi
    if $FLAGGED_ONLY; then
        if [[ -z "$CONTENT_TYPE" ]]; then
            parts+=('kMDItemContentType == "com.apple.mail.email"')
        fi
        parts+=("com_apple_mail_flagged == 1")
    fi
    if $HAS_ATTACHMENTS; then
        parts+=('com_apple_mail_attachmentNames != ""')
    fi

    # Free text search combined with structured filters
    if [[ -n "$SEARCH_QUERY" && ${#parts[@]} -gt 0 ]]; then
        parts+=("kMDItemTextContent == '*${SEARCH_QUERY}*'cd")
    fi

    # Join with &&
    local result=""
    for i in "${!parts[@]}"; do
        if [[ $i -eq 0 ]]; then
            result="${parts[$i]}"
        else
            result="$result && ${parts[$i]}"
        fi
    done

    echo "$result"
}

# Format an email result using mdls metadata
format_email() {
    local file="$1"
    local idx="$2"

    mdls \
        -name kMDItemSubject \
        -name kMDItemAuthors \
        -name kMDItemAuthorEmailAddresses \
        -name kMDItemRecipientEmailAddresses \
        -name com_apple_mail_dateReceived \
        -name com_apple_mail_read \
        -name com_apple_mail_flagged \
        -name com_apple_mail_messageID \
        -name com_apple_mail_attachmentNames \
        "$file" 2>/dev/null | awk -v idx="$idx" '
    BEGIN { in_array = 0; array_key = "" }

    # Start of array value
    /= \(/ {
        array_key = $1
        in_array = 1
        next
    }
    # End of array
    /^\)/ { in_array = 0; next }

    # Array element - take first value only
    in_array && /"/ {
        val = $0
        gsub(/^[[:space:]]*"/, "", val)
        gsub(/"[[:space:]]*,?$/, "", val)
        if (array_key == "kMDItemAuthors" && author_name == "") author_name = val
        if (array_key == "kMDItemAuthorEmailAddresses" && from_email == "") from_email = val
        if (array_key == "kMDItemRecipientEmailAddresses" && to_email == "") to_email = val
        if (array_key == "com_apple_mail_attachmentNames") {
            if (attachments == "") attachments = val
            else attachments = attachments ", " val
        }
        next
    }

    # Scalar values
    /^kMDItemSubject/ {
        sub(/^[^=]+= /, "")
        gsub(/^"/, ""); gsub(/"$/, "")
        subject = $0
    }
    /^com_apple_mail_dateReceived/ {
        sub(/^[^=]+= /, "")
        date_received = $0
    }
    /^com_apple_mail_read/ {
        sub(/^[^=]+= /, "")
        read_status = $0 + 0
    }
    /^com_apple_mail_flagged/ {
        sub(/^[^=]+= /, "")
        flagged = $0 + 0
    }
    /^com_apple_mail_messageID/ {
        sub(/^[^=]+= /, "")
        gsub(/^"/, ""); gsub(/"$/, "")
        message_id = $0
    }

    END {
        has_email_metadata = 0
        if (subject != "" && subject != "(null)") has_email_metadata = 1
        if (from_email != "") has_email_metadata = 1
        if (message_id != "" && message_id != "(null)") has_email_metadata = 1

        if (has_email_metadata) {
            if (subject == "" || subject == "(null)") subject = "(no subject)"

            status = ""
            if (read_status == 0) status = "UNREAD"
            if (flagged == 1) {
                if (status != "") status = status ", "
                status = status "FLAGGED"
            }

            from = ""
            if (author_name != "" && from_email != "") from = author_name " <" from_email ">"
            else if (from_email != "") from = from_email
            else if (author_name != "") from = author_name

            printf "--- Email %d ---\n", idx
            printf "Subject: %s\n", subject
            if (from != "") printf "From: %s\n", from
            if (to_email != "") printf "To: %s\n", to_email
            if (date_received != "" && date_received != "(null)") printf "Date: %s\n", date_received
            if (status != "") printf "Status: %s\n", status
            if (message_id != "" && message_id != "(null)") printf "Message-ID: %s\n", message_id
            if (attachments != "") printf "Attachments: %s\n", attachments
        } else {
            # Fallback: show as file (no email metadata available)
            printf "--- Email file %d ---\n", idx
            printf "(No email metadata — may need Full Disk Access)\n"
        }
        printf "\n"
    }
    '
}

# Format a file result using mdls metadata
format_file() {
    local file="$1"
    local idx="$2"

    mdls \
        -name kMDItemDisplayName \
        -name kMDItemContentType \
        -name kMDItemFSSize \
        -name kMDItemContentModificationDate \
        -name kMDItemLastUsedDate \
        "$file" 2>/dev/null | awk -v idx="$idx" -v path="$file" '
    /^kMDItemDisplayName/ {
        sub(/^[^=]+= /, "")
        gsub(/^"/, ""); gsub(/"$/, "")
        name = $0
    }
    /^kMDItemContentType[[:space:]]/ {
        sub(/^[^=]+= /, "")
        gsub(/^"/, ""); gsub(/"$/, "")
        content_type = $0
    }
    /^kMDItemFSSize/ {
        sub(/^[^=]+= /, "")
        size = $0 + 0
    }
    /^kMDItemContentModificationDate/ {
        sub(/^[^=]+= /, "")
        date_mod = $0
    }
    /^kMDItemLastUsedDate/ {
        sub(/^[^=]+= /, "")
        last_used = $0
    }

    END {
        if (name == "" || name == "(null)") {
            n = split(path, parts, "/")
            name = parts[n]
        }

        size_str = ""
        if (size > 1048576) size_str = sprintf("%.1f MB", size / 1048576)
        else if (size > 1024) size_str = sprintf("%.1f KB", size / 1024)
        else if (size > 0) size_str = size " bytes"

        printf "--- File %d ---\n", idx
        printf "Name: %s\n", name
        printf "Path: %s\n", path
        if (content_type != "" && content_type != "(null)") printf "Type: %s\n", content_type
        if (size_str != "") printf "Size: %s\n", size_str
        if (date_mod != "" && date_mod != "(null)") printf "Modified: %s\n", date_mod
        if (last_used != "" && last_used != "(null)") printf "Last opened: %s\n", last_used
        printf "\n"
    }
    '
}

# ---- Main execution ----

QUERY_STR=$(build_query)

# Build mdfind arguments
MDFIND_ARGS=()
if [[ -n "$SEARCH_DIR" ]]; then
    MDFIND_ARGS+=("-onlyin" "$SEARCH_DIR")
fi

# If we have a structured query, use it; otherwise use free text search
if [[ -n "$QUERY_STR" ]]; then
    MDFIND_ARGS+=("$QUERY_STR")
elif [[ -n "$SEARCH_QUERY" ]]; then
    MDFIND_ARGS+=("$SEARCH_QUERY")
else
    error_exit "No search query could be built"
fi

# Get results and display count
if ! $EXCLUDE_APPS; then
    TOTAL=$(mdfind -count "${MDFIND_ARGS[@]}" 2>/dev/null)
    echo "Found $TOTAL results (showing up to $LIMIT)"
    echo ""
    if [[ "$TOTAL" -eq 0 ]]; then
        echo "No results found."
        exit 0
    fi
fi

# Collect results (limited), optionally filtering out apps
RESULTS=()
if $EXCLUDE_APPS; then
    while IFS= read -r rLine; do
        RESULTS+=("$rLine")
    done < <(mdfind "${MDFIND_ARGS[@]}" 2>/dev/null | grep -v -E '\.(app|prefPane|appex|pluginkit)(/|$)' | head -n "$LIMIT")
    echo "Found ${#RESULTS[@]} files (excluding apps, showing up to $LIMIT)"
    echo ""
else
    while IFS= read -r rLine; do
        RESULTS+=("$rLine")
    done < <(mdfind "${MDFIND_ARGS[@]}" 2>/dev/null | head -n "$LIMIT")
fi

# Determine if results are emails based on type or parameters used
IS_EMAIL=false
if [[ "$CONTENT_TYPE" == "email" || "$CONTENT_TYPE" == "mail" ]]; then
    IS_EMAIL=true
elif [[ -n "$EMAIL_FROM" || -n "$EMAIL_TO" || -n "$EMAIL_SUBJECT" || \
        "$UNREAD_ONLY" == true || "$FLAGGED_ONLY" == true ]]; then
    IS_EMAIL=true
fi

# Format each result
for i in "${!RESULTS[@]}"; do
    if $IS_EMAIL; then
        format_email "${RESULTS[$i]}" "$((i + 1))"
    else
        format_file "${RESULTS[$i]}" "$((i + 1))"
    fi
done
