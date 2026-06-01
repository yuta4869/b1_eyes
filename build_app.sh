#!/usr/bin/env bash
# Build VLM Camera.app — a thin macOS bundle that launches gui.py with the project venv.
set -euo pipefail

cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
APP_NAME="VLM Camera"
APP_DIR="${PROJECT_DIR}/${APP_NAME}.app"
CONTENTS="${APP_DIR}/Contents"
MACOS_DIR="${CONTENTS}/MacOS"
RES_DIR="${CONTENTS}/Resources"

echo "[1/4] generate icon source PNG"
"${PROJECT_DIR}/.venv/bin/python" "${PROJECT_DIR}/make_icon.py"

echo "[2/4] build icon.icns from sources"
ICONSET="${PROJECT_DIR}/build/icon.iconset"
rm -rf "${ICONSET}"
mkdir -p "${ICONSET}"
SRC="${PROJECT_DIR}/build/icon_src.png"
for spec in \
  "16 icon_16x16" "32 icon_16x16@2x" \
  "32 icon_32x32" "64 icon_32x32@2x" \
  "128 icon_128x128" "256 icon_128x128@2x" \
  "256 icon_256x256" "512 icon_256x256@2x" \
  "512 icon_512x512" "1024 icon_512x512@2x"; do
  size="${spec%% *}"
  name="${spec##* }"
  sips -z "${size}" "${size}" "${SRC}" --out "${ICONSET}/${name}.png" >/dev/null
done
iconutil -c icns "${ICONSET}" -o "${PROJECT_DIR}/build/icon.icns"

echo "[3/4] assemble .app bundle"
rm -rf "${APP_DIR}"
mkdir -p "${MACOS_DIR}" "${RES_DIR}"
cp "${PROJECT_DIR}/build/icon.icns" "${RES_DIR}/icon.icns"

cat > "${CONTENTS}/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>VLM Camera</string>
  <key>CFBundleDisplayName</key><string>VLM Camera</string>
  <key>CFBundleIdentifier</key><string>com.local.vlmcamera</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleSignature</key><string>????</string>
  <key>CFBundleExecutable</key><string>VLMCamera</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSCameraUsageDescription</key><string>VLM Cameraがカメラ映像を物体認識・文字起こしに使用します。</string>
  <key>NSAppleEventsUsageDescription</key><string>VLM Camera</string>
</dict>
</plist>
PLIST

LAUNCHER="${MACOS_DIR}/VLMCamera"
cat > "${LAUNCHER}" <<LAUNCH
#!/bin/bash
# Launcher: cd into project dir and run gui.py with the bundled venv.
PROJECT_DIR="${PROJECT_DIR}"
cd "\${PROJECT_DIR}"
LOG="\${PROJECT_DIR}/build/launch.log"
mkdir -p "\${PROJECT_DIR}/build"
exec "\${PROJECT_DIR}/.venv/bin/python" "\${PROJECT_DIR}/gui.py" >> "\${LOG}" 2>&1
LAUNCH
chmod +x "${LAUNCHER}"

echo "[4/4] refresh Finder/Dock icon cache for this bundle"
touch "${APP_DIR}"
# 'open -R' would highlight the app in Finder; skip if running headless.

echo "DONE → ${APP_DIR}"
echo "Double-click to launch, or run: open \"${APP_DIR}\""
