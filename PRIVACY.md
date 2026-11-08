# Privacy

[中文](docs/zh-CN/PRIVACY.md)

Wake runs locally. It has no account, telemetry, analytics SDK, cloud inventory, or automatic diagnostic uploads.

## What Wake reads

- Deployment metadata in the scan folders you choose, such as **package.json**, Compose files, explicit manifests, and supported service entry files.
- Local processes, listening ports, and working directories to verify ownership and find conflicts. Process command lines can contain secrets; Wake handles them locally and does not show a full process listing.
- Registered loopback HTTP endpoints for readiness checks. An explicitly configured sign-in adapter may read a local entry file.
- Docker and system background job status. Discovery does not install dependencies, build projects, pull images, or run their commands.

Deployment files can contain sensitive values. Wake extracts the fields needed to show or launch projects and does not export **.env** contents. Project names, commands, and paths in your inventory can still be private.

## What stays on this Mac

The default data directory is **~/Library/Application Support/Wake/**. It holds the project inventory, runtime records, launch trust, sync backups, and logs. **WAKE_DATA_DIR** can point to an absolute directory for isolated testing. The data directory uses user-only permissions; it is not encrypted by Wake. The language preference is saved locally in macOS app preferences.

The open-source build starts with an empty inventory and no scan folders. It does not automatically import a separate personal installation.

## Network and execution

The app talks to its engine over inherited pipes. There is no HTTP control listener or product update checker. Status checks use registered local addresses. Projects you run, Docker Desktop, and your browser can make their own network requests. The first build fetches pinned public runtime assets and does not send your inventory.

Wake asks you to review a launch command before first execution and stores trust against the launch configuration. A trusted project runs with your user permissions. Trust is not sandboxing or a guarantee that every future code change will be detected.

## Logs and sharing

Project output may include credentials and business data. Raw logs remain on your Mac. Wake masks common credential patterns in UI errors; raw logs are not sanitized. Use synthetic reproduction steps and screenshots for public reports, and omit real paths, configuration, logs, and credentials.

You can remove Wake's stored inventory, trust, and logs by removing its data directory after quitting. Back up anything you need first. This does not remove project files or stop independent services. To reset the language, use **Settings → Language**.

Source releases use an empty seed, a file allowlist, automated checks for known sensitive patterns, and review of the actual outgoing files.
