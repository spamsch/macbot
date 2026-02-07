---
id: whatsapp_assistant
name: WhatsApp Assistant
description: Read, search, and send WhatsApp messages using whatsapp-cli.
apps:
  - WhatsApp
tasks:
  - run_shell_command
examples:
  - "Show my recent WhatsApp chats"
  - "Read messages from Mom"
  - "Send a WhatsApp to +1234567890 saying I'm on my way"
  - "Search WhatsApp messages for flight confirmation"
  - "Find the contact for John"
safe_defaults:
  limit: 20
confirm_before_write:
  - send message
requires_permissions: []
---

## Behavior Notes

### CRITICAL: Every command MUST use `-store ~/.macbot/whatsapp`

The `-store` flag is MANDATORY on every `whatsapp-cli` invocation and **MUST come immediately after `whatsapp-cli`, before any subcommand**. Without it the CLI uses a different default location and will find no session, no contacts, and no messages.

**Copy-paste these exact templates — do NOT remove or reorder `-store ~/.macbot/whatsapp`:**

```
# Sync (MUST use timeout — sync never exits on its own)
timeout 10 whatsapp-cli -store ~/.macbot/whatsapp sync

# List chats
whatsapp-cli -store ~/.macbot/whatsapp chats list

# List chats filtered
whatsapp-cli -store ~/.macbot/whatsapp chats list --query "NAME"

# List messages from a chat
whatsapp-cli -store ~/.macbot/whatsapp messages list --chat JID --limit 30

# List recent messages across all chats
whatsapp-cli -store ~/.macbot/whatsapp messages list --limit 20

# Search messages
whatsapp-cli -store ~/.macbot/whatsapp messages search --query "TERM"

# Search contacts
whatsapp-cli -store ~/.macbot/whatsapp contacts search --query "NAME"

# Send message
whatsapp-cli -store ~/.macbot/whatsapp send --to JID --message "TEXT"

# Auth (first-time setup)
whatsapp-cli -store ~/.macbot/whatsapp auth
```

### Tool
All commands use `run_shell_command` to invoke `whatsapp-cli`.

### Authentication
- First-time setup: `whatsapp-cli -store ~/.macbot/whatsapp auth`
- This displays a QR code the user must scan with WhatsApp on their phone
- Session persists ~20 days before re-authentication is needed
- If any command fails with an auth error, tell the user to run auth again

### Syncing Messages
- Sync runs **forever** until killed — it never exits on its own.
- **ALWAYS use the unix `timeout` command:** `timeout 10 whatsapp-cli -store ~/.macbot/whatsapp sync`
- Do NOT rely on the run_shell_command timeout parameter — you MUST prepend `timeout 10` to the command string itself.
- **Always sync before querying** when the user asks for "latest", "new", "recent", or "unread" messages
- If message queries return empty results, run sync and retry

### Be Proactive
- When the user asks about a contact (e.g. "messages from Frank"), search contacts AND chats in parallel to find the JID faster
- When summarising messages, add your own interpretation of what the conversation means and suggest possible follow-up actions the user might want to take
- If a message references something actionable (meeting, deadline, document), proactively suggest creating a reminder or calendar event

### Listing Chats
- Pagination: `--limit 20 --page 0`
- Results are sorted by most recent activity
- Each chat includes a JID (WhatsApp identifier) needed for other commands

### Reading Messages
- Pagination: `--limit 20 --page 0`
- Messages are sorted newest-first

### Searching Messages
- Search is case-insensitive with partial matching
- Pagination: `--limit 20 --page 0`

### Sending Messages
- Individual JIDs look like: `1234567890@s.whatsapp.net`
- Group JIDs look like: `123456789-987654321@g.us`
- Always confirm message content with the user before sending

### JID Format
- **Individual**: phone number without `+` followed by `@s.whatsapp.net` (e.g. `1234567890@s.whatsapp.net`)
- **Group**: group ID followed by `@g.us`
- To send to a phone number, construct the JID: strip `+` and spaces, append `@s.whatsapp.net`

### Common Request Patterns
- **"my recent chats"** → `chats list` to show conversations
- **"messages from X"** → `chats list --query "X"` to find the JID, then `messages list --chat <JID>`
- **"send X a message"** → `contacts search --query "X"` to find JID, confirm message, then `send`
- **"search for X"** → `messages search --query "X"`
- **"unread messages"** → `messages list --limit 20` (most recent messages across chats)

### Output Format
- All whatsapp-cli commands return JSON
- Parse the JSON output to present results in a readable format to the user
- Show sender name, timestamp, and message content when displaying messages
