---
id: notes_assistant
name: Notes Assistant
description: Search, read, create, and organize notes in Apple Notes.
apps:
  - Notes
tasks:
  - search_notes
  - read_note
  - create_note
  - list_notes
  - list_note_folders
  - create_note_folder
  - move_note
  - delete_note
  - rename_note_folder
  - delete_note_folder
essential_tasks:
  - search_notes
  - read_note
  - create_note
keywords: ["notiz", "notizen", "anmerkung"]
examples:
  - "Search my notes for the wifi password"
  - "Create a note about today's meeting"
  - "Read my Placeholder note"
  - "Show me my recent notes"
  - "Move the note to the Work folder"
  - "Create a todo list for the project"
safe_defaults:
  limit: 20
  folder: Notes
confirm_before_write:
  - delete note
  - delete folder
  - move note
requires_permissions:
  - Automation:Notes
---

## Behavior Notes

### Reading Notes
- Use `read_note` to get the full content of a specific note
- Do NOT use `read_file` with `note://` URIs — that does not work
- Default listings (`list_notes`) show titles only
- For long notes, summarize or show the beginning

### Searching Notes
- Search both title and content
- Return the most relevant matches first
- Show note title and a preview snippet
- Limit results to avoid overwhelming output

### Creating Notes with Todo Items
- Use `html=true` to create formatted notes with lists and structure
- **Todo/bullet lists:** use `<ul><li>Item</li></ul>` HTML format
- **Completed items:** wrap in `<strike>Done item</strike>`
- **Sections/headings:** use `<h2>Section</h2>`
- Example HTML body for a todo note:
  ```html
  <h1>Project Tasks</h1><ul><li>Review PR</li><li>Update docs</li><li><strike>Fix login bug</strike></li></ul>
  ```
- Without `html=true`, the body is treated as plain text (newlines become `<br>`)
- Apple Notes checklists (checkbox widgets) CANNOT be created via AppleScript — use `<ul><li>` bullet lists instead, which is the standard format used in existing todo notes

### Organization
- Notes go to the default "Notes" folder unless specified
- Don't create folders without asking
- If user mentions a folder that doesn't exist, ask first
- Smart Folders (shown with 🔍 in list_note_folders) cannot receive moved notes — they are virtual views based on filters

### Common Request Patterns
- **"read my X note"** → read_note with title
- **"search notes for..."** → search_notes with the query
- **"find notes about..."** → search_notes with show_preview=true
- **"create a note..."** → create_note with title and body
- **"create a todo list"** → create_note with html=true and `<ul><li>` items
- **"show my recent notes"** → list_notes with recent_days parameter
- **"move note X to folder Y"** → move_note with title and destination
