---
id: mail_assistant
name: Mail Assistant
description: Find and act on emails over IMAP with Mail.app closed. Discover which accounts are logged in, search, read contents, download attachments, mark read/unread, archive, and move to trash.
apps: []
tasks:
  - mail_imap_accounts
  - mail_imap_search
  - mail_imap_read
  - mail_imap_download_attachments
  - mail_imap_mark_read
  - mail_imap_move_to_trash
  - mail_imap_archive
  - mail_imap_login
essential_tasks:
  - mail_imap_accounts
  - mail_imap_search
keywords: ["e-mail", "e-mails", "mail", "mails", "posteingang", "postfach", "nachricht", "konto", "account", "imap", "unread", "ungelesen"]
examples:
  - "Which mail accounts am I logged into?"
  - "Show unread emails in my operayo account"
  - "Find emails from UPS in the last week"
  - "Mark the newsletter from Microsoft as read"
  - "Move that Eventbrite email to trash"
  - "Archive the shipping confirmation from UPS"
  - "Read the latest invoice email and summarize it"
  - "Download the attachments from the email from my accountant"
safe_defaults:
  limit: 25
  since_days: 7
confirm_before_write:
  - move to trash
  - archive
requires_permissions: []
---

## Behavior Notes

Mail runs **headless with Mail.app closed** — no AppleScript, no EWS. Each Microsoft
account uses one of two transports, chosen at login and stored per account:
**imap** (IMAP+XOAUTH2) where the tenant allows it, or **graph** (Microsoft Graph)
where the tenant disables IMAP. The agent doesn't choose the transport — it's set
once at login and is transparent afterwards. Only accounts that are *logged in* can
be acted on. The legacy Mail.app tasks (search_emails, send_email, …) are disabled.

### Always start with account discovery
For anything mail-related, call `mail_imap_accounts` first. It returns, per account:
`email`, `provider`, `configured`, `logged_in`, `supported`. The `logged_in` list
is the set of accounts you can operate on right now.

- "Which accounts am I logged into?" → call `mail_imap_accounts`, report the
  `logged_in` list. Do not shell out or guess from macOS files — this task is the
  source of truth.
- If the account the user wants is `supported` but not `logged_in`, it needs a
  one-time login (see below). If it's not `supported`, say so (only Microsoft/
  Exchange works headless today; Gmail/iCloud aren't wired up yet).

### Login is a human step — do not call it autonomously
Logging in runs an interactive device-code flow that **blocks** on the user opening
a URL and entering a code. Never call `mail_imap_login` inside an autonomous run —
it would hang. Instead, tell the user to run the dedicated CLI command in a real
terminal (NOT via `son run`, which is itself an autonomous run and will loop):

```
son mail login <email>
```

For example: `son mail login simon@pamies.de`. They complete the browser prompt,
then you re-run `mail_imap_accounts` to confirm `logged_in` and continue.
`son mail accounts` lists accounts and login state without the agent.

### Searching
Use `mail_imap_search`. If exactly one account is configured, `email` is optional;
otherwise pass the target `email`. Returns headers + flags including the **`uid`**,
which you need for mark-read and trash.

Useful parameters: `mailbox` (default INBOX), `unread_only`, `since_days`,
`sender`, `subject`, `limit`. Combine filters in one call.

Escalation ladder when a search returns nothing — change one dimension at a time:
1. Start specific: `sender` + `subject` + narrow `since_days` (e.g. 7).
2. Vary the keyword: alternative spellings, partial names, the domain.
3. Switch the field: try `subject` instead of `sender`, or vice versa.
4. Widen time: `since_days` 7 → 30 → 90 → 365.
5. Broaden scope: try another `mailbox` (Archive, Sent, Junk) via `list`-known names.

### Reading contents and attachments
`mail_imap_search` returns only headers + flags, never the body. To read an email,
take its `uid` and call `mail_imap_read(uid=..., email=...)` — it returns the body
as plain text (HTML is stripped) plus an attachment list (name, type, size) without
downloading anything. Body is capped at `max_chars` (default 20000); `truncated`
is true when it was cut — raise `max_chars` if you need the rest.

To save attachments, call `mail_imap_download_attachments(uid=..., email=...)`. They
land in `~/Downloads` by default (override with `save_dir`); names are sanitized and
de-duplicated, so nothing is overwritten. Only download when the user asks for the
files — to merely describe what's attached, `mail_imap_read` is enough.

### Actions are by uid, and confirm before trashing
- Mark read/unread: `mail_imap_mark_read(uid=..., email=..., read=true|false)`.
- Move to trash: `mail_imap_move_to_trash(uid=..., email=...)` — lands in the
  account's Deleted Items, recoverable, but still **confirm with the user first**
  and show what will be moved (sender + subject).
- Archive: `mail_imap_archive(uid=..., email=...)` — moves it out of the inbox into
  the account's archive (Outlook/iCloud `Archive`, Gmail `[Gmail]/All Mail`, i.e.
  drop the inbox label). Use for processed mail worth keeping; trash is for
  discarding. Confirm before archiving too (sender + subject).
- For bulk actions, search first, show the count and a short preview, get one
  confirmation, then act on each uid.

### Multiple accounts
- "emails from X account" = received by that account → pass `email`.
- "emails from X sender" = from that person → pass `sender`.
- Clarify if it's ambiguous. Never loop blindly over every account; act on the
  specific logged-in account the user means.
