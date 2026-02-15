---
id: mindwtr
name: Mindwtr GTD Assistant
description: Manage tasks, projects, and GTD workflows in the Mindwtr productivity app.
apps:
  - Mindwtr
tasks:
  - mindwtr_list_tasks
  - mindwtr_add_task
  - mindwtr_get_task
  - mindwtr_update_task
  - mindwtr_complete_task
  - mindwtr_archive_task
  - mindwtr_delete_task
  - mindwtr_list_projects
  - mindwtr_create_project
  - mindwtr_update_project
  - mindwtr_list_sections
  - mindwtr_create_section
  - mindwtr_update_section
  - mindwtr_delete_section
  - mindwtr_update_checklist
  - mindwtr_list_tags
  - mindwtr_search
essential_tasks: []
examples:
  - "Add a task to buy groceries tomorrow"
  - "Show me my next actions"
  - "What's in my inbox?"
  - "Mark the grocery task as done"
  - "Move that task to the waiting list"
  - "What tasks are due this week?"
  - "Search my tasks for anything about the dentist"
  - "Show me all my projects"
  - "Create a project called Home Renovation"
  - "What tags am I using?"
safe_defaults:
  include_completed: false
  include_deleted: false
  status: ""
confirm_before_write:
  - delete task
  - archive task
requires_permissions: []
requires_settings:
  - mindwtr_data_path
---

## Behavior Notes

### Quick-Add Syntax
Mindwtr supports a powerful quick-add format when creating tasks via the `input` parameter:
- **Contexts**: `@home`, `@work`, `@errands` — where/when to do the task
- **Tags**: `#shopping`, `#finance`, `#urgent` — categorization labels
- **Due dates**: `/due:tomorrow`, `/due:2026-03-01`, `/due:next monday`
- **Priority**: `/priority:high` (low, medium, high, urgent)
- **Project**: `+ProjectName` — assign to an existing project
- **Time**: `9am`, `2pm` — start time for the task

Example: `"Review invoice @work /due:tomorrow 2pm #finance +Accounting /priority:high"`

Always prefer using `input` with quick-add syntax over setting individual fields — it's more natural and supports all features in one string.

### Task Statuses (GTD Workflow)
- **inbox** — Newly captured, not yet processed
- **todo** — Processed, ready to be done (general bucket)
- **next** — Next actions, the tasks you should do now
- **in-progress** — Currently being worked on
- **waiting** — Delegated or waiting for someone/something
- **someday** — Deferred ideas, maybe later
- **done** — Completed
- **archived** — Old completed tasks, out of sight

### Common GTD Patterns

**Inbox Processing** ("What's in my inbox?"):
1. List inbox tasks: `mindwtr_list_tasks(status="inbox")`
2. For each task, help the user decide: actionable? → next/todo; delegated? → waiting; defer? → someday
3. Update status accordingly with `mindwtr_update_task`

**Daily Review** ("What should I work on today?"):
1. Show next actions: `mindwtr_list_tasks(status="next")`
2. Show in-progress: `mindwtr_list_tasks(status="in-progress")`
3. Check waiting items: `mindwtr_list_tasks(status="waiting")`

**Weekly Review** ("Let me review everything"):
1. Process inbox first
2. Review all projects: `mindwtr_list_projects`
3. Check someday/maybe: `mindwtr_list_tasks(status="someday")`
4. Review waiting items

### Completing Tasks
- Use `mindwtr_complete_task` to mark tasks as done — this handles recurring tasks automatically
- Don't manually set status to "done" via update; use the complete endpoint instead
- Recurring tasks automatically spawn the next occurrence when completed

### Searching
- Use `mindwtr_search` for broad queries across tasks and projects
- Use `mindwtr_list_tasks(query="...")` for filtered task-only searches
- Search supports @context and #tag syntax in queries
- Use `mindwtr_list_tasks(status="...")` when the user asks for a specific GTD list

### Sections
Sections group tasks within a project into logical phases (e.g., "Planning", "In Progress", "Review"):
1. List sections: `mindwtr_list_sections(project_id="...")`
2. Create: `mindwtr_create_section(project_id="...", title="Phase 1")`
3. Assign task to section: use `section_id` on `mindwtr_add_task` or `mindwtr_update_task`
4. Remove from section: `mindwtr_update_task(task_id="...", section_id="__clear__")`
5. Deleting a section automatically clears `sectionId` on its tasks

### Checklists
Tasks can have checklist items (subtasks). Use `mindwtr_update_checklist`:
- **Add items**: `action="add", items=["Step 1", "Step 2"]`
- **Toggle completion**: `action="toggle", item_id="..."`
- **Remove item**: `action="remove", item_id="..."`
- **Replace all**: `action="set", items=["New 1", "New 2"]`

### Two-Step Lookup
When the user refers to a task vaguely (e.g., "that grocery task"):
1. Search first: `mindwtr_search(query="grocery")` or `mindwtr_list_tasks(query="grocery")`
2. If multiple matches, show them and ask which one
3. Then act on the specific task by ID

### How It Works
Son of Simon reads and writes `~/Sync/mindwtr/data.json` directly (no server needed). The Mindwtr desktop app's file watcher monitors this sync folder and auto-refreshes the UI within ~750ms of any change.

To change the data file path, set `MACBOT_MINDWTR_DATA_PATH` in `~/.macbot/.env`.
