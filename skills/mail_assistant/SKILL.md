---
id: mail_assistant
name: Mail Assistant
description: Find, summarize, and act on emails safely with sensible defaults.
apps:
  - Mail
tasks:
  - search_emails
  - send_email
  - move_email
  - download_attachments
  - get_unread_emails
  - mark_emails_read
examples:
  - "Summarize unread emails from today"
  - "Find emails from UPS and show tracking numbers"
  - "Show me emails from the waas.rent account"
  - "Archive all read newsletters"
  - "Download attachments from the last email from Bob"
  - "Reply to John's email about the meeting"
safe_defaults:
  days: 7
  limit: 20
  with_content: false
confirm_before_write:
  - send email
  - delete email
  - move to trash
requires_permissions:
  - Automation:Mail
---

## Behavior Notes

### Performance: Two-Phase Search Pattern
Email search can be slow (10-30s) because Mail.app processes messages one by one.
**Always use a two-phase approach to minimize search time:**

1. **Phase 1 — Find (headers only):** Search with the most specific filters possible, `with_content=false` (default), small `limit` (5), and narrow `days` (7 unless user says otherwise). Combine `sender` AND `subject` in a single call when both are known.
2. **Phase 2 — Read (by message_id):** Once you find the right email, fetch its content with `message_id` + `with_content=true`. Message-ID lookup is near-instant (<1s).

**Bad:** `search_emails(subject="Ferien", days=30, with_content=True)` → slow (30s+, fetches all bodies)
**Good:** `search_emails(subject="Ferien", sender="mom", days=7, limit=5)` → fast headers → then `search_emails(message_id="<id>", with_content=True)` → instant

### Search Optimization Rules
- **Combine filters:** Use both `sender` + `subject` in one call instead of two separate searches
- **Narrow date range:** Use `days=7` by default, only widen if nothing found
- **Small limit:** Use `limit=5` for targeted searches (default 20 is too many for exploration)
- **Specify account:** If the user context implies which account, use the `account` parameter to halve search time
- **Never use `with_content=true` on broad searches** — it adds seconds per result

### Search Strategy
- Start with the most specific search first (sender + subject + narrow days)
- Only expand search (wider days, remove filters) if initial query returns nothing
- Use `today_only=true` for "today's emails" requests
- Use the `account` parameter when user says "from X account" (not sender)

### Email Actions
- Always confirm before sending, deleting, or moving emails
- Show a preview of what will be sent/changed before confirming
- For bulk operations, show count and ask for confirmation

### Reading Email Content
- **Never use `with_content=true` on the initial search** — search headers first, then read by message_id
- For tracking numbers or specific content, use the two-phase pattern above

### Handling Multiple Accounts
- "emails from X account" means emails RECEIVED BY that account (any sender)
- "emails from X sender" means emails FROM that person/address
- Always clarify if the user mentions an account name vs sender name

### Common Request Patterns
- **"today's emails"** → use today_only=true parameter
- **"recent emails"** → use days parameter (e.g., days=7 for last week)
- **"all emails" or "read and unread"** → the search includes both by default
- **"read this email"** → search_emails with message_id AND with_content=True
- **"archive this email"** → move_email with to="archive" and message_id
- **"delete this email"** → move_email with to="trash" and message_id

### Moving and Archiving Emails
When processing emails and the user wants them archived or deleted:
1. Use search_emails to find the email and get its Message-ID
2. Use move_email with the message_id and to="archive" or to="trash"
3. The email will be moved to the account's Archive/Trash mailbox

### Downloading Attachments
When the user wants to download email attachments:
1. Use search_emails to find the email and get its Message-ID
2. Use download_attachments with the message_id and output folder path
3. Attachments will be saved with their original filenames (duplicates auto-renamed)
