#!/bin/bash
# ==============================================================================
# run-shortcut.sh - Run a macOS Shortcut by name
# ==============================================================================
# Runs a shortcut from the Shortcuts app, optionally with file input.
# Captures output to a temp file and returns it.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

# Defaults
SHORTCUT_NAME=""
INPUT_FILE=""
TIMEOUT=60

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --name)
            SHORTCUT_NAME="$2"
            shift 2
            ;;
        --input)
            INPUT_FILE="$2"
            shift 2
            ;;
        *)
            error_exit "Unknown argument: $1"
            ;;
    esac
done

if [[ -z "$SHORTCUT_NAME" ]]; then
    error_exit "Missing required argument: --name <shortcut_name>"
fi

# Check that shortcuts CLI exists
if ! command -v shortcuts &>/dev/null; then
    error_exit "shortcuts command not found. Requires macOS 12 (Monterey) or later."
fi

# Build the command
args=(run "$SHORTCUT_NAME")

if [[ -n "$INPUT_FILE" ]]; then
    if [[ ! -f "$INPUT_FILE" ]]; then
        error_exit "Input file not found: $INPUT_FILE"
    fi
    args+=(-i "$INPUT_FILE")
fi

# Capture output to temp file
OUTPUT_FILE=$(mktemp /tmp/shortcut-output.XXXXXX)
trap "rm -f '$OUTPUT_FILE'" EXIT

args+=(-o "$OUTPUT_FILE")

# Run with timeout
if timeout "$TIMEOUT" shortcuts "${args[@]}" 2>&1; then
    if [[ -s "$OUTPUT_FILE" ]]; then
        echo "=== Shortcut Output ==="
        cat "$OUTPUT_FILE"
    else
        echo "Shortcut '$SHORTCUT_NAME' completed successfully (no output)."
    fi
else
    exit_code=$?
    if [[ $exit_code -eq 124 ]]; then
        error_exit "Shortcut timed out after ${TIMEOUT}s"
    else
        error_exit "Shortcut '$SHORTCUT_NAME' failed with exit code $exit_code"
    fi
fi
