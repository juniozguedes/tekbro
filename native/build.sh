#!/bin/sh
# Builds the native helpers into bin/:
#   tekbro-audio   macOS system-audio capture (ScreenCaptureKit)
#   tekbro-hotkey  global hotkeys (Carbon RegisterEventHotKey)
# The VFS overlay works around a duplicate SwiftBridging modulemap shipped with
# some Command Line Tools versions.
set -e
cd "$(dirname "$0")/.."
NATIVE="$PWD/native"
mkdir -p bin build
sed "s#NATIVE_DIR#$NATIVE#" native/vfs-overlay.template.yaml > build/vfs-overlay.yaml
: > build/empty.modulemap
for name in tekbro-audio tekbro-hotkey; do
  src="build/$(echo $name | tr - _).swift"
  cp "native/$name.swift" "$src"
  swiftc -O -parse-as-library \
    -vfsoverlay build/vfs-overlay.yaml -Xcc -ivfsoverlay -Xcc build/vfs-overlay.yaml \
    -module-cache-path build/mcache \
    -o "bin/$name" "$src"
  echo "built bin/$name"
done
