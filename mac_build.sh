#!/bin/bash
# =============================================================================
# Build macOS DMG for Math Modeling Assistant
#
# Usage:  ./mac_build.sh
# Output: dist/MathModelingAssistant-1.0.0.dmg
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

APP_NAME="MathModelingAssistant"
VERSION="1.0.0"
DMG_NAME="${APP_NAME}-${VERSION}"
BUILD_DIR="$PROJECT_DIR/build"
DIST_DIR="$PROJECT_DIR/dist"
DMG_DIR="$DIST_DIR/dmg"
APP_PATH="$DIST_DIR/${APP_NAME}.app"
DMG_PATH="$DIST_DIR/${DMG_NAME}.dmg"

echo "=== Math Modeling Assistant — macOS DMG Builder ==="
echo ""

# Step 1: Clean previous builds
echo "[1/4] Cleaning previous builds..."
rm -rf "$BUILD_DIR" "$DIST_DIR/$APP_NAME" "$DMG_DIR" 2>/dev/null || true
mkdir -p "$DIST_DIR"

# Step 2: Build .app with PyInstaller
echo "[2/4] Building .app bundle with PyInstaller..."
pyinstaller \
    --clean \
    --noconfirm \
    --distpath "$DIST_DIR" \
    --workpath "$BUILD_DIR" \
    mac_build.spec \
    2>&1 | tail -20

if [ ! -d "$APP_PATH" ]; then
    echo "ERROR: .app build failed — $APP_PATH not found"
    exit 1
fi
echo "  ✓ $APP_PATH created"

# Step 3: Prepare DMG staging directory
echo "[3/4] Preparing DMG layout..."
mkdir -p "$DMG_DIR"
cp -R "$APP_PATH" "$DMG_DIR/"
# Create a symlink to /Applications so user can drag-to-install
ln -s /Applications "$DMG_DIR/Applications"
# Copy README if it exists
if [ -f "$PROJECT_DIR/README.md" ]; then
    cp "$PROJECT_DIR/README.md" "$DMG_DIR/README.md"
fi

# Step 4: Create DMG with hdiutil
echo "[4/4] Creating DMG..."
rm -f "$DMG_PATH"

# Calculate DMG size (app size + 20MB padding)
APP_SIZE_KB=$(du -sk "$DMG_DIR" | awk '{print $1}')
DMG_SIZE_KB=$((APP_SIZE_KB + 20000))

hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$DMG_DIR" \
    -ov \
    -format UDZO \
    -size "${DMG_SIZE_KB}k" \
    "$DMG_PATH" \
    2>&1

# Clean up staging
rm -rf "$DMG_DIR"

echo ""
echo "=== Done ==="
echo "DMG:  $DMG_PATH"
echo "Size: $(du -sh "$DMG_PATH" | awk '{print $1}')"
echo ""
echo "To test: open $(dirname "$DMG_PATH")"
