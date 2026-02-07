---
id: spotlight_search
name: Spotlight Search
description: Fast indexed search for files and documents on disk using macOS Spotlight (mdfind).
apps:
  - Spotlight
  - Finder
tasks:
  - spotlight_search
examples:
  - "What files did I work on today?"
  - "Which documents did I open this week?"
  - "Find PDFs containing budget"
  - "Search for files named meeting notes"
  - "Find documents modified in the last 3 days"
  - "Find spreadsheets about revenue"
safe_defaults:
  limit: 20
  days: 30
confirm_before_write: []
requires_permissions: []
---

## Behavior Notes

### What This Tool Does

`spotlight_search` uses macOS Spotlight (mdfind) to search the system's pre-built file index. Searches are extremely fast (milliseconds) because they query an existing index rather than scanning files.

### Recently Used Files

Use `recently_used=True` to find files the user actually opened/worked on. This uses macOS's `kMDItemLastUsedDate` tracking, which records when files were opened by any application.

- **"what did I work on today"** -> `spotlight_search(recently_used=True, exclude_apps=True, days=1)`
- **"files I opened this week"** -> `spotlight_search(recently_used=True, exclude_apps=True, days=7)`
- **"recent PDFs"** -> `spotlight_search(recently_used=True, content_type="pdf", days=7)`

Always use `exclude_apps=True` with `recently_used` unless the user specifically asks about applications. Without it, results are cluttered with system apps.

### Important: Does NOT Search Mail.app

Mail.app uses Core Spotlight, a separate private index that is NOT accessible via `mdfind`. To search emails in Mail.app, always use `search_emails` (AppleScript-based). This tool can find `.eml` files stored on disk (e.g., in OneDrive, Downloads), but not messages in Mail.app mailboxes.

### File and Document Search

Search by:
- `file_name` — file name pattern (partial match, case-insensitive)
- `query` — full-text content search across file contents
- `body` — alias for content text search
- `content_type` — filter by file type
- `days` — limit to recently modified files (or recently opened when `recently_used=True`)
- `directory` — restrict search to a specific directory

### Content Types

| Type           | What it matches                           |
|----------------|-------------------------------------------|
| `pdf`          | PDF documents                             |
| `image`        | All image formats (PNG, JPG, HEIC, etc.)  |
| `document`     | Text documents, Word, Pages, etc.         |
| `presentation` | Keynote, PowerPoint                       |
| `spreadsheet`  | Numbers, Excel                            |
| `email`        | .eml files on disk (NOT Mail.app inbox)   |

### Common Patterns

- **"what did I work on"** -> `spotlight_search(recently_used=True, exclude_apps=True, days=1)`
- **"files I opened this week"** -> `spotlight_search(recently_used=True, exclude_apps=True, days=7)`
- **"find PDF named X"** -> `spotlight_search(file_name="X", content_type="pdf")`
- **"documents modified today"** -> `spotlight_search(content_type="document", days=1)`
- **"search files for X in Downloads"** -> `spotlight_search(query="X", directory="~/Downloads")`
- **"search all spreadsheets for budget"** -> `spotlight_search(query="budget", content_type="spreadsheet")`
- **"find recent presentations"** -> `spotlight_search(recently_used=True, content_type="presentation", days=14)`

### Output Format

**For files:** Shows Name, Path, Type, Size, Modified date, and Last opened date (when available).
