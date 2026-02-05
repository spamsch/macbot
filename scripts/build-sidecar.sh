#!/bin/bash
# Build the Python CLI as a sidecar binary for Tauri
#
# This script:
# 1. Builds the son CLI using PyInstaller
# 2. Copies the binary to the Tauri sidecar location
# 3. Names it according to Tauri's sidecar naming convention

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_DIR="$PROJECT_ROOT/app"
SIDECAR_DIR="$APP_DIR/src-tauri/binaries"

# Determine target triple
case "$(uname -s)" in
    Darwin)
        case "$(uname -m)" in
            arm64) TARGET="aarch64-apple-darwin" ;;
            x86_64) TARGET="x86_64-apple-darwin" ;;
            *) echo "Unsupported architecture: $(uname -m)"; exit 1 ;;
        esac
        ;;
    Linux)
        case "$(uname -m)" in
            aarch64) TARGET="aarch64-unknown-linux-gnu" ;;
            x86_64) TARGET="x86_64-unknown-linux-gnu" ;;
            *) echo "Unsupported architecture: $(uname -m)"; exit 1 ;;
        esac
        ;;
    *)
        echo "Unsupported OS: $(uname -s)"
        exit 1
        ;;
esac

echo "Building sidecar for target: $TARGET"

# Ensure PyInstaller is installed
if ! command -v pyinstaller &> /dev/null; then
    echo "Installing PyInstaller..."
    pip install pyinstaller
fi

# Build with PyInstaller
echo "Building with PyInstaller..."
cd "$PROJECT_ROOT"
pyinstaller --clean --noconfirm son.spec

# Create sidecar directory if it doesn't exist
mkdir -p "$SIDECAR_DIR"

# Copy binary with target triple name
BINARY_NAME="son-$TARGET"
echo "Copying binary to $SIDECAR_DIR/$BINARY_NAME"
cp "$PROJECT_ROOT/dist/son" "$SIDECAR_DIR/$BINARY_NAME"

# Make it executable
chmod +x "$SIDECAR_DIR/$BINARY_NAME"

echo ""
echo "Sidecar built successfully!"
echo "  Binary: $SIDECAR_DIR/$BINARY_NAME"
echo "  Size: $(du -h "$SIDECAR_DIR/$BINARY_NAME" | cut -f1)"
echo ""
echo "To build the Tauri app, run:"
echo "  cd $APP_DIR && npm run tauri build"
