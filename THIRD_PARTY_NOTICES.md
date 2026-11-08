# Third-party notices

Wake's original source code is licensed under MIT. Third-party components retain their own licenses.

| Component | Role | License / provenance |
| --- | --- | --- |
| CPython 3.12.16 | Bundled standard-library runtime | Python Software Foundation License Version 2 and incorporated notices; see the bundled `Python/lib/python3.12/LICENSE.txt` |
| python-build-standalone 20261026 | Relocatable arm64 runtime distribution | [Upstream release](https://github.com/astral-sh/python-build-standalone/releases/tag/20261026); fixed assets and SHA-256 values are in `runtime.lock.json` |
| Runtime dependencies | Libraries incorporated into the above Python build | Original license files referenced by the matching full distribution's `PYTHON.json`, copied into `Contents/Resources/Licenses/Python-dependencies/` |
| Apple SDKs and system frameworks | SwiftUI, AppKit and system services | Provided by the operating system / Xcode; not vendored in this repository |

The build excludes pip, site-packages, development headers, static archives, test suites and unused Python GUI modules (Tcl/Tk) from the app. It preserves CPython's license and the full build's dependency license texts, even when a dependency is not needed by Wake. Zstandard is used only as a build tool to extract notices; its executable is not bundled.

The cloud app icon is a project asset created for Wake. It is included under the project's MIT license. The interface uses Apple's public system APIs and symbols.

Runtime upgrades require updating both pinned archives, verifying hashes, reviewing `PYTHON.json` and the dependency notices, then rebuilding and testing. The build scripts do not copy a runtime from another locally installed product.

References: [runtime distribution metadata](https://gregoryszorc.com/docs/python-build-standalone/main/distributions.html), [Python license](https://docs.python.org/3.12/license.html).
