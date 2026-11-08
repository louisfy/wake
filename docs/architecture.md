# Architecture

[中文](zh-CN/architecture.md)

~~~mermaid
flowchart LR
    UI[SwiftUI / AppKit] <-->|Inherited JSON pipes| Engine[Python engine]
    Engine --> Metadata[Selected deployment folders]
    Engine --> State[Local inventory and runtime records]
    Engine --> Checks[Process, port, and HTTP checks]
    Engine -->|After command review| Services[Independent service processes]
~~~

**WakeApp** owns the window and single-instance lock. **WakeStore** manages inventory snapshots and pending actions. **ServiceBridge** owns one child process, newline-delimited JSON, request timeouts, and reconnects. There is no HTTP control endpoint.

The app defaults to English and stores the language preference in local app settings. Each request carries the selected language; the engine localizes its response and invalidates cached display data when the language changes. Language switching does not rewrite inventory fields, change launch trust, or restart the engine. Project-authored metadata and service output remain in their original language.

**discovery.py** reads supported deployment descriptions without executing project commands. **Manager** checks configuration, local processes, ports, and readiness. Dependency commands run only during a reviewed launch.

Launch leases and persisted state prevent duplicate starts across app restarts. Services start in separate process sessions. Closing the app closes its pipes and allows accepted launches to finish. Stop verifies process ID, command fingerprint, and process creation time. External and complex multi-process services may require their own stop mechanism.

Sync uses a separate lock, atomic writes, and bounded backups. Undo checks the digest before restoring so later edits are preserved.
