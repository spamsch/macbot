#!/bin/bash
# ==============================================================================
# build-install.sh - Build and install "Letta Privacy Bridge.app"
# ==============================================================================
# Description:
#   Compiles the bridge from source with swiftc (no Xcode project, no GUI),
#   assembles a proper .app bundle, signs it (Developer ID when available,
#   ad-hoc otherwise), and installs it to ~/Applications.
#
#   The build is deterministic: same sources in, same bundle layout out.
#   A source snapshot is copied next to the app support directory so the app
#   can always be rebuilt even if this repository is gone.
#
# Usage:
#   ./build-install.sh                      # build, sign, install to ~/Applications
#   ./build-install.sh --no-install         # build into ./build only
#   ./build-install.sh --dest /Applications # install elsewhere
#   ./build-install.sh --identity "Developer ID Application: ..."
#   ./build-install.sh --request            # install, then trigger permission dialogs
#
# Options:
#   --dest <dir>       Install directory (default: ~/Applications)
#   --identity <id>    Code signing identity (default: auto-detect, else ad-hoc)
#   --no-install       Build only; leave the bundle in ./build
#   --no-snapshot      Skip copying the source snapshot
#   --request          After install, run `request all` to show permission dialogs
#   -h, --help         Show this help
#
# Output:
#   Progress on stderr, one JSON summary object on stdout.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Letta Privacy Bridge"
BUNDLE_ID="ai.letta.privacybridge"
EXECUTABLE="letta-privacy-bridge"
VERSION="1.0.0"
DEPLOYMENT_TARGET="14.0"

DEST_DIR="$HOME/Applications"
IDENTITY=""
DO_INSTALL=true
DO_SNAPSHOT=true
DO_REQUEST=false
SNAPSHOT_DIR="$HOME/Library/Application Support/LettaPrivacyBridge/src"

log() { printf '[build-install] %s\n' "$*" >&2; }
die() {
    printf '{\n  "ok": false,\n  "command": "build-install",\n  "error": {\n    "code": "%s",\n    "message": "%s"\n  }\n}\n' "$1" "$2"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dest) DEST_DIR="$2"; shift 2 ;;
        --identity) IDENTITY="$2"; shift 2 ;;
        --no-install) DO_INSTALL=false; shift ;;
        --no-snapshot) DO_SNAPSHOT=false; shift ;;
        --request) DO_REQUEST=true; shift ;;
        -h|--help) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 0 ;;
        *) die "unknown_option" "Unknown option: $1" ;;
    esac
done

command -v swiftc >/dev/null 2>&1 || die "swiftc_missing" \
    "swiftc not found. Install the Xcode Command Line Tools with: xcode-select --install"
command -v codesign >/dev/null 2>&1 || die "codesign_missing" "codesign not found"

BUILD_DIR="$SCRIPT_DIR/build"
APP_BUNDLE="$BUILD_DIR/$APP_NAME.app"
CONTENTS="$APP_BUNDLE/Contents"

log "cleaning $BUILD_DIR"
rm -rf "$BUILD_DIR"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"

ARCH="$(uname -m)"
TARGET="${ARCH}-apple-macos${DEPLOYMENT_TARGET}"

# main.swift must come last: top-level code lives there.
SOURCES=()
while IFS= read -r file; do
    [[ "$(basename "$file")" == "main.swift" ]] || SOURCES+=("$file")
done < <(find "$SCRIPT_DIR/Sources" -name '*.swift' | sort)
SOURCES+=("$SCRIPT_DIR/Sources/main.swift")

[[ ${#SOURCES[@]} -gt 1 ]] || die "no_sources" "No Swift sources found in $SCRIPT_DIR/Sources"

log "compiling ${#SOURCES[@]} source files for $TARGET"
swiftc \
    -swift-version 5 \
    -target "$TARGET" \
    -O \
    -framework EventKit \
    -framework Foundation \
    -framework CoreServices \
    -o "$CONTENTS/MacOS/$EXECUTABLE" \
    "${SOURCES[@]}" >&2 || die "compile_failed" "swiftc failed; see stderr above"

log "writing Info.plist (version $VERSION)"
sed "s/__VERSION__/$VERSION/g" "$SCRIPT_DIR/Resources/Info.plist" > "$CONTENTS/Info.plist"
printf 'APPL????' > "$CONTENTS/PkgInfo"

# Fail loudly if a privacy string went missing: without them macOS terminates the
# process instead of prompting.
for key in NSCalendarsFullAccessUsageDescription NSRemindersFullAccessUsageDescription NSAppleEventsUsageDescription; do
    /usr/libexec/PlistBuddy -c "Print :$key" "$CONTENTS/Info.plist" >/dev/null 2>&1 \
        || die "missing_usage_description" "Info.plist is missing $key"
done
/usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$CONTENTS/Info.plist" | grep -qx "$BUNDLE_ID" \
    || die "bundle_id_mismatch" "Info.plist bundle id does not match $BUNDLE_ID"

# ---- signing -----------------------------------------------------------------
SIGN_MODE="adhoc"
if [[ -z "$IDENTITY" ]]; then
    IDENTITY="${LETTA_BRIDGE_SIGN_IDENTITY:-}"
fi
if [[ -z "$IDENTITY" ]]; then
    IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null \
        | grep 'Developer ID Application' | head -1 | sed -E 's/.*"(.*)"/\1/')" || true
fi

if [[ -n "$IDENTITY" ]]; then
    SIGN_MODE="developer-id"
    log "signing with Developer ID: $IDENTITY (hardened runtime)"
    codesign --force --deep --timestamp --options runtime \
        --entitlements "$SCRIPT_DIR/Resources/hardened.entitlements" \
        --sign "$IDENTITY" "$APP_BUNDLE" >&2 \
        || die "codesign_failed" "Developer ID signing failed"
else
    log "no Developer ID found; signing ad-hoc"
    # Ad-hoc, no hardened runtime: entitlements are neither required nor honored.
    codesign --force --deep --sign - "$APP_BUNDLE" >&2 \
        || die "codesign_failed" "Ad-hoc signing failed"
fi

codesign --verify --strict "$APP_BUNDLE" >&2 || die "codesign_verify_failed" "Signature verification failed"

# ---- smoke test --------------------------------------------------------------
log "smoke-testing the built binary"
"$CONTENTS/MacOS/$EXECUTABLE" version >/dev/null || die "smoke_test_failed" "\`version\` did not return successfully"

# ---- install -----------------------------------------------------------------
INSTALLED_PATH=""
if [[ "$DO_INSTALL" == true ]]; then
    mkdir -p "$DEST_DIR"
    INSTALLED_PATH="$DEST_DIR/$APP_NAME.app"
    if [[ -e "$INSTALLED_PATH" ]]; then
        log "replacing existing $INSTALLED_PATH"
        rm -rf "$INSTALLED_PATH"
    fi
    ditto "$APP_BUNDLE" "$INSTALLED_PATH" || die "install_failed" "ditto failed"
    # Register with LaunchServices so `open -a` and the Privacy panes find it.
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
        -f "$INSTALLED_PATH" >/dev/null 2>&1 || true
    log "installed to $INSTALLED_PATH"
fi

# ---- source snapshot ---------------------------------------------------------
if [[ "$DO_SNAPSHOT" == true ]]; then
    rm -rf "$SNAPSHOT_DIR"
    mkdir -p "$SNAPSHOT_DIR"
    ditto "$SCRIPT_DIR/Sources" "$SNAPSHOT_DIR/Sources"
    ditto "$SCRIPT_DIR/Resources" "$SNAPSHOT_DIR/Resources"
    cp "$SCRIPT_DIR/build-install.sh" "$SNAPSHOT_DIR/build-install.sh"
    [[ -f "$SCRIPT_DIR/README.md" ]] && cp "$SCRIPT_DIR/README.md" "$SNAPSHOT_DIR/README.md"
    chmod +x "$SNAPSHOT_DIR/build-install.sh"
    log "source snapshot refreshed at $SNAPSHOT_DIR"
fi

BIN_PATH="${INSTALLED_PATH:-$APP_BUNDLE}/Contents/MacOS/$EXECUTABLE"

if [[ "$DO_REQUEST" == true ]]; then
    log "triggering permission dialogs — answer them on screen"
    "$BIN_PATH" request all >&2 || true
fi

cat <<JSON
{
  "ok": true,
  "command": "build-install",
  "app_name": "$APP_NAME",
  "bundle_id": "$BUNDLE_ID",
  "version": "$VERSION",
  "arch": "$ARCH",
  "deployment_target": "$DEPLOYMENT_TARGET",
  "signing": "$SIGN_MODE",
  "built_bundle": "$APP_BUNDLE",
  "installed_path": "${INSTALLED_PATH:-null}",
  "binary": "$BIN_PATH",
  "source_snapshot": "$([[ "$DO_SNAPSHOT" == true ]] && printf '%s' "$SNAPSHOT_DIR" || printf 'null')",
  "next_steps": [
    "$BIN_PATH status",
    "$BIN_PATH request all"
  ]
}
JSON
