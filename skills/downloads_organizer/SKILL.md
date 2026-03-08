---
id: downloads_organizer
name: Downloads Organizer
description: Organize the ~/Downloads folder by categorizing files and subdirectories into subfolders using AI-driven analysis.
apps:
  - Finder
tasks:
  - list_directory
  - run_shell_command
  - spotlight_search
essential_tasks: []
keywords: ["downloads", "sortieren", "aufräumen", "ordner"]
examples:
  - "Organize my Downloads folder"
  - "Clean up Downloads"
  - "Sort my downloads by type"
  - "What's in my Downloads folder?"
  - "Help me tidy up Downloads"
  - "Organize the subdirectories in my Downloads"
safe_defaults:
  limit: 50
  directory: "~/Downloads"
confirm_before_write:
  - move files
  - create folders
requires_permissions: []
---

## Behavior Notes

### Four-Phase Workflow: Survey, Propose, Execute, Organize Subdirectories

Always follow this four-phase approach when organizing Downloads.

### Phase 1: Survey

1. Start with `list_directory(summary=True)` to get an overview of the folder.
2. Present the summary to the user (file counts by type, by age, existing subfolders).
3. If the folder is empty, say "Your Downloads folder is already clean!" and stop.
4. If the folder has fewer than 10 files, skip to Phase 3 (list them all and propose moves directly).

### Phase 2: Propose

Based on the summary, propose folder categories. Only suggest folders for types that are actually present:

- `Images/` — screenshots, photos, graphics (png, jpg, heic, gif, svg, webp)
- `Documents/` — PDFs, Word docs, text files (pdf, doc, docx, txt, rtf, pages, md)
- `Spreadsheets/` — Excel, Numbers, CSV (xls, xlsx, numbers, csv)
- `Archives/` — ZIP, tar, compressed files (zip, gz, tar, rar, 7z)
- `Installers/` — disk images and packages (dmg, pkg, mpkg, iso) — mention these might be safe to delete after install
- `Videos/` — video files (mp4, mov, avi, mkv)
- `Audio/` — music, recordings (mp3, wav, aac, m4a)
- `Code/` — scripts, source code (py, js, ts, html, json, sh)
- `Other/` — everything that doesn't fit above

**Important rules:**
- Do NOT create empty folders — only propose categories that have matching files.
- Respect existing subfolders — never reorganize or move files already in subfolders.
- If only one category has files, suggest a single folder (not the full taxonomy).
- Ask the user to approve or modify the proposed structure before creating anything.

### Phase 3: Execute (batch by batch)

1. Create approved folders: `run_shell_command(command="mkdir -p ~/Downloads/Category")`
2. Process files type-by-type using `list_directory(filter_type="images", limit=50)` to get the list.
3. Move files with `run_shell_command(command="mv ~/Downloads/file.png ~/Downloads/Images/")`.
4. **Handle name conflicts safely:** Before moving, check if the target exists. If so, append a number suffix (e.g., `report (2).pdf`). Use this pattern:
   ```
   dest="~/Downloads/Documents/report.pdf"
   if [ -f "$dest" ]; then
     base="${dest%.*}" ext="${dest##*.}"
     n=2; while [ -f "${base} (${n}).${ext}" ]; do n=$((n+1)); done
     dest="${base} (${n}).${ext}"
   fi
   mv "source" "$dest"
   ```
5. Report progress after each batch: "Moved 23 images to Images/"
6. If the directory has more files than the limit, paginate with offset to process the next batch.
7. Report a final summary when done: total files moved, folders created.

### Phase 4: Organize Subdirectories

After files are organized, handle leftover subdirectories sitting at the top level of ~/Downloads.

1. Run `list_directory(dirs_only=True, summary=True)` to check if there are uncategorized subdirectories.
2. If there are none (or very few), skip this phase.
3. Run `list_directory(dirs_only=True, limit=50)` to get subdirectory details (name, size, item count, contents breakdown).
4. Use the folder name and `Contents:` line to guess the best category for each:
   - Folder with mostly images (png, jpg, heic, gif) → `Images/`
   - Folder with .dmg, .app, or .pkg inside → `Installers/`
   - Folder with .py, .js, .ts, .go, .rs, .java → `Code/`
   - Folder with .pdf, .doc, .docx, .txt → `Documents/`
   - Folder with .xls, .xlsx, .csv → `Spreadsheets/`
   - Folder with .mp4, .mov, .mkv → `Videos/`
   - Folder with .mp3, .wav, .m4a → `Audio/`
   - Folder with .zip, .tar, .gz inside (nested archives) → `Archives/`
   - .app bundles (folders ending in .app) → `Installers/`
   - Anything ambiguous or mixed → `Other/`
5. Present the proposed moves to the user in a clear table before executing:
   ```
   Proposed subdirectory moves:
   - Frank_Case_Anhänge (8 files: pdf, jpg, docx) → Documents/
   - vacation_photos (42 files: jpg, png) → Images/
   - my-python-project (15 files: py, json, md) → Code/
   - random_stuff (mixed contents) → Other/
   ```
6. Wait for user approval before moving anything.
7. Move with `run_shell_command(command="mv ~/Downloads/folder ~/Downloads/Category/")`.
8. Handle name conflicts: if `~/Downloads/Category/folder` already exists, append a number suffix to the folder name.
9. If there are more than 50 subdirectories, paginate with offset to process the next batch.

### Safety Rules

- **Never move files out of ~/Downloads** — only into subfolders within ~/Downloads.
- **Never delete any files** — only move them.
- **Always confirm** the proposed folder structure before creating anything.
- **Skip locked files** — if a move fails, report it and continue with the next file.
- **Handle collisions** — never overwrite existing files (use number suffix).

### Edge Cases

- **Empty folder:** "Your Downloads folder is already clean!" — no action needed.
- **Already organized (subfolders exist with few loose files):** Only scan top-level files, note existing structure.
- **Single dominant type:** If 80%+ of files are one type, suggest just that one folder instead of the full taxonomy.
- **Very old installers (DMG/PKG):** After organizing, mention that old installers in `Installers/` might be safe to delete if the apps are already installed — but never delete them automatically.
- **Large folders (100+ files):** Process in batches of 50 using pagination. Report progress between batches.
