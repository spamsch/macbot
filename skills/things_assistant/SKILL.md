---
id: things_assistant
name: Things3 Assistant
description: Manage to-dos, projects, and tags in Things3 with natural language.
apps:
  - Things3
tasks:
  - show_things_today
  - show_things_inbox
  - list_things_todos
  - search_things_todos
  - create_things_todo
  - complete_things_todo
  - update_things_todo
  - move_things_todo
  - list_things_projects
  - create_things_project
  - list_things_tags
essential_tasks:
  - show_things_today
  - create_things_todo
  - complete_things_todo
examples:
  - "Show my Things today list"
  - "What's in my Things inbox?"
  - "Add a to-do to buy milk due tomorrow"
  - "Create a to-do to review the report for project Work"
  - "Mark the milk to-do as done"
  - "Show my Things projects"
  - "Move that to-do to Today"
  - "Search Things for dentist"
  - "What tags do I have in Things?"
safe_defaults:
  status: open
  include_completed: false
confirm_before_write:
  - complete to-do
  - cancel to-do
  - delete to-do
requires_permissions:
  - Automation:Things3
---

## Behavior Notes

### Creating To-Dos
- Parse natural language dates for the `due` parameter ("tomorrow" → compute YYYY-MM-DD)
- Use `schedule` for when to show the to-do (today, evening, tomorrow, someday, anytime)
- Use `due` for the actual deadline date
- Tags are comma-separated: `--tags "work,urgent"`
- When the user says "add to Today", use `list_name="Today"` or `schedule="today"`
- When they mention a project, use the `project` parameter

### Scheduling vs Due Dates
- **Schedule** controls when the to-do appears in Things (visibility)
- **Due date** is the deadline
- "Do this today" → schedule to today
- "This is due Friday" → set due date to Friday
- "Remind me about this tomorrow" → schedule to tomorrow

### Status Values
- `open` — Active, not yet done
- `completed` — Done
- `canceled` — Canceled/removed

### Built-in Lists
- **Inbox** — Unprocessed items, brain dump
- **Today** — To-dos to focus on today
- **Upcoming** — Scheduled for future dates
- **Anytime** — Available to do anytime (no schedule)
- **Someday** — Ideas for later, not committed
- **Logbook** — Completed to-dos
- **Trash** — Deleted items

### Two-Step Lookup
When the user wants to act on a specific to-do (complete, update, move), first search or list to find the to-do's ID, then use the ID for the action. This avoids ambiguity with duplicate names.

### Common Request Patterns
- **"show my today list"** → show_things_today
- **"what's in my inbox?"** → show_things_inbox
- **"add a to-do..."** → create_things_todo with parsed name, due, tags, project
- **"mark X as done"** → search_things_todos to find it, then complete_things_todo with id
- **"show my projects"** → list_things_projects with with_todos=true
- **"move X to Today"** → move_things_todo with to_list="Today"
- **"what are my tags?"** → list_things_tags with with_counts=true
- **"show tasks for project X"** → list_things_todos with project="X"
- **"show tasks tagged X"** → list_things_todos with tag="X"
- **"update the due date"** → update_things_todo with set_due

### Notes on To-Dos
- Notes/descriptions can be added when creating a to-do with the `notes` parameter
- Notes can be updated on existing to-dos with `update_things_todo` using `set_notes`
- Notes support plain text (no rich text/HTML)
