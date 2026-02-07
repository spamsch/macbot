---
id: teams_assistant
name: Teams Assistant
description: Interact with Microsoft Teams — read chats, send messages, list channels and teams.
apps:
  - Microsoft Teams
tasks:
  - teams_setup
  - teams_login
  - teams_status
  - teams_list_teams
  - teams_list_channels
  - teams_read_channel_messages
  - teams_send_channel_message
  - teams_list_chats
  - teams_read_chat_messages
  - teams_send_chat_message
examples:
  - "Set up Teams integration"
  - "List my Teams"
  - "Show channels in the Engineering team"
  - "Read recent messages in the General channel"
  - "Send a message to the General channel saying the deploy is done"
  - "Show my recent Teams chats"
  - "Read my chat with Alice"
  - "Send Bob a Teams message asking about the deadline"
safe_defaults:
  limit: 20
confirm_before_write:
  - send message
requires_permissions: []
---

## Behavior Notes

### Setup Flow
- Setup requires the Azure CLI (`az`). If not installed, tell the user: `brew install azure-cli`
- `teams_setup` handles everything: az login, Azure AD app registration, and initial browser auth
- The user just needs to sign in via the browser windows that open — no manual Azure portal steps
- After setup, tokens are cached and refresh automatically
- If token expires, use `teams_login` to re-authenticate

### Account Selection
- If only one account is configured, it is used automatically — no need to pass `account_name`
- If multiple accounts exist and `account_name` is not specified, the task returns an error listing available accounts
- Use `teams_status` to check which accounts are set up and whether tokens are valid
- Default account name is "default" — suggest "work" or "personal" if the user has multiple tenants

### Reading Messages
1. Start with `teams_list_teams` to get team IDs
2. Use `teams_list_channels` with the team_id to get channel IDs
3. Use `teams_read_channel_messages` with both IDs to read messages
4. For direct chats, use `teams_list_chats` then `teams_read_chat_messages`

### Sending Messages
- Always confirm with the user before sending a message
- Show a preview of the message content and destination before sending
- Channel messages go to `teams_send_channel_message` (needs team_id + channel_id)
- Direct/group chat messages go to `teams_send_chat_message` (needs chat_id)

### Message Content
- Messages support plain text by default
- HTML content is supported by the Graph API but prefer plain text for simplicity
- Channel message content may contain HTML tags — present the text content to the user cleanly

### Common Request Patterns
- **"my Teams messages"** → list chats, show recent messages from top chats
- **"what's happening in [channel]"** → find the team/channel, read recent messages
- **"message [person] on Teams"** → find the 1:1 chat, send message
- **"Teams status"** → check configured accounts and token validity
