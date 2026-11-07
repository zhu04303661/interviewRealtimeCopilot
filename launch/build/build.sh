#!/bin/sh
# Build everything the app needs:
#   1. the Python backend's virtual environment (launch/backend/.venv, from uv.lock);
#   2. the patched app archive (launch/build/out/local-workspace.asar).
#
# The @electron/asar module is taken from $ASAR_MODULE or the npx cache
# (`npx @electron/asar@4.2.0 --version` fills the cache once).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
(cd "$here/../backend" && uv sync --frozen --no-dev --quiet)
asar=${ASAR_MODULE:-$(ls -d "$HOME"/.npm/_npx/*/node_modules/@electron/asar/lib/asar.js 2>/dev/null | head -1)}
[ -n "$asar" ] || { echo "Set ASAR_MODULE to @electron/asar/lib/asar.js (run: npx @electron/asar@4.2.0 --version)." >&2; exit 1; }
node "$here/repack.mjs" "$root" "$asar"
