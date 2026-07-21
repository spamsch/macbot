# macOS Automation Scripts

A collection of shell scripts for automating Apple's native productivity apps (Mail, Calendar, Reminders, Notes, and Safari) via AppleScript.

## Prerequisites

- macOS 10.14 or later
- Bash shell
- For Safari JavaScript features: Enable "Allow JavaScript from Apple Events" in Safari's Develop menu

## Directory Structure

```
macos-automation/
├── privacy-bridge/        # "Letta Privacy Bridge.app" — owns the TCC grants (see its README)
├── lib/
│   └── common.sh          # Shared utilities and helper functions
├── mail/
│   ├── get-unread-summary.sh   # List unread emails
│   ├── search-emails.sh        # Search by sender/subject
│   ├── send-email.sh           # Send emails
│   └── mark-as-read.sh         # Bulk mark as read
├── calendar/
│   ├── get-today-events.sh     # Today's schedule
│   ├── get-week-events.sh      # Weekly agenda
│   ├── create-event.sh         # Create new events
│   └── list-calendars.sh       # List all calendars
├── reminders/
│   ├── get-due-today.sh        # Today's tasks
│   ├── create-reminder.sh      # Create new reminders
│   ├── complete-reminder.sh    # Mark tasks complete
│   └── list-reminders.sh       # List with filters
├── notes/
│   ├── create-note.sh          # Create notes
│   ├── search-notes.sh         # Search note content
│   ├── list-notes.sh           # List notes
│   └── export-note.sh          # Export to files
└── safari/
    ├── get-current-page.sh     # Current tab info
    ├── open-url.sh             # Open URLs
    ├── extract-links.sh        # Extract page links
    └── list-tabs.sh            # List open tabs
```

## Permissions: Letta Privacy Bridge

The scripts here run under whatever process launches them, so macOS records their
privacy grants against Terminal, iTerm, or the agent host — an identity that is
both too broad and too unstable. `privacy-bridge/` builds
`~/Applications/Letta Privacy Bridge.app`, a signed helper with a fixed bundle ID
(`ai.letta.privacybridge`) and real usage descriptions that owns those grants
instead.

```bash
bash privacy-bridge/build-install.sh
"$HOME/Applications/Letta Privacy Bridge.app/Contents/MacOS/letta-privacy-bridge" status
"$HOME/Applications/Letta Privacy Bridge.app/Contents/MacOS/letta-privacy-bridge" request all
```

It handles Calendar and Reminders access end to end (EventKit full access), the
Apple Events grant for Notes.app and Mail.app, and it detects Full Disk Access —
which macOS never lets an app request; that one is always a manual grant. See
[privacy-bridge/README.md](privacy-bridge/README.md).

---

## Quick Start

1. Make scripts executable:
   ```bash
   chmod +x macos-automation/**/*.sh
   ```

2. Run any script with `--help` for usage:
   ```bash
   ./mail/get-unread-summary.sh --help
   ```

---

## Mail Scripts

### get-unread-summary.sh
Get a summary of all unread emails in inbox.

```bash
# List all unread emails
./mail/get-unread-summary.sh

# Just get the count
./mail/get-unread-summary.sh --count-only
```

### search-emails.sh
Search emails by sender or subject.

```bash
# Search by sender
./mail/search-emails.sh --sender "john@example.com"

# Search by subject
./mail/search-emails.sh --subject "Invoice"

# Combine filters with limit
./mail/search-emails.sh --sender "amazon" --subject "order" --limit 5
```

### send-email.sh
Send emails via Mail.app.

```bash
# Send a simple email
./mail/send-email.sh --to "john@example.com" --subject "Hello" --body "Hi John!"

# Create draft for review
./mail/send-email.sh --to "team@example.com" --subject "Update" --body "..." --draft

# With CC and body from file
./mail/send-email.sh --to "boss@example.com" --subject "Report" \
    --body-file report.txt --cc "manager@example.com"
```

### mark-as-read.sh
Bulk mark emails as read.

```bash
# Mark all unread as read
./mail/mark-as-read.sh --all

# Mark newsletters as read
./mail/mark-as-read.sh --sender "newsletter@"

# Preview without marking
./mail/mark-as-read.sh --older-than 30 --dry-run
```

---

## Calendar Scripts

### get-today-events.sh
Get today's schedule.

```bash
# All calendars
./calendar/get-today-events.sh

# Specific calendar
./calendar/get-today-events.sh --calendar "Work"
```

### get-week-events.sh
Get upcoming events.

```bash
# Next 7 days
./calendar/get-week-events.sh

# Next 14 days from Work calendar
./calendar/get-week-events.sh --days 14 --calendar "Work"
```

### create-event.sh
Create new calendar events.

```bash
# Timed event
./calendar/create-event.sh --calendar "Work" --title "Meeting" \
    --start "2026-01-30 14:00" --end "2026-01-30 15:00"

# With duration instead of end time
./calendar/create-event.sh --calendar "Work" --title "Standup" \
    --start "2026-02-03 09:00" --duration 15

# All-day event
./calendar/create-event.sh --calendar "Personal" --title "Birthday" \
    --date "2026-03-15" --all-day

# With location and notes
./calendar/create-event.sh --calendar "Work" --title "Review" \
    --start "2026-01-31 10:00" --duration 60 \
    --location "Room 101" --notes "Bring laptop"
```

### list-calendars.sh
List available calendars.

```bash
# Simple list
./calendar/list-calendars.sh

# With event counts
./calendar/list-calendars.sh --with-counts
```

---

## Reminders Scripts

### get-due-today.sh
Get reminders due today.

```bash
# Today's reminders
./reminders/get-due-today.sh

# Include overdue
./reminders/get-due-today.sh --include-overdue

# Specific list
./reminders/get-due-today.sh --list "Work Tasks"
```

### create-reminder.sh
Create new reminders.

```bash
# Simple reminder
./reminders/create-reminder.sh --title "Call dentist"

# With due date and priority
./reminders/create-reminder.sh --title "Submit report" \
    --due "2026-01-31 17:00" --priority high --flag

# In specific list with notes
./reminders/create-reminder.sh --list "Work Tasks" \
    --title "Review document" --notes "Check section 3" \
    --due "2026-02-01"
```

### complete-reminder.sh
Mark reminders complete.

```bash
# By exact name
./reminders/complete-reminder.sh --name "Call dentist"

# By pattern
./reminders/complete-reminder.sh --pattern "meeting"

# Preview mode
./reminders/complete-reminder.sh --pattern "old" --dry-run
```

### list-reminders.sh
List reminders with filters.

```bash
# All incomplete
./reminders/list-reminders.sh

# Flagged and high priority
./reminders/list-reminders.sh --flagged --high-priority

# Overdue
./reminders/list-reminders.sh --overdue

# Completed items
./reminders/list-reminders.sh --completed --limit 10
```

---

## Notes Scripts

### create-note.sh
Create new notes.

```bash
# Simple note
./notes/create-note.sh --title "Quick Note" --body "Remember this..."

# In specific folder
./notes/create-note.sh --folder "Work" --title "Meeting" --body "Action items..."

# From file
./notes/create-note.sh --title "Document" --body-file document.txt

# HTML formatted
./notes/create-note.sh --title "Formatted" \
    --body "<h1>Title</h1><p>Content</p>" --html
```

### search-notes.sh
Search notes by content.

```bash
# Search all notes
./notes/search-notes.sh --query "project"

# In specific folder
./notes/search-notes.sh --query "budget" --folder "Finance"

# Title only (faster)
./notes/search-notes.sh --query "Report" --title-only

# With preview
./notes/search-notes.sh --query "meeting" --show-preview
```

### list-notes.sh
List notes with various options.

```bash
# All notes grouped by folder
./notes/list-notes.sh --show-folders

# From specific folder
./notes/list-notes.sh --folder "Work"

# Recently modified
./notes/list-notes.sh --recent 7

# With attachments
./notes/list-notes.sh --with-attachments
```

### export-note.sh
Export notes to files.

```bash
# Single note to text
./notes/export-note.sh --name "Meeting Notes" --output meeting.txt

# Single note to HTML
./notes/export-note.sh --name "Formatted Note" --output note.html --format html

# Export entire folder
./notes/export-note.sh --folder "Work" --output-dir ./work-notes
```

---

## Safari Scripts

### get-current-page.sh
Get current tab information.

```bash
# Basic info
./safari/get-current-page.sh

# With page text
./safari/get-current-page.sh --with-text

# JSON output
./safari/get-current-page.sh --json
```

### open-url.sh
Open URLs in Safari.

```bash
# Open in new tab
./safari/open-url.sh "https://example.com"

# Open in new window
./safari/open-url.sh "https://example.com" --new-window

# Wait and get title
./safari/open-url.sh "https://news.ycombinator.com" --wait --get-title

# In background
./safari/open-url.sh "https://example.com" --background
```

### extract-links.sh
Extract links from current page.

```bash
# All links
./safari/extract-links.sh

# Filter by domain
./safari/extract-links.sh --domain "github.com"

# External links only
./safari/extract-links.sh --external --limit 20

# With link text
./safari/extract-links.sh --with-text
```

### list-tabs.sh
List all open Safari tabs.

```bash
# Full listing
./safari/list-tabs.sh

# URLs only (for piping)
./safari/list-tabs.sh --urls-only

# JSON format
./safari/list-tabs.sh --json

# Specific window
./safari/list-tabs.sh --window 1
```

---

## Combining Scripts

These scripts can be combined for powerful automation:

```bash
# Morning briefing
echo "=== MORNING BRIEFING ==="
./mail/get-unread-summary.sh --count-only
./calendar/get-today-events.sh
./reminders/get-due-today.sh --include-overdue

# Create meeting notes with reminder
./notes/create-note.sh --folder "Work" --title "Meeting $(date +%Y-%m-%d)" \
    --body "Attendees:\n\nAgenda:\n\nAction Items:"
./reminders/create-reminder.sh --title "Review meeting notes" \
    --due "$(date -v+1d +%Y-%m-%d)" --list "Work Tasks"

# Research and save
./safari/open-url.sh "https://example.com/article" --wait
PAGE_CONTENT=$(./safari/get-current-page.sh --with-text)
./notes/create-note.sh --title "Research: Article" --body "$PAGE_CONTENT"
```

---

## Performance: Notes vs Reminders for Todos

Reminders.app has significant AppleScript performance issues — each Apple Event incurs ~2 seconds of overhead, and bulk property fetches often fail with error -1728. Listing or searching reminders across multiple lists can take 10-30 seconds.

**For todo/task tracking, prefer Notes.app over Reminders.app.** Notes is much faster via AppleScript and supports structured lists, checklists, and rich text. Use a dedicated "Todos" note or folder in Notes instead of Reminders lists.

Use Reminders only when you specifically need its features (due dates, recurring reminders, location-based alerts, Siri integration).

---

## Troubleshooting

### "application isn't running" errors
The scripts will work even if apps aren't running; macOS will launch them as needed.

### Safari JavaScript errors
Enable "Allow JavaScript from Apple Events":
1. Safari → Settings → Advanced → "Show Develop menu"
2. Develop → "Allow JavaScript from Apple Events"

### Permission errors
Grant Terminal/iTerm automation permissions:
System Settings → Privacy & Security → Automation

---

## License

These scripts are provided as-is for personal and educational use.
