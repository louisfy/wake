import AppKit
import SwiftUI

struct Product: Decodable, Identifiable, Equatable {
    struct Check: Decodable, Equatable { let label: String; let path: String; let ok: Bool }
    struct Job: Decodable, Equatable { let state: String?; let message: String? }
    let id, name, description, category, icon, root, kind, status, label, reason: String
    let ports: [Int]
    let url: String?
    let pids: [Int]
    let can_start, can_open, can_stop: Bool
    let checks: [Check]
    let note: String?
    let port_note: String?
    let next_port: Int?
    let job: Job
    let needs_approval: Bool?
    let approval_fingerprint, command_preview: String?

    var group: Filter {
        switch status {
        case "running": return .running
        case "ready", "starting": return .ready
        default: return .attention
        }
    }

    var portText: String {
        if !ports.isEmpty { return ports.map(String.init).joined(separator: " / ") }
        return kind == "app" ? l("Desktop app") : kind == "launchd" ? l("Background job") : l("No service port")
    }

    var symbol: String {
        ["orca":"water.waves", "cube":"cube", "chart":"chart.bar", "sparkles":"sparkles", "medical":"cross.case",
         "layers":"square.3.layers.3d", "calendar":"calendar", "pen":"pencil.tip", "stack":"square.stack",
         "database":"externaldrive", "box":"shippingbox", "message":"text.bubble", "network":"point.3.connected.trianglepath.dotted",
         "bird":"bird", "model":"cpu", "chip":"cpu", "document":"doc.text", "workflow":"square.grid.2x2",
         "flow":"point.topleft.down.to.point.bottomright.curvepath", "flask":"testtube.2"][icon] ?? "app.dashed"
    }
}

enum Filter: String, CaseIterable, Identifiable {
    case all, running, ready, attention
    var title: String {
        switch self {
        case .all: return l("All")
        case .running: return l("Running")
        case .ready: return l("Ready")
        case .attention: return l("Attention")
        }
    }
    var id: Self { self }
}

struct Inventory: Decodable {
    let products: [Product]
    let checked_at: Double
    let scan_roots: [String]?
    let port_issues: [PortIssue]?
}

struct PortIssue: Decodable, Identifiable, Equatable {
    let port: Int
    let products, blocked: [String]
    var id: Int { port }
}

struct EngineInfo: Decodable { let version, transport: String; let pid: Int }
struct ActionResult: Decodable { let message: String }

struct SyncResult: Decodable {
    struct Report: Decodable {
        struct Change: Decodable, Identifiable { let id, name: String; let root, reason: String?; let fields: [String]? }
        let added, updated, removed: [Change]
        let warnings: [String]
        let scanned_directories, total: Int
    }
    let report: Report?
    let message: String?
    let can_undo: Bool?
}

@MainActor
final class WakeStore: ObservableObject {
    @Published private(set) var products: [Product] = []
    @Published private(set) var scanRoots: [String] = []
    @Published private(set) var portIssues: [PortIssue] = []
    @Published private(set) var checked: Date?
    @Published private(set) var busy: Set<String> = []
    @Published private(set) var loading = false
    @Published private(set) var syncing = false
    @Published private(set) var error: String?
    @Published private(set) var notice: String?
    @Published var report: SyncResult.Report?
    private var reportCanUndo = false
    private var info: EngineInfo?
    private var noticeTask: Task<Void, Never>?
    private var refreshAgain = false
    private let bridge: ServiceBridge
    var dataDirectory: URL { bridge.dataDirectory }
    var canUndo: Bool { reportCanUndo }

    init(bridge: ServiceBridge) { self.bridge = bridge }

    func languageChanged() async {
        noticeTask?.cancel()
        notice = nil
        error = nil
        report = nil
        await refresh(manual: true, announce: false)
    }

    func refresh(manual: Bool = false, announce: Bool = true) async {
        guard !loading else {
            refreshAgain = refreshAgain || manual
            return
        }
        loading = true
        defer {
            loading = false
            if refreshAgain {
                refreshAgain = false
                Task { await refresh(manual: true) }
            }
        }
        let language = WakeLanguage.current
        do {
            info = try await bridge.request("info", as: EngineInfo.self)
            let snapshot = try await bridge.request("products", parameters: ["refresh": manual], language: language, as: Inventory.self)
            guard language == WakeLanguage.current else { refreshAgain = true; return }
            apply(snapshot)
            if manual && announce {
                show(portIssues.isEmpty ? l("Deployment, status, and ports refreshed") : l("Status and ports refreshed · Port alerts: %@", String(portIssues.count)))
            }
        } catch {
            if language == WakeLanguage.current { self.error = error.localizedDescription }
        }
    }

    func perform(_ id: String, _ action: String, autoOpen: Bool = true, approval: String? = nil) async {
        guard !busy.contains(id) else { return }
        busy.insert(id)
        defer { busy.remove(id) }
        let language = WakeLanguage.current
        do {
            var parameters: [String: Any] = ["id": id, "action": action, "open": autoOpen]
            if let approval { parameters["approval"] = approval }
            let result = try await bridge.request("action", parameters: parameters, language: language, as: ActionResult.self)
            if language == WakeLanguage.current { show(result.message) }
            if ["start", "stop", "open"].contains(action) { await refresh() }
        } catch { if language == WakeLanguage.current { show(error.localizedDescription) } }
    }

    func synchronize(undo: Bool = false) async {
        guard !syncing else { return }
        syncing = true
        defer { syncing = false }
        let language = WakeLanguage.current
        do {
            let result = try await bridge.request("sync", parameters: ["mode": undo ? "undo" : "sync"], language: language, as: SyncResult.self)
            let snapshotLanguage = WakeLanguage.current
            let snapshot = try await bridge.request("products", parameters: ["refresh": true], language: snapshotLanguage, as: Inventory.self)
            if snapshotLanguage == WakeLanguage.current { apply(snapshot) }
            else { await refresh(manual: true, announce: false) }
            guard language == WakeLanguage.current else { return }
            reportCanUndo = result.can_undo == true
            report = result.report
            if let message = result.message { show(message) }
        } catch { if language == WakeLanguage.current { show(error.localizedDescription) } }
    }

    func setScanRoots(_ roots: [String]) async {
        let language = WakeLanguage.current
        do {
            let result = try await bridge.request("scan-roots", parameters: ["roots": roots], language: language, as: ActionResult.self)
            if language == WakeLanguage.current { show(result.message) }
            await refresh(manual: true)
        } catch { if language == WakeLanguage.current { show(error.localizedDescription) } }
    }

    func monitor() async {
        await refresh()
        while !Task.isCancelled {
            let delay: UInt64 = products.contains(where: { $0.status == "starting" }) ? 2 : 8
            try? await Task.sleep(nanoseconds: delay * 1_000_000_000)
            guard !Task.isCancelled else { return }
            if !syncing { await refresh() }
        }
    }

    func close() {
        bridge.close()
        try? FileManager.default.removeItem(at: dataDirectory.appendingPathComponent("Health.json"))
    }

    private func apply(_ snapshot: Inventory) {
        let previous = Dictionary(uniqueKeysWithValues: products.map { ($0.id, $0.job.state) })
        if products != snapshot.products { products = snapshot.products }
        checked = Date(timeIntervalSince1970: snapshot.checked_at)
        if scanRoots != (snapshot.scan_roots ?? []) { scanRoots = snapshot.scan_roots ?? [] }
        if portIssues != (snapshot.port_issues ?? []) { portIssues = snapshot.port_issues ?? [] }
        if error != nil { error = nil }
        for product in products where previous[product.id] == "starting" && ["done", "failed"].contains(product.job.state ?? "") {
            if let message = product.job.message { show("\(product.name) · \(message)") }
        }
        if let info, let status = try? JSONSerialization.data(withJSONObject: [
            "pid": ProcessInfo.processInfo.processIdentifier, "engine_pid": info.pid,
            "version": info.version, "transport": info.transport,
            "bundle": Bundle.main.bundleURL.path, "products": products.count,
            "running": products.filter { $0.group == .running }.count,
            "checked_at": snapshot.checked_at
        ]) { try? status.write(to: dataDirectory.appendingPathComponent("Health.json"), options: .atomic) }
    }

    private func show(_ text: String) {
        noticeTask?.cancel()
        notice = text
        noticeTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            if !Task.isCancelled { self?.notice = nil }
        }
    }
}
