#!/bin/sh
# Put the built archive into an app bundle and re-sign it.
#
#   launch/build/stage.sh "<path to Final Round Recovered.app>"
#
# Electron checks the archive header against Info.plist (ElectronAsarIntegrity),
# so the hash is updated before the bundle is signed ad hoc. Run build.sh first.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
bundle=$1
archive="$here/out/local-workspace.asar"
report="$here/../reports/repack.json"
[ -f "$archive" ] || { echo "Missing $archive; run build.sh first." >&2; exit 1; }
contents="$bundle/Contents"
cp "$archive" "$contents/Resources/app.asar.new"
mv "$contents/Resources/app.asar.new" "$contents/Resources/app.asar"
hash=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["headerSha256"])' "$report")
[ -n "$hash" ] || { echo "No headerSha256 in $report; run build.sh first." >&2; exit 1; }
plutil -replace 'ElectronAsarIntegrity.Resources/app\.asar.hash' -string "$hash" "$contents/Info.plist"
# Sign with the local certificate when it exists: macOS then ties permissions
# (microphone, screen and system audio recording) to the certificate instead
# of the build's hash, so they survive rebuilds. Otherwise sign ad hoc.
identity=${FRLOCAL_SIGN_IDENTITY:-Final Round Recovered Local Signing}
if security find-certificate -c "$identity" >/dev/null 2>&1; then
  codesign --force --deep --sign "$identity" "$bundle" 2>&1 | tail -1
else
  echo "Signing ad hoc: no \"$identity\" certificate in the keychain (permissions reset on every build)." >&2
  codesign --force --deep --sign - "$bundle" 2>&1 | tail -1
fi
codesign --verify --deep --strict "$bundle"
echo "Staged $hash into $bundle"
