#!/bin/bash
# Release script for Son of Simon
#
# Usage:
#   ./scripts/release.sh patch                    # 0.1.0 -> 0.1.1
#   ./scripts/release.sh minor                    # 0.1.0 -> 0.2.0
#   ./scripts/release.sh major                    # 0.1.0 -> 1.0.0
#   ./scripts/release.sh 0.2.0                    # Set specific version
#   ./scripts/release.sh patch "Custom message"   # With custom commit message

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get current version from pyproject.toml
CURRENT_VERSION=$(grep -E '^version = "' pyproject.toml | sed 's/version = "\(.*\)"/\1/')

echo -e "${YELLOW}Current version: ${NC}$CURRENT_VERSION"

# Parse version components
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

# Determine new version
case "${1:-patch}" in
    major)
        NEW_VERSION="$((MAJOR + 1)).0.0"
        ;;
    minor)
        NEW_VERSION="$MAJOR.$((MINOR + 1)).0"
        ;;
    patch)
        NEW_VERSION="$MAJOR.$MINOR.$((PATCH + 1))"
        ;;
    *)
        # Assume it's a specific version
        if [[ $1 =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            NEW_VERSION="$1"
        else
            echo -e "${RED}Error: Invalid version '$1'${NC}"
            echo "Usage: $0 [major|minor|patch|X.Y.Z]"
            exit 1
        fi
        ;;
esac

echo -e "${GREEN}New version: ${NC}$NEW_VERSION"

# Custom commit message (optional second argument)
COMMIT_MSG="${2:-Release version $NEW_VERSION}"
echo -e "${YELLOW}Commit message: ${NC}$COMMIT_MSG"
echo ""

# Confirm
read -p "Continue with release v$NEW_VERSION? [y/N] " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "=========================================="
echo "Updating version numbers..."
echo "=========================================="

# Update pyproject.toml
sed -i '' "s/^version = \".*\"/version = \"$NEW_VERSION\"/" pyproject.toml
echo "  ✓ pyproject.toml"

# Update app/src-tauri/tauri.conf.json
sed -i '' "s/\"version\": \".*\"/\"version\": \"$NEW_VERSION\"/" app/src-tauri/tauri.conf.json
echo "  ✓ app/src-tauri/tauri.conf.json"

# Update app/package.json
sed -i '' "s/\"version\": \".*\"/\"version\": \"$NEW_VERSION\"/" app/package.json
echo "  ✓ app/package.json"

# Update Cargo.toml version
sed -i '' "s/^version = \".*\"/version = \"$NEW_VERSION\"/" app/src-tauri/Cargo.toml
echo "  ✓ app/src-tauri/Cargo.toml"

echo ""
echo "=========================================="
echo "Committing changes..."
echo "=========================================="

git add pyproject.toml app/src-tauri/tauri.conf.json app/package.json app/src-tauri/Cargo.toml
git commit --no-gpg-sign -m "$COMMIT_MSG"
echo "  ✓ Committed: $COMMIT_MSG"

echo ""
echo "=========================================="
echo "Creating and pushing tag..."
echo "=========================================="

git tag -a "v$NEW_VERSION" -m "Release v$NEW_VERSION"
echo "  ✓ Created tag v$NEW_VERSION"

git push origin HEAD
echo "  ✓ Pushed commits"

git push origin "v$NEW_VERSION"
echo "  ✓ Pushed tag v$NEW_VERSION"

echo ""
echo "=========================================="
echo -e "${GREEN}Release v$NEW_VERSION initiated!${NC}"
echo "=========================================="
echo ""
echo "GitHub Actions is now building the release."
echo "Check progress at:"
echo "  https://github.com/spamsch/son-of-simon/actions"
echo ""
echo "Once complete, the release will be available at:"
echo "  https://github.com/spamsch/son-of-simon/releases"
echo ""
