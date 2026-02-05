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
echo "Verifying Build"
echo "=========================================="

# Verify binaries are in place
case "$(uname -s)" in
    Darwin)
        APP_BUNDLE="$APP_DIR/src-tauri/target/release/bundle/macos/Son of Simon.app"
        MACOS_DIR="$APP_BUNDLE/Contents/MacOS"

        echo "Checking binaries in $MACOS_DIR..."

        # Check main executable
        if [ -f "$MACOS_DIR/son-of-simon" ]; then
            echo "  ✓ Main executable: son-of-simon ($(du -h "$MACOS_DIR/son-of-simon" | cut -f1))"
        else
            echo "  ✗ ERROR: Main executable not found!"
            exit 1
        fi

        # Check sidecar
        if [ -f "$MACOS_DIR/son" ]; then
            echo "  ✓ Sidecar binary: son ($(du -h "$MACOS_DIR/son" | cut -f1))"
        else
            echo "  ✗ ERROR: Sidecar binary 'son' not found!"
            echo "    Expected at: $MACOS_DIR/son"
            echo "    Run ./scripts/build-sidecar.sh first"
            exit 1
        fi

        # Verify sidecar is executable
        if [ -x "$MACOS_DIR/son" ]; then
            echo "  ✓ Sidecar is executable"
        else
            echo "  ✗ WARNING: Sidecar is not executable"
        fi

        BUNDLE_DIR="$APP_DIR/src-tauri/target/release/bundle/macos"
        ;;
    Linux)
        BUNDLE_DIR="$APP_DIR/src-tauri/target/release/bundle"
        echo "Linux build verification not implemented"
        ;;
esac

echo ""
echo "=========================================="
echo "Build complete!"
echo "=========================================="
echo ""
echo "The app bundle is located at:"
ls -la "$BUNDLE_DIR"
echo ""

case "$(uname -s)" in
    Darwin)
        echo "To create a DMG, run:"
        echo "  $SCRIPT_DIR/create-dmg.sh"
        ;;
esac
