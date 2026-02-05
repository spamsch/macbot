#!/bin/bash
# Build the complete Son of Simon desktop app
#
# This script:
# 1. Builds the Python sidecar
# 2. Installs npm dependencies
# 3. Builds the Tauri app
#
# Output: app/src-tauri/target/release/bundle/

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/app"

echo "=========================================="
echo "Building Son of Simon Desktop App"
echo "=========================================="
echo ""

# Step 1: Build sidecar
echo "Step 1/3: Building Python sidecar..."
"$SCRIPT_DIR/build-sidecar.sh"
echo ""

# Step 2: Install npm dependencies
echo "Step 2/3: Installing npm dependencies..."
cd "$APP_DIR"
npm install
echo ""

# Step 3: Build Tauri app
echo "Step 3/3: Building Tauri app..."
npm run tauri build

echo ""
echo "=========================================="
echo "Build complete!"
echo "=========================================="
echo ""
echo "The app bundle is located at:"

# Find the built app
case "$(uname -s)" in
    Darwin)
        BUNDLE_DIR="$APP_DIR/src-tauri/target/release/bundle/macos"
        if [ -d "$BUNDLE_DIR" ]; then
            ls -la "$BUNDLE_DIR"
        fi
        echo ""
        echo "To create a DMG, run:"
        echo "  $SCRIPT_DIR/create-dmg.sh"
        ;;
    Linux)
        BUNDLE_DIR="$APP_DIR/src-tauri/target/release/bundle"
        ls -la "$BUNDLE_DIR"
        ;;
esac
