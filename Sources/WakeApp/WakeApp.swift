import AppKit
import SwiftUI

extension Notification.Name {
    static let wakeSettings = Notification.Name("WakeSettings")
    static let wakeSearch = Notification.Name("WakeSearch")
    static let wakeRefresh = Notification.Name("WakeRefresh")
}

@MainActor
final class WakeDelegate: NSObject, NSApplicationDelegate {
    private var window: NSWindow?
    private var store: WakeStore?
    private var instanceLock: Int32 = -1

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard let resources = Bundle.main.resourceURL else { return }
        let directory: URL
        if let override = ProcessInfo.processInfo.environment["WAKE_DATA_DIR"], override.hasPrefix("/") {
            directory = URL(fileURLWithPath: override, isDirectory: true)
        } else {
            directory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("Wake", isDirectory: true)
        }
        guard claimInstance(in: directory) else { return }
        let store = WakeStore(bridge: ServiceBridge(resources: resources, dataDirectory: directory))
        self.store = store
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1120, height: 760),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "唤醒"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.appearance = NSAppearance(named: .aqua)
        window.backgroundColor = .white
        window.contentMinSize = NSSize(width: 650, height: 510)
        window.contentView = NSHostingView(rootView: WakeView(store: store))
        window.isReleasedWhenClosed = false
        window.setFrameAutosaveName("Wake.MainWindow")
        if !window.setFrameUsingName("Wake.MainWindow") { window.center() }
        self.window = window
        installMenu()
        showWindow()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
        return true
    }

    func application(_ application: NSApplication, open urls: [URL]) { showWindow() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) {
        store?.close()
        if instanceLock >= 0 { Darwin.close(instanceLock) }
    }

    private func claimInstance(in directory: URL) -> Bool {
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                    attributes: [.posixPermissions: 0o700])
            let fd = Darwin.open(directory.appendingPathComponent(".instance.lock").path,
                                 O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0o600)
            guard fd >= 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
            if flock(fd, LOCK_EX | LOCK_NB) == 0 {
                instanceLock = fd
                return true
            }
            let failure = errno
            Darwin.close(fd)
            guard failure == EWOULDBLOCK else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(failure)) }
            let current = ProcessInfo.processInfo.processIdentifier
            if let identifier = Bundle.main.bundleIdentifier,
               let existing = NSRunningApplication.runningApplications(withBundleIdentifier: identifier)
                .first(where: { $0.processIdentifier != current && !$0.isTerminated }),
               let url = existing.bundleURL {
                NSWorkspace.shared.openApplication(at: url, configuration: .init()) { _, _ in }
            }
        } catch {
            let alert = NSAlert()
            alert.messageText = "无法打开唤醒"
            alert.informativeText = "本地数据目录暂时无法使用。\n\(error.localizedDescription)"
            alert.runModal()
        }
        NSApp.terminate(nil)
        return false
    }

    private func showWindow() {
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func installMenu() {
        let bar = NSMenu()
        let app = NSMenuItem(); bar.addItem(app)
        let appMenu = NSMenu(title: "唤醒"); app.submenu = appMenu
        appMenu.addItem(withTitle: "关于唤醒", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(item("设置…", #selector(openSettings), ","))
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出唤醒", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let edit = NSMenuItem(); bar.addItem(edit)
        let editMenu = NSMenu(title: "编辑"); edit.submenu = editMenu
        editMenu.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editMenu.addItem(.separator())
        editMenu.addItem(item("搜索产品", #selector(focusSearch), "f"))
        editMenu.addItem(item("刷新状态", #selector(refresh), "r"))
        NSApp.mainMenu = bar
    }

    private func item(_ title: String, _ selector: Selector, _ key: String) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: selector, keyEquivalent: key)
        item.target = self
        return item
    }

    @objc private func openSettings() { NotificationCenter.default.post(name: .wakeSettings, object: nil) }
    @objc private func focusSearch() { NotificationCenter.default.post(name: .wakeSearch, object: nil) }
    @objc private func refresh() { NotificationCenter.default.post(name: .wakeRefresh, object: nil) }
}

@main
struct WakeApplication {
    @MainActor static func main() {
        signal(SIGPIPE, SIG_IGN)
        let app = NSApplication.shared
        let delegate = WakeDelegate()
        app.setActivationPolicy(.regular)
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
