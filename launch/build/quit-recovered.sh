#!/bin/sh
set -eu
for pid in $(jq -r 'select(.event=="recovered-entry")|.pid' "$1/profile/launch-events.jsonl" | sort -u); do
  if /bin/ps -p "$pid" -o command= | rg -q 'Final Round Recovered\.app/Contents/MacOS/Final Round'; then
    osascript -l JavaScript -e 'ObjC.import("AppKit"); function run(args) { const app = $.NSRunningApplication.runningApplicationWithProcessIdentifier(Number(args[0])); if (ObjC.unwrap(app.bundleIdentifier) === "com.finalround.desktop.recovered") app.terminate; }' "$pid"
    for i in $(seq 1 14); do
      if ! kill -0 "$pid" 2>/dev/null; then continue 2; fi
      sleep 1
    done
    echo "Recovered app $pid did not quit" >&2
    exit 1
  fi
done
