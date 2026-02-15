---
id: powerpoint
name: PowerPoint Reader
description: Analyze PowerPoint (.pptx) presentations by converting them to PDF via Keynote and reading the slides visually.
apps:
  - Keynote
tasks:
  - run_shell_command
  - read_file
  - spotlight_search
essential_tasks: []
examples:
  - "Summarize this PowerPoint presentation"
  - "What are the key points in slides.pptx?"
  - "Read the presentation on my Desktop and list the action items"
  - "Compare these two PowerPoint decks"
  - "Find the latest presentation I worked on and summarize it"
safe_defaults: {}
confirm_before_write: []
requires_permissions:
  - Keynote (Automation)
---

## Behavior Notes

### How It Works

macOS cannot read `.pptx` files as text — they are binary archives. To analyze a PowerPoint presentation, convert it to PDF using Keynote (pre-installed on macOS), then read the PDF visually. This preserves full layout, diagrams, charts, and screenshots.

### Step 1: Find the File

If the user doesn't provide a path, use `spotlight_search` to locate it:

```
spotlight_search(file_name="presentation", content_type="presentation")
```

### Step 2: Convert PPTX to PDF via Keynote

Use `run_shell_command` with this AppleScript. Replace the input/output paths:

```
osascript -e '
set inputFile to POSIX file "/path/to/presentation.pptx"
set outputFile to POSIX file "/tmp/presentation.pdf"
tell application "Keynote"
    open inputFile
    delay 5
    set theDoc to front document
    export theDoc to outputFile as PDF with properties {PDF image quality:Best}
    close theDoc saving no
end tell
'
```

- The `delay 5` gives Keynote time to render the file. Increase to `delay 10` for very large presentations.
- Keynote opens briefly during conversion — this is expected.
- Always write the PDF to `/tmp/` to avoid cluttering the user's filesystem.
- Use a unique filename if processing multiple files (e.g., `/tmp/deck_sales_q4.pdf`).

### Step 3: Read the PDF

Use `read_file` to read the converted PDF:

```
read_file(file_path="/tmp/presentation.pdf")
```

- Maximum 20 pages can be read at once.
- For larger decks, read in batches using the `offset` parameter and tell the user which slides you're covering.

### Important Rules

- **Never skip the conversion step.** Reading a `.pptx` directly with `read_file` will produce garbage — always convert to PDF first.
- **Clean up after yourself.** Delete the temporary PDF from `/tmp/` when done: `run_shell_command(command="rm /tmp/presentation.pdf")`.
- **Keynote opens .pptx natively.** No plugins or extra software needed.
- **Paths with spaces must be quoted.** The AppleScript `POSIX file` handles this, but ensure the path string itself is correct.
- **If Keynote fails**, it may be because the file is corrupted or uses unsupported features. Tell the user and suggest opening it manually.

### Export as Individual Slide Images (Alternative)

For very image-heavy decks or when you need per-slide analysis:

```
osascript -e '
set inputFile to POSIX file "/path/to/presentation.pptx"
set outputFolder to POSIX file "/tmp/slides"
tell application "Keynote"
    open inputFile
    delay 5
    set theDoc to front document
    export theDoc to outputFolder as slide images with properties {image format:PNG, skipped slides:false}
    close theDoc saving no
end tell
'
```

This creates `slide001.png`, `slide002.png`, etc. in `/tmp/slides/`. Read individual images with `read_file`.

### Common Patterns

- **"Summarize this deck"** -> Convert to PDF, read all pages, provide summary with key points per slide.
- **"What's on slide 5?"** -> Convert to PDF, read with offset to target that page.
- **"Find my latest presentation"** -> `spotlight_search(recently_used=True, content_type="presentation", days=7)`, then convert and read.
- **"Compare two decks"** -> Convert both to PDF, read both, provide comparison.
