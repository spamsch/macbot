---
id: mail_assistant
name: Mail Assistant
description: Find, summarize, and act on emails safely with sensible defaults. Supports sending emails with file attachments.
apps:
  - Mail
tasks:
  - search_emails
  - send_email
  - move_email
  - download_attachments
  - get_unread_emails
  - mark_emails_read
essential_tasks:
  - search_emails
  - get_unread_emails
  - send_email
examples:
  - "Summarize unread emails from today"
  - "Find emails from UPS and show tracking numbers"
  - "Show me emails from the waas.rent account"
  - "Archive all read newsletters"
  - "Download attachments from the last email from Bob"
  - "Reply to John's email about the meeting"
  - "Send a draft to Frank with the invoice PDF attached"
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
Email metadata search (headers, sender, subject, date) is fast (~50ms via SQLite index).
**The two-phase approach remains important for reading email content:**

1. **Phase 1 — Find (headers only):** Search with filters, `with_content=false` (default).
   Returns in milliseconds via SQLite. Falls back to AppleScript if needed.
2. **Phase 2 — Read (by message_id):** Fetch content with `message_id` + `with_content=true`.
   Takes ~3-5s per email (AppleScript required for email body). Add `with_links=true` only when the user needs URLs from HTML emails (adds ~5s extra).

**Bad:** `search_emails(subject="Ferien", days=30, with_content=True)` → slow (30s+, fetches all bodies)
**Good:** `search_emails(subject="Ferien", sender="mom", days=7, limit=5)` → fast headers → then `search_emails(message_id="<id>", with_content=True)` → ~3-5s

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

### Critical: Never Iterate Over Accounts
- `search_emails` WITHOUT an `account` parameter already searches ALL accounts' Inbox + Archive in a single call
- NEVER loop through individual accounts one by one — this is wasteful and slow
- For "today's emails": `search_emails(today_only=true, limit=20)` — one call, all accounts
- For "unread emails": `get_unread_emails` — one call, all accounts
- Only use the `account` parameter when the user specifically asks about ONE account

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

### Sending Emails with Attachments
When the user wants to send an email with file attachments:
1. Find the file using `spotlight_search` or use the absolute path provided by the user
2. Call `send_email` with `attachments=["/absolute/path/to/file"]` — paths must be absolute
3. Multiple files: pass multiple paths in the list, e.g. `attachments=["/path/a.pdf", "/path/b.pdf"]`
4. Always use `draft=True` or `draft_visible=True` when attachments are involved so the user can review before sending

### Downloading Attachments
When the user wants to download email attachments:
1. Use search_emails to find the email and get its Message-ID
2. Use download_attachments with the message_id and output folder path
3. Attachments will be saved with their original filenames (duplicates auto-renamed)
