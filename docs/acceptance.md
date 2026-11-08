# Release acceptance

[中文](zh-CN/acceptance.md)

Use an isolated data directory and synthetic services. Record the exact build and macOS version.

## First launch and language

- A clean launch opens one window in English with an empty inventory and a folder picker. Wake does not scan personal folders before selection.
- Choose **examples/demo-service**, click **Scan & Sync**, and verify the card and sync report. **Review** shows the launch command.
- Open Settings and switch English → 简体中文 → English. Check the search, filters, settings, menu actions, project statuses, sync report, and launch prompts.
- Reopen and check that the selected language persists. Check long paths, button labels, the smallest window, and keyboard navigation in both languages.

## Services and recovery

- Trust the sample and start it. Verify its localhost response and running status.
- Change language while it runs. The same process remains reachable and the status label changes.
- Quit and reopen Wake. The service still responds and is not started again. Stop it from details and verify the endpoint shuts down.
- Modify a synthetic launch command and verify Wake requires another review.
- Use synthetic listeners to exercise shared and occupied ports. Eligible services can switch ports; fixed deployments show a conflict.
- Verify adding and removing scan folders, syncing and undoing changes, and an offline sample launch.

## Publication

- Run tests, build, and scan the exact staged tree and archives. Confirm the seed and migration are empty and no runtime records or signing material are included.
- Review English and Chinese docs, release text, and images. Use synthetic projects for screenshots and strip unnecessary metadata.
- State the architecture, deployment target, observed runtime environment, and any limits. Do not claim macOS 14/15 or Intel verification without testing those systems. Label a source release separately from a notarized binary.
