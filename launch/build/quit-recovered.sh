#!/bin/sh
# Quit every running copy of launch/Final Round Recovered.app, however it was
# opened (Finder, Dock, open, scripts), and wait until each has exited.
#
#   launch/build/quit-recovered.sh <launch dir>
set -eu
bundle=$(cd "$1/Final Round Recovered.app" && pwd)
osascript -l JavaScript - "$bundle" <<'EOF'
ObjC.import("AppKit");
function run(args) {
  const wanted = args[0];
  const matching = () => {
    const apps = ObjC.unwrap($.NSRunningApplication.runningApplicationsWithBundleIdentifier("com.finalround.desktop.recovered"));
    return apps.filter((app) => ObjC.unwrap(app.bundleURL.path) === wanted);
  };
  matching().forEach((app) => app.terminate);
  for (let i = 0; i < 30; i++) {
    if (matching().length === 0) return;
    delay(0.5);
  }
  throw new Error("Final Round Recovered did not quit");
}
EOF
