# Use and configure Wake

[中文](zh-CN/configuration.md)

## Language

Wake starts in English. Choose **English** or **简体中文** under **Settings → Language**. App labels, notices, and generated service statuses switch in the current session. The choice persists across launches. macOS-managed dialog controls follow the system language. Text supplied by a project, such as its name, description, command, or log output, stays as supplied.

## Scan folders

Choose your first folder in the empty workbench. Add or remove up to 16 folders in Settings. New discovery is limited to selected folders. Existing cards can still refresh after you remove a scan folder; removing it does not delete project files or existing cards.

Scanning defaults to four levels and uses directory and time limits. It skips common dependency, build, and example folders. If a project is missing, select a folder closer to its entry. Wake preserves known entries if it cannot access their folder.

**Scan & Sync** backs up the inventory and reports added, updated, and removed cards. You can undo the latest sync as long as the inventory has not been edited afterward.

## Discovery and explicit manifests

Wake detects supported **package.json** scripts, Python services, Compose files, and **.launchpad.json** manifests. Install dependencies using the project's own instructions. Ambiguous Compose ports, combined scripts, and unrecognized launch entries may require manual setup.

See [the demo manifest](../examples/demo-service/.launchpad.json):

- **command** is an argument array. Relative command paths resolve in the project working directory.
- **ports** lists local service ports. The browser **url** must use a registered port on **http://127.0.0.1** or **http://localhost**, with no embedded credentials.
- **required** lists dependencies. Relative paths resolve from the manifest's folder.
- **match** and **cwd_match** identify the project process. Pair command patterns with a working directory to avoid ambiguous matches.
- **port_strategy: {"environment":"PORT"}** opts in only when the service can actually read that environment variable.

Vite with explicit **--port** and **--strictPort** can use an alternate port. Wake does not rewrite fixed ports or complex container deployments. Open follows the verified current port.

## Trust, exit, and stop

Review the command and directory before clicking **Trust & Start**. Wake asks again when the launch configuration or detected entry fingerprint changes. Trust does not sandbox the command or guarantee detection of every code change. To reset all launch trust, quit Wake and remove **Runtime/approvals.json** from your local Wake data directory.

Quitting Wake leaves started services running. **Stop Service** is available when Wake can verify a direct process it started. For external or wrapped processes, use the project's own stop mechanism.

## Local files

Data is stored by default in **~/Library/Application Support/Wake/**. Advanced users can open **Settings → Edit Inventory**, save their edits, and refresh. Set **WAKE_DATA_DIR** to an absolute test path to use separate state. Never copy a real inventory, sign-in entry file, or launch log into the repository.
