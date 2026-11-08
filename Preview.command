#!/bin/bash
set -euo pipefail
workspace="$(cd "$(dirname "$0")" && pwd)"
archive="$workspace/dist/Wake-1.1-macos-arm64.zip"
if [[ ! -f "$archive" ]]; then
    echo 'Run ./script/build_and_run.sh --build-only to build Wake first.'; exit 1
fi
(cd "$workspace/dist" && /usr/bin/shasum -a 256 -c SHA256SUMS.txt)
stage="$(mktemp -d /private/tmp/wake-preview.XXXXXX)"
mkdir -p "$workspace/.local/preview-data"
cleanup() {
    # Accepted startup jobs may finish after the window closes. Keep their runtime available.
    for ((attempt=0; attempt<150; attempt++)); do
        if ! /usr/bin/pgrep -f "$stage/Wake.app/Contents/Resources/Core/ipc.py" >/dev/null; then break; fi
        sleep 1
    done
    if /usr/bin/pgrep -f "$stage/Wake.app/Contents/Resources/Core/ipc.py" >/dev/null; then
        echo 'A launch is still finishing. The temporary app remains at:' "$stage"; return
    fi
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -u "$stage/Wake.app" 2>/dev/null || true
    rm -rf "$stage"
}
trap cleanup EXIT
COPYFILE_DISABLE=1 /usr/bin/ditto -x -k "$archive" "$stage"
/usr/bin/codesign --verify --deep --strict "$stage/Wake.app"
echo 'Opening Wake 1.1. Preview data stays in .local/preview-data. The temporary app is cleaned up on quit.'
WAKE_DATA_DIR="$workspace/.local/preview-data" "$stage/Wake.app/Contents/MacOS/Wake"
