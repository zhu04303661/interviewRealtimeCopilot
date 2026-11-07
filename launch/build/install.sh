#!/bin/sh
# Install the built archive into launch/Final Round Recovered.app.
#
# Quits the running app, keeps the previous app.asar and Info.plist in
# launch/pre-<name>/ (default name: previous), stages the new archive and opens
# the app again. macOS ties Screen Recording permission to the signature, which
# changes with every build: re-add the app in System Settings afterwards.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
launch=$(cd "$here/.." && pwd)
bundle="$launch/Final Round Recovered.app"
backup="$launch/pre-${1:-previous}"
sh "$here/quit-recovered.sh" "$launch"
mkdir -p "$backup"
cp -p "$bundle/Contents/Resources/app.asar" "$bundle/Contents/Info.plist" "$backup/"
sh "$here/stage.sh" "$bundle"
env -u ELECTRON_RUN_AS_NODE open -n "$bundle"
