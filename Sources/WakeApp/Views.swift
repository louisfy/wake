import SwiftUI

// Keep using the State property wrapper with the Command Line Tools SDK.
private typealias WakeState<Value> = SwiftUI.State<Value>

private let ink = Color(red: 28/255, green: 28/255, blue: 30/255)
private let quiet = Color(red: 97/255, green: 97/255, blue: 105/255)
private let accent = Color(red: 10/255, green: 132/255, blue: 1)
private let actionBlue = Color(red: 0, green: 96/255, blue: 223/255)
private let line = Color.black.opacity(0.09)

private struct WakeGlassContainer: ViewModifier {
    @ViewBuilder func body(content: Content) -> some View {
        if #available(macOS 26, *) {
            GlassEffectContainer(spacing: 0) { content }
        } else {
            content
        }
    }
}

private struct WakeButton: ViewModifier {
    var prominent: Bool = false
    var width: CGFloat? = nil
    var height: CGFloat = 34
    var selected: Bool = false
    func body(content: Content) -> some View {
        content.buttonStyle(WakeControlStyle(prominent: prominent, width: width, height: height, selected: selected))
    }
}

private struct WakeControlStyle: ButtonStyle {
    let prominent: Bool
    let width: CGFloat?
    let height: CGFloat
    let selected: Bool
    @Environment(\.isEnabled) private var enabled
    @Environment(\.appearsActive) private var appearsActive

    @ViewBuilder func makeBody(configuration: Configuration) -> some View {
        let highlighted = prominent && appearsActive && enabled
        let foreground: Color = highlighted ? .white : configuration.role == .destructive ? .red : ink
        let label = configuration.label
            .padding(.horizontal, width == nil ? 13 : 0)
            .frame(width: width, height: height)
            .foregroundStyle(foreground)
            .background(selected ? Color.black.opacity(0.055) : .clear, in: Capsule())
            .contentShape(Capsule())
            .opacity(enabled ? 1 : 0.52)
        if #available(macOS 26, *) {
            label.glassEffect(highlighted ? .regular.tint(actionBlue).interactive() : .regular.interactive(), in: Capsule())
        } else {
            label.background(highlighted ? actionBlue : Color(white: selected || configuration.isPressed ? 0.91 : 0.96), in: Capsule())
                .overlay { Capsule().strokeBorder(line, lineWidth: 0.65).allowsHitTesting(false) }
        }
    }
}

private struct StatusLabel: View {
    let product: Product
    private var color: Color {
        switch product.status {
        case "running": return Color(red: 0.19, green: 0.57, blue: 0.34)
        case "starting": return accent
        case "failed": return Color(red: 0.73, green: 0.24, blue: 0.23)
        case "incomplete", "conflict", "blocked": return Color(red: 0.65, green: 0.43, blue: 0.15)
        default: return Color(red: 0.47, green: 0.49, blue: 0.53)
        }
    }

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(color).frame(width: 6, height: 6).accessibilityHidden(true)
            Text(product.label).lineLimit(1)
        }
        .font(.system(size: 11, weight: .medium))
        .foregroundStyle(quiet)
        .accessibilityElement(children: .combine)
    }
}

private struct ProductIcon: View {
    let product: Product
    var body: some View {
        Image(systemName: product.symbol)
            .font(.system(size: 20, weight: .regular))
            .foregroundStyle(ink.opacity(0.80))
            .frame(width: 44, height: 44)
            .background(Color(white: 0.96), in: RoundedRectangle(cornerRadius: 14))
            .accessibilityHidden(true)
    }
}

private struct ProductCard: View, Equatable {
    let product: Product
    let busy: Bool
    let store: WakeStore
    let autoOpen: Bool
    let showDetails: () -> Void

    let language: WakeLanguage
    private var actionTitle: String {
        if product.needs_approval == true && (product.can_start || product.can_open) { return l("Review") }
        if product.can_open { return l("Open") }
        if product.can_start { return l("Start") }
        return l("Inspect")
    }

    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.product == rhs.product && lhs.busy == rhs.busy
            && lhs.autoOpen == rhs.autoOpen && lhs.language == rhs.language && lhs.store === rhs.store
    }

    var body: some View {
        HStack(spacing: 13) {
            ProductIcon(product: product)
            VStack(alignment: .leading, spacing: 5) {
                Text(product.name).font(.system(size: 15, weight: .semibold)).foregroundStyle(ink).lineLimit(1).help(product.name)
                Text(product.description).font(.system(size: 12)).foregroundStyle(quiet).lineLimit(1).help(product.description)
                HStack(spacing: 8) {
                    StatusLabel(product: product)
                    if let port = product.next_port {
                        Text(l("Expected %@", String(port))).font(.system(size: 10, design: .monospaced)).foregroundStyle(quiet).lineLimit(1)
                    } else if !product.ports.isEmpty {
                        Text(product.portText).font(.system(size: 10, design: .monospaced)).foregroundStyle(quiet).lineLimit(1)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            HStack(spacing: 8) {
                if busy || product.status == "starting" {
                    Button {} label: { ProgressView().controlSize(.small) }
                        .modifier(WakeButton(width: 62)).disabled(true).accessibilityLabel(l("Starting %@", product.name))
                } else {
                    Button {
                        if product.needs_approval == true && (product.can_start || product.can_open) { showDetails() }
                        else if product.can_open { perform("open") }
                        else if product.can_start && product.needs_approval != true { perform("start") }
                        else { showDetails() }
                    } label: {
                        Text(actionTitle)
                            .font(.system(size: 12, weight: .semibold))
                    }
                    .modifier(WakeButton(prominent: product.can_start && !product.can_open, width: 62))
                    .accessibilityLabel(l("%1$@: %2$@", actionTitle, product.name))
                }
                Button(action: showDetails) { Image(systemName: "ellipsis").font(.system(size: 13, weight: .semibold)) }
                    .modifier(WakeButton(width: 34))
                    .help(l("View deployment and service details"))
                    .accessibilityLabel(l("Details for %@", product.name))
            }
        }
        .padding(.horizontal, 17)
        .padding(.vertical, 17)
        .frame(height: 100)
        .background {
            Capsule().fill(.white)
                .shadow(color: .black.opacity(0.035), radius: 7, y: 2)
        }
        .overlay { Capsule().strokeBorder(line, lineWidth: 0.7).allowsHitTesting(false) }
        .accessibilityElement(children: .contain)
    }

    private func perform(_ action: String) {
        Task { await store.perform(product.id, action, autoOpen: autoOpen) }
    }
}

private enum WakeSheet: Identifiable {
    case detail(Product)
    case settings
    case report
    case ports

    var id: String {
        switch self {
        case .detail(let product): return "product:\(product.id)"
        case .settings: return "settings"
        case .report: return "report"
        case .ports: return "ports"
        }
    }
}

struct WakeView: View {
    @ObservedObject var store: WakeStore
    var onLanguageChange: () -> Void
    @AppStorage(WakeLanguage.preferenceKey) private var language: WakeLanguage = .english
    @AppStorage("openAfterWake") private var autoOpen = true
    @WakeState private var filter = Filter.all
    @WakeState private var query = ""
    @WakeState private var sheet: WakeSheet?
    @WakeState private var sheetClosing = false
    @FocusState private var searchFocused: Bool

    private var visible: [Product] {
        let value = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return store.products.filter { product in
            (filter == .all || product.group == filter) && (value.isEmpty ||
              "\(product.name) \(product.description) \(product.category) \(product.portText) \(product.next_port.map(String.init) ?? "")".localizedStandardContains(value))
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            VStack(spacing: 0) {
                header
                controls
            }
            .modifier(WakeGlassContainer())
            if let error = store.error {
                Label(error, systemImage: "exclamationmark.circle").font(.system(size: 12)).foregroundStyle(quiet)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 30).padding(.vertical, 12)
            }
            ScrollView {
                if visible.isEmpty { empty }
                else {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 382), spacing: 14)], spacing: 13) {
                        ForEach(visible) { product in
                            ProductCard(product: product, busy: store.busy.contains(product.id),
                                        store: store, autoOpen: autoOpen,
                                        showDetails: { present(.detail(product)) }, language: language)
                                .equatable()
                        }
                    }
                    .padding(.horizontal, 30).padding(.top, 7).padding(.bottom, 22)
                    .modifier(WakeGlassContainer())
                }
            }
            footer
        }
        .frame(minWidth: 650, minHeight: 510)
        .background(Color.white)
        .foregroundStyle(ink)
        .preferredColorScheme(.light)
        .environment(\.locale, language.locale)
        .task { await store.monitor() }
        .onChange(of: language) { _, _ in
            onLanguageChange()
            Task { await store.languageChanged() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .wakeSettings)) { _ in present(.settings) }
        .onReceive(NotificationCenter.default.publisher(for: .wakeSearch)) { _ in searchFocused = true }
        .onReceive(NotificationCenter.default.publisher(for: .wakeRefresh)) { _ in Task { await store.refresh(manual: true) } }
        .onChange(of: store.report != nil) { _, hasReport in
            if hasReport { present(.report) }
            else if case .report = sheet { dismissSheet() }
        }
        .sheet(item: Binding(get: { sheet }, set: { if $0 == nil { dismissSheet() } }), onDismiss: {
            sheetClosing = false
            if store.report != nil { present(.report) }
        }) { active in
            switch active {
            case .detail(let product):
                DetailView(product: product, store: store, autoOpen: autoOpen)
            case .settings:
                preferences
            case .report:
                if let report = store.report { reportView(report) }
            case .ports:
                portReview
            }
        }
        .overlay(alignment: .bottom) {
            if let notice = store.notice {
                Text(notice).font(.system(size: 12, weight: .medium)).padding(.horizontal, 16).padding(.vertical, 10)
                    .background(.regularMaterial, in: Capsule()).overlay { Capsule().strokeBorder(line, lineWidth: 0.5) }
                    .shadow(color: .black.opacity(0.09), radius: 12, y: 4).padding(.bottom, 43)
                    .allowsHitTesting(false).accessibilityAddTraits(.updatesFrequently)
            }
        }
    }

    private func present(_ next: WakeSheet) {
        guard sheet == nil, !sheetClosing else { return }
        sheet = next
    }

    private func dismissSheet() {
        guard let sheet else { return }
        sheetClosing = true
        if case .report = sheet { store.report = nil }
        self.sheet = nil
    }

    private var header: some View {
        HStack(spacing: 11) {
            Image(nsImage: NSApplication.shared.applicationIconImage).resizable().scaledToFit()
                .frame(width: 44, height: 44)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(l("Wake")).font(.system(size: 26, weight: .semibold))
                Text(l("Local project workbench")).font(.system(size: 12)).foregroundStyle(quiet)
            }
            Spacer()
            Button {
                Task { await store.synchronize() }
            } label: {
                Label(store.syncing ? l("Scanning…") : l("Scan & Sync"), systemImage: "viewfinder").font(.system(size: 12, weight: .medium))
                    .padding(.horizontal, 3)
            }
            .modifier(WakeButton(width: 116))
            .disabled(store.syncing)
            .help(l("Discover local deployments and sync the project list"))
            Button { Task { await store.refresh(manual: true) } } label: { Image(systemName: "arrow.clockwise").frame(width: 15) }
                .modifier(WakeButton(width: 34)).help(l("Refresh service status")).accessibilityLabel(l("Refresh service status"))
            Button { present(.settings) } label: { Image(systemName: "gearshape").frame(width: 15) }
                .modifier(WakeButton(width: 34)).help(l("Settings")).accessibilityLabel(l("Settings"))
        }
        .controlSize(.regular)
        .padding(.horizontal, 30)
        .padding(.top, 23)
        .padding(.bottom, 21)
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass").foregroundStyle(quiet)
                TextField(l("Search projects, descriptions, or ports"), text: $query).textFieldStyle(.plain).font(.system(size: 13))
                    .focused($searchFocused).accessibilityLabel(l("Search projects, descriptions, or ports"))
                if !query.isEmpty {
                    Button { query = "" } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(quiet) }
                        .buttonStyle(.plain).accessibilityLabel(l("Clear search"))
                } else { Text("⌘ F").font(.system(size: 11, weight: .medium)).foregroundStyle(quiet) }
            }
            .padding(.horizontal, 13).frame(height: 39)
            .background(Color(white: 0.965), in: Capsule())
            .overlay { Capsule().strokeBorder(searchFocused ? accent.opacity(0.58) : line, lineWidth: 0.7).allowsHitTesting(false) }

            HStack(spacing: 9) {
                ForEach(Filter.allCases) { item in
                    let count = item == .all ? store.products.count : store.products.filter { $0.group == item }.count
                    Button { filter = item } label: {
                        HStack(spacing: 6) {
                            Text(item.title).fontWeight(filter == item ? .semibold : .regular)
                            if store.checked != nil { Text(count.formatted()).monospacedDigit().foregroundStyle(quiet) }
                        }
                        .font(.system(size: 12)).padding(.horizontal, 3)
                    }
                    .modifier(WakeButton(width: language == .english ? 94 : 88, height: 30, selected: filter == item)).controlSize(.small)
                    .accessibilityAddTraits(filter == item ? .isSelected : [])
                }
                Spacer()
                if store.loading || store.syncing {
                    ProgressView().controlSize(.small)
                }
                if !store.portIssues.isEmpty {
                    Button { present(.ports) } label: {
                        Label(l("Ports %@", String(store.portIssues.count)), systemImage: "point.3.connected.trianglepath.dotted")
                            .font(.system(size: 12, weight: .medium))
                    }
                    .modifier(WakeButton(height: 30))
                }
            }
        }
        .padding(.horizontal, 30).padding(.bottom, 15)
    }

    private var empty: some View {
        VStack(spacing: 10) {
            if store.loading && store.checked == nil { ProgressView().controlSize(.small) }
            else { Image(systemName: "magnifyingglass").font(.system(size: 22)).foregroundStyle(quiet) }
            Text(store.checked == nil ? (store.error == nil ? l("Loading local projects") : l("Could not load projects")) : store.products.isEmpty ? (store.scanRoots.isEmpty ? l("Choose a folder containing your projects") : l("Scan your selected folders to discover projects")) : l("No matching projects"))
                .font(.system(size: 15, weight: .semibold))
            if store.error != nil {
                Button(l("Retry")) { Task { await store.refresh(manual: true) } }.modifier(WakeButton())
            } else if store.checked != nil && store.products.isEmpty && store.scanRoots.isEmpty {
                Text(l("Wake scans only the folders you select. You can review each command before its first launch."))
                    .font(.system(size: 12)).foregroundStyle(quiet)
                Button(l("Choose Folder")) { chooseFolder() }.modifier(WakeButton(prominent: true))
            } else if store.checked != nil && store.products.isEmpty {
                Button(l("Scan & Sync")) { Task { await store.synchronize() } }
                    .modifier(WakeButton(prominent: true)).disabled(store.syncing)
            } else if store.checked != nil {
                Button(l("Show All")) { query = ""; filter = .all }.modifier(WakeButton())
            }
        }
        .padding(.top, 65).frame(maxWidth: .infinity)
    }

    private var footer: some View {
        HStack {
            Label(l("Runs on this Mac"), systemImage: "laptopcomputer")
            Spacer()
            if let checked = store.checked { Text(l("Last checked %@", checked.formatted(Date.FormatStyle(date: .omitted, time: .standard, locale: language.locale)))) }
            Text(l("Projects: %@", store.products.count.formatted())).monospacedDigit()
        }
        .font(.system(size: 11)).foregroundStyle(quiet)
        .padding(.horizontal, 30).padding(.vertical, 13)
        .background(Color.white)
        .overlay(alignment: .top) { Rectangle().fill(line).frame(height: 0.5) }
    }

    private var preferences: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text(l("Settings")).font(.system(size: 21, weight: .semibold))
            VStack(alignment: .leading, spacing: 7) {
                Picker(l("Language"), selection: $language) {
                    ForEach(WakeLanguage.allCases, id: \.self) { option in
                        Text(option.title).tag(option)
                    }
                }
                .pickerStyle(.segmented)
                Text(l("Language changes apply immediately. Running services keep their state."))
                    .font(.system(size: 11)).foregroundStyle(quiet)
            }
            Toggle(l("Open projects when ready"), isOn: $autoOpen).toggleStyle(.switch).tint(actionBlue)
            Divider()
            VStack(alignment: .leading, spacing: 7) {
                Text(l("Scan folders")).fontWeight(.medium)
                if store.scanRoots.isEmpty { Text(l("No folders selected")).font(.system(size: 12)).foregroundStyle(quiet) }
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(store.scanRoots, id: \.self) { root in
                            HStack {
                                Text(root).font(.system(size: 12)).foregroundStyle(quiet).textSelection(.enabled)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                Button { Task { await store.setScanRoots(store.scanRoots.filter { $0 != root }) } } label: {
                                    Image(systemName: "minus").frame(width: 12)
                                }.modifier(WakeButton(width: 30, height: 30)).accessibilityLabel(l("Remove scan folder %@", root))
                            }
                        }
                    }
                }.frame(maxHeight: 160)
                Button(l("Add Folder")) { chooseFolder() }.modifier(WakeButton()).disabled(store.syncing)
                Text(l("Removing a scan folder keeps its files and existing project cards."))
                    .font(.system(size: 11)).foregroundStyle(quiet)
            }
            HStack {
                Button(l("Edit Inventory")) { Task { await store.perform("settings", "config") } }.modifier(WakeButton())
                Button(l("Open Data Folder")) { NSWorkspace.shared.open(store.dataDirectory) }.modifier(WakeButton())
                Spacer()
                Button(l("Done"), action: dismissSheet).modifier(WakeButton(prominent: true)).keyboardShortcut(.defaultAction)
            }
        }
        .padding(24).frame(width: 490)
    }

    private func chooseFolder() {
        let panel = NSOpenPanel()
        panel.title = l("Choose a folder containing your projects")
        panel.prompt = l("Add Folder")
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url {
            Task { await store.setScanRoots(store.scanRoots + [url.path]) }
        }
    }

    private func reportView(_ report: SyncResult.Report) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(l("Scan & sync complete")).font(.system(size: 21, weight: .semibold))
            Text(l("Folders scanned: %@ · Projects: %@", report.scanned_directories.formatted(), report.total.formatted())).foregroundStyle(quiet)
            HStack(spacing: 11) {
                countCell(report.added.count, l("Added"))
                countCell(report.updated.count, l("Updated"))
                countCell(report.removed.count, l("Removed"))
            }
            if report.added.isEmpty && report.updated.isEmpty && report.removed.isEmpty {
                Text(l("The project list is up to date.")).foregroundStyle(quiet)
            }
            if !report.added.isEmpty || !report.updated.isEmpty || !report.removed.isEmpty || !report.warnings.isEmpty || !store.portIssues.isEmpty {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        changes(l("New projects"), report.added)
                        changes(l("Updated projects"), report.updated)
                        changes(l("Removed cards"), report.removed)
                        ForEach(report.warnings, id: \.self) { Text($0).font(.system(size: 11)).foregroundStyle(quiet) }
                        if !store.portIssues.isEmpty {
                            Text(l("Port Checks")).font(.system(size: 12, weight: .semibold))
                            portRows
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }.frame(maxHeight: 270)
            }
            HStack {
                if store.canUndo { Button(l("Undo Sync")) { Task { await store.synchronize(undo: true) } }.modifier(WakeButton()).disabled(store.syncing) }
                Spacer()
                Button(l("Done"), action: dismissSheet).modifier(WakeButton(prominent: true)).keyboardShortcut(.defaultAction)
            }
        }
        .padding(24).frame(width: 490)
    }

    private var portReview: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(l("Port Checks")).font(.system(size: 21, weight: .semibold))
            Text(l("Running projects keep their ports. For projects that can switch ports, Wake checks availability again before launch."))
                .font(.system(size: 12)).foregroundStyle(quiet)
            ScrollView {
                VStack(alignment: .leading, spacing: 12) { portRows }
                    .frame(maxWidth: .infinity, alignment: .leading)
            }.frame(maxHeight: 320)
            HStack {
                Spacer()
                Button(l("Done"), action: dismissSheet).modifier(WakeButton(prominent: true)).keyboardShortcut(.defaultAction)
            }
        }
        .padding(24).frame(width: 490)
    }

    private var portRows: some View {
        ForEach(store.portIssues) { issue in
            VStack(alignment: .leading, spacing: 5) {
                Text(String(issue.port)).font(.system(size: 13, weight: .semibold, design: .monospaced))
                if issue.products.count > 1 {
                    Text(l("Shared by %@", wakeList(issue.products)))
                }
                if !issue.blocked.isEmpty {
                    Text(l("In use · Affects %@", wakeList(issue.blocked)))
                }
            }.font(.system(size: 12)).foregroundStyle(quiet)
        }
    }

    private func countCell(_ count: Int, _ title: String) -> some View {
        VStack(spacing: 5) {
            Text(count.formatted()).font(.system(size: 22, weight: .semibold)).monospacedDigit()
            Text(title).font(.system(size: 11)).foregroundStyle(quiet)
        }.frame(maxWidth: .infinity).padding(12).background(Color(white: 0.963), in: RoundedRectangle(cornerRadius: 13))
    }

    @ViewBuilder private func changes(_ title: String, _ items: [SyncResult.Report.Change]) -> some View {
        if !items.isEmpty {
            Text(title).font(.system(size: 12, weight: .semibold))
            ForEach(items) { item in
                VStack(alignment: .leading, spacing: 3) {
                    Text(item.name).font(.system(size: 12))
                    if let info = item.root ?? item.reason { Text(info).font(.system(size: 11)).foregroundStyle(quiet) }
                }
            }
        }
    }
}

private struct DetailView: View {
    let product: Product
    @ObservedObject var store: WakeStore
    let autoOpen: Bool
    @Environment(\.dismiss) private var dismiss

    private var current: Product { store.products.first { $0.id == product.id } ?? product }

    var body: some View {
        VStack(alignment: .leading, spacing: 15) {
            HStack(spacing: 12) {
                ProductIcon(product: current)
                VStack(alignment: .leading, spacing: 4) {
                    Text(current.name).font(.system(size: 20, weight: .semibold))
                    Text(current.category).font(.system(size: 12)).foregroundStyle(quiet)
                }
                Spacer()
                Button { dismiss() } label: { Image(systemName: "xmark").frame(width: 14) }
                    .modifier(WakeButton(width: 34)).accessibilityLabel(l("Close details")).keyboardShortcut(.cancelAction)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    StatusLabel(product: current)
                    Text(current.reason).font(.system(size: 12)).foregroundStyle(quiet).fixedSize(horizontal: false, vertical: true)
                    Divider()
                    row(l("Project folder"), current.root)
                    row(l("Service ports"), current.portText)
                    if let url = current.url { row(l("Local address"), url) }
                    if let portNote = current.port_note { row(l("Port check"), portNote) }
                    if !current.pids.isEmpty { row(l("Processes"), current.pids.map(String.init).joined(separator: ", ")) }
                    if !current.checks.isEmpty {
                        Divider()
                        Text(l("Deployment checks")).font(.system(size: 12, weight: .semibold))
                        ForEach(Array(current.checks.enumerated()), id: \.offset) { _, check in
                            Label(check.ok ? check.label : l("%@ · Missing", check.label), systemImage: check.ok ? "checkmark" : "exclamationmark.circle")
                                .font(.system(size: 11)).foregroundStyle(quiet).help(check.path)
                        }
                    }
                    if let note = current.note, !note.isEmpty {
                        Text(note).font(.system(size: 11)).foregroundStyle(quiet).fixedSize(horizontal: false, vertical: true)
                    }
                    if current.needs_approval == true && (current.can_start || current.can_open) {
                        Divider()
                        Text(l("Review before first launch")).font(.system(size: 12, weight: .semibold))
                        Text(l("Only continue if you trust the code in this folder. Wake runs the command below with your user permissions and asks again if the launch configuration changes."))
                            .font(.system(size: 12)).foregroundStyle(quiet)
                        if let command = current.command_preview {
                            Text(command).font(.system(size: 11, design: .monospaced)).textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading).padding(10)
                                .background(Color(white: 0.96), in: RoundedRectangle(cornerRadius: 10))
                        }
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }.frame(maxHeight: 360)
            HStack {
                Button(l("Show in Finder")) { perform("reveal") }.modifier(WakeButton())
                Button(l("Launch Log")) { perform("log") }.modifier(WakeButton())
                if current.can_stop { Button(l("Stop Service"), role: .destructive) { perform("stop") }.modifier(WakeButton()) }
                Spacer()
                if current.can_open {
                    Button(current.needs_approval == true ? l("Trust & Open") : l("Open")) {
                        Task { await store.perform(current.id, "open", autoOpen: autoOpen,
                                                  approval: current.needs_approval == true ? current.approval_fingerprint : nil) }
                    }.modifier(WakeButton(prominent: true))
                }
                else if current.can_start {
                    Button(current.needs_approval == true ? l("Trust & Start") : l("Start")) {
                        Task { await store.perform(current.id, "start", autoOpen: autoOpen,
                                                  approval: current.needs_approval == true ? current.approval_fingerprint : nil) }
                    }.modifier(WakeButton(prominent: true))
                }
            }.disabled(store.busy.contains(current.id))
        }
        .padding(24).frame(width: 535)
    }

    private func row(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(label).foregroundStyle(quiet).frame(width: 81, alignment: .leading)
            Text(value).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
        }.font(.system(size: 11))
    }

    private func perform(_ action: String) {
        Task { await store.perform(current.id, action, autoOpen: autoOpen) }
    }
}
