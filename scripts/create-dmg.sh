#!/bin/bash
# Create a DMG installer for Son of Simon
#
# Requires: create-dmg (brew install create-dmg)
#
# Output: Son-of-Simon-{version}.dmg

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/app"
BUNDLE_DIR="$APP_DIR/src-tauri/target/release/bundle/macos"

# Check for macOS
if [ "$(uname -s)" != "Darwin" ]; then
    echo "This script only runs on macOS"
    exit 1
fi

# Check for create-dmg
if ! command -v create-dmg &> /dev/null; then
    echo "create-dmg not found. Install it with:"
    echo "  brew install create-dmg"
    exit 1
fi

# Find the app
APP_PATH="$BUNDLE_DIR/Son of Simon.app"
if [ ! -d "$APP_PATH" ]; then
    echo "App not found at: $APP_PATH"
    echo "Run scripts/build-app.sh first"
    exit 1
fi

# Get version from tauri.conf.json
VERSION=$(grep -o '"version": "[^"]*"' "$APP_DIR/src-tauri/tauri.conf.json" | head -1 | cut -d'"' -f4)
DMG_NAME="Son-of-Simon-$VERSION.dmg"

echo "Creating DMG: $DMG_NAME"

# Create DMG
cd "$PROJECT_ROOT"
rm -f "$DMG_NAME"

create-dmg \
    --volname "Son of Simon" \
    --volicon "$APP_DIR/src-tauri/icons/icon.icns" \
    --window-pos 200 120 \
    --window-size 600 400 \
    --icon-size 100 \
    --icon "Son of Simon.app" 150 190 \
    --hide-extension "Son of Simon.app" \
    --app-drop-link 450 185 \
    --no-internet-enable \
    "$DMG_NAME" \
    "$APP_PATH"

echo ""
echo "DMG created: $PROJECT_ROOT/$DMG_NAME"
echo "Size: $(du -h "$DMG_NAME" | cut -f1)"
