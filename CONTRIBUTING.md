# Contributing

[中文](docs/zh-CN/CONTRIBUTING.md)

Issues, docs, translations, and code are welcome in English or Simplified Chinese. Search existing issues and pull requests first. Explain what triggers the problem, what should happen, and how you verified the change.

## Build and test

Use Apple Silicon and the macOS 26 SDK. See the [build guide](docs/build.md), then run:

~~~sh
runtime_path="$(python3 -B script/fetch_runtime.py)"
"$runtime_path/bin/python3.12" -B -m unittest discover -s Tests -q
python3 -B script/privacy_check.py --source
./script/build_and_run.sh --build-only
~~~

Use temporary directories, synthetic projects, and free loopback ports. For UI changes, check both languages, the smallest window, long names, empty lists, and errors. Wake currently uses a light appearance.

## Localize

English is the default UI and the primary language for the repository. Swift labels go through **l()** and their translations live in **Resources/zh-Hans.lproj/Localizable.strings**. The Python engine uses **Core/messages.en.json** for English renderings of its existing message templates. Keep format arguments intact and translate Wake-generated messages only. Project-supplied names, commands, descriptions, paths, and logs are user content.

Update both language versions of affected documentation. Test switching in Settings while a sample service is running.

## Protect user data

- Use synthetic data for reports, tests, and images. Keep personal inventories, real logs, **.env**, databases, signing material, and absolute home paths out of commits.
- Preserve the review-before-launch and verified-stop boundaries. Detection must not silently execute projects or install dependencies.
- Review the actual diff and image contents. New public files must fit **script/public_files.py**.
- Record what you ran and where. Separate automated checks, real UI behavior, and untested environments.

Contributions may be distributed under the project's [MIT license](LICENSE).
