---
id: reminders_assistant
name: Reminders Assistant
description: Create and manage reminders with natural language time parsing.
apps:
  - Reminders
tasks:
  - create_reminder
  - list_reminders
  - complete_reminder
  - get_due_today_reminders
examples:
  - "Remind me to call mom at 5pm"
  - "Add a reminder to buy groceries tomorrow morning"
  - "Show my reminders for today"
  - "What reminders are overdue?"
  - "Mark the grocery reminder as done"
safe_defaults:
  list: Reminders
  include_completed: false
confirm_before_write:
  - delete reminder
requires_permissions:
  - Automation:Reminders
---

## Behavior Notes

### Creating Reminders
- Parse natural language times ("at 5pm", "tomorrow morning", "next Monday")
- Default to the main "Reminders" list unless specified
- Confirm the reminder before creating if time interpretation is ambiguous
- Include the full reminder text and scheduled time in confirmation

### Time Interpretation
- "morning" = 9:00 AM
- "afternoon" = 2:00 PM
- "evening" = 6:00 PM
- "tonight" = 8:00 PM
- "end of day" = 5:00 PM
- "next week" = same day next week, 9:00 AM

### Viewing Reminders
- Default to showing incomplete reminders only
- Show due date/time and list name
- Group by list if showing multiple reminders
- Highlight overdue reminders

### Lists
- Use the user's existing lists
- Don't create new lists without asking
- If a specified list doesn't exist, ask to create it or use default

### Common Request Patterns
- **"remind me to..."** → create_reminder with the title and parsed time
- **"show my reminders"** → list_reminders or get_due_today_reminders
- **"what's due today?"** → get_due_today_reminders with include_overdue=true
- **"mark X as done"** → complete_reminder with name or pattern matching
