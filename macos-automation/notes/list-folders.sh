#!/bin/bash
# ==============================================================================
# list-folders.sh - List all folders in Notes.app
# ==============================================================================
# Description:
#   Lists all folders (and subfolders) in Notes.app with note counts.
#
# Usage:
#   ./list-folders.sh
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

osascript <<'EOF'
tell application "Notes"
    set output to "=== NOTES FOLDERS ===" & return & return
    set folderCount to 0

    repeat with f in folders
        if name of f is not "Recently Deleted" then
            set folderCount to folderCount + 1
            set nCount to count of notes of f
            set output to output & "📁 " & name of f & " (" & nCount & " notes)" & return
        end if
    end repeat

    set output to output & return & "Total: " & folderCount & " folder(s)"
    return output
end tell
EOF
