#!/bin/bash
set -euo pipefail
workspace="$(cd "$(dirname "$0")" && pwd)"
archive="$workspace/dist/Wake-1.0-macos-arm64.zip"
if [[ ! -f "$archive" ]]; then
    echo '请先执行 script/build_and_run.sh --build-only 构建应用包。'; exit 1
fi
(cd "$workspace/dist" && /usr/bin/shasum -a 256 -c SHA256SUMS.txt)
stage="$(mktemp -d /private/tmp/wake-preview.XXXXXX)"
mkdir -p "$workspace/.local/preview-data"
cleanup() {
    # Accepted startup jobs may finish after the window closes. Keep their runtime available.
    for ((attempt=0; attempt<150; attempt++)); do
        if ! /usr/bin/pgrep -f "$stage/唤醒.app/Contents/Resources/Core/ipc.py" >/dev/null; then break; fi
        sleep 1
    done
    if /usr/bin/pgrep -f "$stage/唤醒.app/Contents/Resources/Core/ipc.py" >/dev/null; then
        echo '启动任务仍在收尾，临时应用保留在：' "$stage"; return
    fi
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -u "$stage/唤醒.app" 2>/dev/null || true
    rm -rf "$stage"
}
trap cleanup EXIT
COPYFILE_DISABLE=1 /usr/bin/ditto -x -k "$archive" "$stage"
/usr/bin/codesign --verify --deep --strict "$stage/唤醒.app"
echo '正在打开唤醒 1.0。体验数据保存在项目 .local/preview-data；退出窗口后自动清理临时应用。'
WAKE_DATA_DIR="$workspace/.local/preview-data" "$stage/唤醒.app/Contents/MacOS/Wake"
