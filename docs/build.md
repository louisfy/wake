# Build and distribution

[中文](zh-CN/build.md)

## Requirements

- Apple Silicon Mac. The current build packages arm64.
- Xcode or Command Line Tools with the macOS 26 SDK and Swift 6.2 or newer.
- Python 3 and **zstd** for the build. Install zstd with **brew install zstd**.
- Network access on the first build to download pinned public Python assets.

~~~sh
./script/build_and_run.sh --build-only
~~~

**runtime.lock.json** pins SHA-256 hashes for the runtime and the matching full archive. The full archive supplies licenses and build metadata. Wake bundles the smaller install-only runtime. The default build verifies downloads and caches them under **.build-native/**. For custom local builds, **WAKE_PYTHON_RUNTIME** may point to an equivalent prepared runtime with **upstream-licenses/**.

## Outputs and app identity

~~~text
dist/Wake-1.1-macos-arm64.zip
dist/SHA256SUMS.txt
~~~

The package contains **Wake.app** with bundle ID **dev.wake.launcher**. Its default data directory is **~/Library/Application Support/Wake/**. The ID and directory remain stable from 1.0. Source paths are remapped, debug symbols stripped, and filesystem metadata excluded from the ZIP.

**--build-only** leaves the installed app alone. **--install** explicitly installs **/Applications/Wake.app**. If a 1.0 install exists at **/Applications/唤醒.app** with the same bundle ID, the script upgrades that copy in place. A different app identity is never overwritten. **run** installs and opens the app. **Preview.command** runs a temporary copy with separate data in **.local/preview-data/**.

## Signing

GitHub releases provide source. The default local build is ad hoc signed and has not been notarized. It needs no signing key. A maintainer with a Developer ID identity can build with:

~~~sh
WAKE_CODESIGN_IDENTITY='Developer ID Application: YOUR PUBLISHER' \
WAKE_SIGNING_MODE=release ./script/build_and_run.sh --build-only
~~~

Before distributing a signed binary, follow [Apple's notarization instructions](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution), verify and staple the ticket, then repackage and recalculate checksums. Keep credentials, private keys, and local signing setup outside the repository.

## Checks

~~~sh
python3 -B script/privacy_check.py --source
python3 -B script/privacy_check.py --archive dist/Wake-1.1-macos-arm64.zip
python3 -B script/prepare_source.py
~~~

Check the built bundle with **codesign --verify --deep --strict**. For distribution, also check Gatekeeper and the notarization ticket. See [release acceptance](acceptance.md) for runtime and UI checks.
