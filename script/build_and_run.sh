#!/bin/bash
set -euo pipefail

workspace="$(cd "$(dirname "$0")/.." && pwd)"
build_dir="$workspace/.build-native"
archive="$workspace/dist/Wake-1.1-macos-arm64.zip"
installed="/Applications/Wake.app"
bundle_id="${WAKE_BUNDLE_ID:-dev.wake.launcher}"
sign_identity="${WAKE_CODESIGN_IDENTITY:--}"
mode="${1:---build-only}"
case "$mode" in
    run|--build-only|--install) ;;
    *) echo "usage: $0 [--build-only|--install|run]" >&2; exit 2 ;;
esac
if [[ "$(uname -m)" != arm64 ]]; then
    echo 'This release currently builds Apple Silicon (arm64) only.' >&2; exit 1
fi
if [[ ! "$bundle_id" =~ ^[a-zA-Z0-9.-]+$ ]]; then
    echo 'Invalid bundle identifier' >&2; exit 1
fi
mkdir -p "$build_dir" "$workspace/dist"
runtime="${WAKE_PYTHON_RUNTIME:-}"
if [[ -z "$runtime" ]]; then
    runtime="$(/usr/bin/python3 -B "$workspace/script/fetch_runtime.py")"
fi
if [[ ! -x "$runtime/bin/python3.12" || ! -d "$runtime/lib" || ! -d "$runtime/upstream-licenses" ]]; then
    echo 'Runtime must include Python 3.12, lib/, and verified upstream-licenses/.' >&2; exit 1
fi
/usr/bin/python3 -B "$workspace/script/privacy_check.py" --source
export CLANG_MODULE_CACHE_PATH="$build_dir/clang-cache"
export SWIFTPM_MODULECACHE_OVERRIDE="$build_dir/swift-cache"
swift build --package-path "$workspace" --scratch-path "$build_dir/swift" -c release --product Wake \
    -Xswiftc -file-prefix-map -Xswiftc "$workspace=/Wake" \
    -Xswiftc -debug-prefix-map -Xswiftc "$workspace=/Wake"
binary="$(swift build --package-path "$workspace" --scratch-path "$build_dir/swift" -c release --show-bin-path)/Wake"
stage="$(mktemp -d "$build_dir/stage.XXXXXX")"
install_stage=""
cleanup() {
    rm -rf "$stage"
    if [[ -n "$install_stage" ]]; then
        if [[ -d "$install_stage/previous" && ! -e "$installed" ]]; then
            mv "$install_stage/previous" "$installed" || return
        fi
        rm -rf "$install_stage"
    fi
}
trap cleanup EXIT
staged_bundle="$stage/Wake.app"
contents="$staged_bundle/Contents"
resources="$contents/Resources"
mkdir -p "$contents/MacOS" "$resources/Core" "$resources/Python/bin" "$resources/Licenses" "$stage/Wake.iconset"
cp "$binary" "$contents/MacOS/Wake"
/usr/bin/strip -S "$contents/MacOS/Wake"
cp "$workspace"/Core/*.py "$resources/Core/"
cp "$workspace/Core/messages.en.json" "$resources/Core/"
cp -R "$workspace/Resources/zh-Hans.lproj" "$resources/"
cp "$workspace/Resources/products.seed.json" "$workspace/Resources/migration.json" "$resources/"
cp "$workspace/LICENSE" "$workspace/THIRD_PARTY_NOTICES.md" "$resources/Licenses/"
cp "$workspace/runtime.lock.json" "$resources/"
cp "$runtime/bin/python3.12" "$resources/Python/bin/python3.12"
/usr/bin/python3 -B - "$runtime" "$resources" "$bundle_id" <<'PY'
import plistlib, shutil, sys
from pathlib import Path
source, resources = map(Path, sys.argv[1:3])
shutil.copytree(source/'lib', resources/'Python/lib', symlinks=True,
    ignore=shutil.ignore_patterns('site-packages','__pycache__','*.pyc','test','tests','idlelib','ensurepip','pkgconfig','*.a',
                                 'tcl*','tk*','Tix*','libtcl*','libtk*','_tkinter*'))
shutil.copytree(source/'upstream-licenses',resources/'Licenses/Python-dependencies')
info=dict(CFBundleIdentifier=sys.argv[3],CFBundleName='Wake',CFBundleDisplayName='Wake',
    CFBundleExecutable='Wake',CFBundlePackageType='APPL',CFBundleIconFile='AppIcon',
    CFBundleShortVersionString='1.1',CFBundleVersion='110',LSMinimumSystemVersion='14.0',
    NSPrincipalClass='NSApplication',NSHighResolutionCapable=True,
    LSApplicationCategoryType='public.app-category.utilities',CFBundleDevelopmentRegion='en',
    CFBundleLocalizations=['en','zh-Hans'],
    NSDocumentsFolderUsageDescription='Wake reads the project folders you select to discover and start local services.',
    NSDownloadsFolderUsageDescription='Wake reads the project folders you select to discover and start local services.',
    CFBundleURLTypes=[dict(CFBundleURLName=sys.argv[3]+'.open',CFBundleURLSchemes=['wake-launchpad'],CFBundleTypeRole='Viewer')])
with (resources.parent/'Info.plist').open('wb') as file:plistlib.dump(info,file)
PY
icon="$workspace/Resources/AppIcon.png"
for size in 16 32 128 256 512; do
    /usr/bin/sips -z "$size" "$size" "$icon" --out "$stage/Wake.iconset/icon_${size}x${size}.png" >/dev/null
    double="$((size * 2))"
    /usr/bin/sips -z "$double" "$double" "$icon" --out "$stage/Wake.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
/usr/bin/iconutil -c icns "$stage/Wake.iconset" -o "$resources/AppIcon.icns"
/usr/bin/xattr -cr "$staged_bundle"
"$resources/Python/bin/python3.12" -I -S -B -c 'import ssl,pathlib,subprocess,json; print("Bundled runtime ready")'
sign_flags=(--force --timestamp=none --sign "$sign_identity")
if [[ "${WAKE_SIGNING_MODE:-local}" == release ]]; then
    if [[ "$sign_identity" == '-' ]]; then echo 'Release signing requires a Developer ID identity.' >&2; exit 1; fi
    sign_flags=(--force --timestamp --options runtime --sign "$sign_identity")
fi
while IFS= read -r -d '' library; do
    /usr/bin/codesign "${sign_flags[@]}" "$library" 2>> "$build_dir/codesign.log"
done < <(find "$resources/Python/lib" -type f \( -name '*.so' -o -name '*.dylib' \) -print0)
/usr/bin/codesign "${sign_flags[@]}" "$resources/Python/bin/python3.12"
/usr/bin/codesign "${sign_flags[@]}" "$staged_bundle"
/usr/bin/codesign --verify --deep --strict "$staged_bundle"
/usr/bin/python3 -B "$workspace/script/zip_app.py" "$staged_bundle" "$stage/Wake.zip"
/usr/bin/python3 -B "$workspace/script/privacy_check.py" --archive "$stage/Wake.zip"
mv -f "$stage/Wake.zip" "$archive"
(cd "$workspace/dist" && /usr/bin/shasum -a 256 "$(basename "$archive")" > SHA256SUMS.txt)

if [[ "$mode" != --build-only ]]; then
    legacy="/Applications/唤醒.app"
    if [[ -d "$legacy" && ! -L "$legacy" ]] &&
        [[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$legacy/Contents/Info.plist" 2>/dev/null)" == "$bundle_id" ]]; then
        if [[ -e "$installed" || -L "$installed" ]]; then
            echo 'Both Wake.app and the legacy bundle exist. Keep only the intended installation before upgrading.' >&2; exit 1
        fi
        installed="$legacy"
    fi
    if [[ -e "$installed" || -L "$installed" ]]; then
        if [[ -L "$installed" ]] || [[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$installed/Contents/Info.plist")" != "$bundle_id" ]]; then
            echo 'Existing app has a different identity; no replacement performed.' >&2; exit 1
        fi
        if /usr/bin/pgrep -fx "$installed/Contents/MacOS/Wake" >/dev/null; then
            echo 'Quit Wake before installing.' >&2; exit 1
        fi
    fi
    install_stage="$(mktemp -d /Applications/.wake-install.XXXXXX)"
    /usr/bin/ditto "$staged_bundle" "$install_stage/candidate.app"
    /usr/bin/codesign --verify --deep --strict "$install_stage/candidate.app"
    if [[ -e "$installed" ]]; then mv "$installed" "$install_stage/previous"; fi
    mv "$install_stage/candidate.app" "$installed"
    if [[ "$mode" == run ]]; then /usr/bin/open "$installed"; fi
fi
printf 'Built %s\n' "$archive"
