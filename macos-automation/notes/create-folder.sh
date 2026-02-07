#!/bin/bash
# ==============================================================================
# create-folder.sh - Create a new folder in Notes.app
# ==============================================================================
# Usage:
#   ./create-folder.sh --name "Work"
#   ./create-folder.sh --name "Sub" --parent "Work"
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

NAME=""
PARENT=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --name) NAME="$2"; shift 2 ;;
        --parent) PARENT="$2"; shift 2 ;;
        *) error_exit "Unknown option: $1" ;;
    esac
done

[[ -z "$NAME" ]] && error_exit "--name is required"

NAME_ESCAPED=$(escape_for_applescript "$NAME")
PARENT_ESCAPED=$(escape_for_applescript "$PARENT")

osascript <<EOF
tell application "Notes"
    if "$PARENT_ESCAPED" is not "" then
        try
            set parentFolder to folder "$PARENT_ESCAPED"
            make new folder at parentFolder with properties {name:"$NAME_ESCAPED"}
            return "Created folder '$NAME_ESCAPED' inside '$PARENT_ESCAPED'"
        on error
            return "Error: Parent folder '$PARENT_ESCAPED' not found."
        end try
    else
        make new folder with properties {name:"$NAME_ESCAPED"}
        return "Created folder '$NAME_ESCAPED'"
    end if
end tell
EOF
