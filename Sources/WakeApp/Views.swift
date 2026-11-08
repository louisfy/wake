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

    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.product == rhs.product && lhs.busy == rhs.busy
            && lhs.autoOpen == rhs.autoOpen && lhs.store === rhs.store
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
                        Text("预计 \(String(port))").font(.system(size: 10, design: .monospaced)).foregroundStyle(quiet).lineLimit(1)
                    } else if !product.ports.isEmpty {
                        Text(product.portText).font(.system(size: 10, design: .monospaced)).foregroundStyle(quiet).lineLimit(1)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            HStack(spacing: 8) {
                if busy || product.status == "starting" {
                    Button {} label: { ProgressView().controlSize(.small) }
                        .modifier(WakeButton(width: 62)).disabled(true).accessibilityLabel("正在唤醒 \(product.name)")
                } else {
                    Button {
                        if product.needs_approval == true && (product.can_start || product.can_open) { showDetails() }
                        else if product.can_open { perform("open") }
                        else if product.can_start && product.needs_approval != true { perform("start") }
                        else { showDetails() }
                    } label: {
                        Text(product.needs_approval == true && (product.can_start || product.can_open) ? "审查" : product.can_open ? "打开" : product.can_start ? "唤醒" : "检查")
                            .font(.system(size: 12, weight: .semibold))
                    }
                    .modifier(WakeButton(prominent: product.can_start && !product.can_open, width: 62))
                    .accessibilityLabel("\(product.needs_approval == true && (product.can_start || product.can_open) ? "审查" : product.can_open ? "打开" : product.can_start ? "唤醒" : "检查") \(product.name)")
                }
                Button(action: showDetails) { Image(systemName: "ellipsis").font(.system(size: 13, weight: .semibold)) }
                    .modifier(WakeButton(width: 34))
                    .help("查看部署与运行详情")
                    .accessibilityLabel("查看 \(product.name) 的详情")
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
                                        showDetails: { present(.detail(product)) })
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
        .task { await store.monitor() }
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
                Text("唤醒").font(.system(size: 26, weight: .semibold))
                Text("本地产品工作台").font(.system(size: 12)).foregroundStyle(quiet)
            }
            Spacer()
            Button {
                Task { await store.synchronize() }
            } label: {
                Label(store.syncing ? "检测中" : "检测并同步", systemImage: "viewfinder").font(.system(size: 12, weight: .medium))
                    .padding(.horizontal, 3)
            }
            .modifier(WakeButton(width: 116))
            .disabled(store.syncing)
            .help("扫描本机部署并同步服务清单")
            Button { Task { await store.refresh(manual: true) } } label: { Image(systemName: "arrow.clockwise").frame(width: 15) }
                .modifier(WakeButton(width: 34)).help("刷新服务状态").accessibilityLabel("刷新服务状态")
            Button { present(.settings) } label: { Image(systemName: "gearshape").frame(width: 15) }
                .modifier(WakeButton(width: 34)).help("唤醒设置").accessibilityLabel("唤醒设置")
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
                TextField("搜索产品、功能或端口", text: $query).textFieldStyle(.plain).font(.system(size: 13))
                    .focused($searchFocused).accessibilityLabel("搜索产品、功能或端口")
                if !query.isEmpty {
                    Button { query = "" } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(quiet) }
                        .buttonStyle(.plain).accessibilityLabel("清除搜索")
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
                            Text(item.rawValue).fontWeight(filter == item ? .semibold : .regular)
                            if store.checked != nil { Text(count.formatted()).monospacedDigit().foregroundStyle(quiet) }
                        }
                        .font(.system(size: 12)).padding(.horizontal, 3)
                    }
                    .modifier(WakeButton(width: 88, height: 30, selected: filter == item)).controlSize(.small)
                    .accessibilityAddTraits(filter == item ? .isSelected : [])
                }
                Spacer()
                if store.loading || store.syncing {
                    ProgressView().controlSize(.small)
                }
                if !store.portIssues.isEmpty {
                    Button { present(.ports) } label: {
                        Label("端口检查 \(store.portIssues.count)", systemImage: "point.3.connected.trianglepath.dotted")
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
            Text(store.checked == nil ? (store.error == nil ? "正在读取本地产品" : "暂时无法读取产品") : store.products.isEmpty ? (store.scanRoots.isEmpty ? "选择本地产品所在的文件夹" : "扫描所选文件夹，发现本地产品") : "没有符合条件的产品")
                .font(.system(size: 15, weight: .semibold))
            if store.error != nil {
                Button("重新检测") { Task { await store.refresh(manual: true) } }.modifier(WakeButton())
            } else if store.checked != nil && store.products.isEmpty && store.scanRoots.isEmpty {
                Text("只扫描你选择的位置；发现产品后，首次唤醒前会展示启动命令。")
                    .font(.system(size: 12)).foregroundStyle(quiet)
                Button("选择文件夹") { chooseFolder() }.modifier(WakeButton(prominent: true))
            } else if store.checked != nil && store.products.isEmpty {
                Button("检测同步") { Task { await store.synchronize() } }
                    .modifier(WakeButton(prominent: true)).disabled(store.syncing)
            } else if store.checked != nil {
                Button("查看全部") { query = ""; filter = .all }.modifier(WakeButton())
            }
        }
        .padding(.top, 65).frame(maxWidth: .infinity)
    }

    private var footer: some View {
        HStack {
            Label("仅在此 Mac 运行", systemImage: "laptopcomputer")
            Spacer()
            if let checked = store.checked { Text("最近检测 \(checked.formatted(date: .omitted, time: .standard))") }
            Text("\(store.products.count) 个产品").monospacedDigit()
        }
        .font(.system(size: 11)).foregroundStyle(quiet)
        .padding(.horizontal, 30).padding(.vertical, 13)
        .background(Color.white)
        .overlay(alignment: .top) { Rectangle().fill(line).frame(height: 0.5) }
    }

    private var preferences: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("唤醒设置").font(.system(size: 21, weight: .semibold))
            Toggle("产品就绪后自动打开", isOn: $autoOpen).toggleStyle(.switch).tint(actionBlue)
            Divider()
            VStack(alignment: .leading, spacing: 7) {
                Text("自动扫描位置").fontWeight(.medium)
                if store.scanRoots.isEmpty { Text("尚未选择文件夹").font(.system(size: 12)).foregroundStyle(quiet) }
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(store.scanRoots, id: \.self) { root in
                            HStack {
                                Text(root).font(.system(size: 12)).foregroundStyle(quiet).textSelection(.enabled)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                Button { Task { await store.setScanRoots(store.scanRoots.filter { $0 != root }) } } label: {
                                    Image(systemName: "minus").frame(width: 12)
                                }.modifier(WakeButton(width: 30, height: 30)).accessibilityLabel("移除扫描位置 \(root)")
                            }
                        }
                    }
                }.frame(maxHeight: 160)
                Button("添加文件夹") { chooseFolder() }.modifier(WakeButton()).disabled(store.syncing)
                Text("移除扫描位置不会删除产品文件或已有卡片。")
                    .font(.system(size: 11)).foregroundStyle(quiet)
            }
            HStack {
                Button("编辑产品清单") { Task { await store.perform("settings", "config") } }.modifier(WakeButton())
                Button("打开数据文件夹") { NSWorkspace.shared.open(store.dataDirectory) }.modifier(WakeButton())
                Spacer()
                Button("完成", action: dismissSheet).modifier(WakeButton(prominent: true)).keyboardShortcut(.defaultAction)
            }
        }
        .padding(24).frame(width: 490)
    }

    private func chooseFolder() {
        let panel = NSOpenPanel()
        panel.title = "选择本地产品所在的文件夹"
        panel.prompt = "添加扫描位置"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url {
            Task { await store.setScanRoots(store.scanRoots + [url.path]) }
        }
    }

    private func reportView(_ report: SyncResult.Report) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("检测与同步完成").font(.system(size: 21, weight: .semibold))
            Text("扫描 \(report.scanned_directories) 个目录 · 现有 \(report.total) 个产品").foregroundStyle(quiet)
            HStack(spacing: 11) {
                countCell(report.added.count, "新增")
                countCell(report.updated.count, "更新")
                countCell(report.removed.count, "移除")
            }
            if report.added.isEmpty && report.updated.isEmpty && report.removed.isEmpty {
                Text("清单已是最新。").foregroundStyle(quiet)
            }
            if !report.added.isEmpty || !report.updated.isEmpty || !report.removed.isEmpty || !report.warnings.isEmpty || !store.portIssues.isEmpty {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        changes("新增服务", report.added)
                        changes("更新信息", report.updated)
                        changes("移除卡片", report.removed)
                        ForEach(report.warnings, id: \.self) { Text($0).font(.system(size: 11)).foregroundStyle(quiet) }
                        if !store.portIssues.isEmpty {
                            Text("端口检查").font(.system(size: 12, weight: .semibold))
                            portRows
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }.frame(maxHeight: 270)
            }
            HStack {
                if store.canUndo { Button("撤销本次同步") { Task { await store.synchronize(undo: true) } }.modifier(WakeButton()).disabled(store.syncing) }
                Spacer()
                Button("完成", action: dismissSheet).modifier(WakeButton(prominent: true)).keyboardShortcut(.defaultAction)
            }
        }
        .padding(24).frame(width: 490)
    }

    private var portReview: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("端口检查").font(.system(size: 21, weight: .semibold))
            Text("已运行的产品会继续使用当前端口。可切换的产品在唤醒前会再确认端口是否空闲。")
                .font(.system(size: 12)).foregroundStyle(quiet)
            ScrollView {
                VStack(alignment: .leading, spacing: 12) { portRows }
                    .frame(maxWidth: .infinity, alignment: .leading)
            }.frame(maxHeight: 320)
            HStack {
                Spacer()
                Button("完成", action: dismissSheet).modifier(WakeButton(prominent: true)).keyboardShortcut(.defaultAction)
            }
        }
        .padding(24).frame(width: 490)
    }

    private var portRows: some View {
        ForEach(store.portIssues) { issue in
            VStack(alignment: .leading, spacing: 5) {
                Text(String(issue.port)).font(.system(size: 13, weight: .semibold, design: .monospaced))
                if issue.products.count > 1 {
                    Text("共用配置 · \(issue.products.joined(separator: "、"))")
                }
                if !issue.blocked.isEmpty {
                    Text("当前被占用 · 影响 \(issue.blocked.joined(separator: "、"))")
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
                    .modifier(WakeButton(width: 34)).accessibilityLabel("关闭详情").keyboardShortcut(.cancelAction)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    StatusLabel(product: current)
                    Text(current.reason).font(.system(size: 12)).foregroundStyle(quiet).fixedSize(horizontal: false, vertical: true)
                    Divider()
                    row("部署位置", current.root)
                    row("服务端口", current.portText)
                    if let url = current.url { row("本机地址", url) }
                    if let portNote = current.port_note { row("端口检测", portNote) }
                    if !current.pids.isEmpty { row("进程", current.pids.map(String.init).joined(separator: ", ")) }
                    if !current.checks.isEmpty {
                        Divider()
                        Text("部署检查").font(.system(size: 12, weight: .semibold))
                        ForEach(Array(current.checks.enumerated()), id: \.offset) { _, check in
                            Label(check.ok ? check.label : "\(check.label) · 未找到", systemImage: check.ok ? "checkmark" : "exclamationmark.circle")
                                .font(.system(size: 11)).foregroundStyle(quiet).help(check.path)
                        }
                    }
                    if let note = current.note, !note.isEmpty {
                        Text(note).font(.system(size: 11)).foregroundStyle(quiet).fixedSize(horizontal: false, vertical: true)
                    }
                    if current.needs_approval == true && (current.can_start || current.can_open) {
                        Divider()
                        Text("首次操作确认").font(.system(size: 12, weight: .semibold))
                        Text("确认你信任此目录中的代码。唤醒将以你的用户权限运行以下入口；后续启动配置变化时会再次确认。")
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
                Button("在 Finder 显示") { perform("reveal") }.modifier(WakeButton())
                Button("启动日志") { perform("log") }.modifier(WakeButton())
                if current.can_stop { Button("停止服务", role: .destructive) { perform("stop") }.modifier(WakeButton()) }
                Spacer()
                if current.can_open {
                    Button(current.needs_approval == true ? "信任并打开" : "打开") {
                        Task { await store.perform(current.id, "open", autoOpen: autoOpen,
                                                  approval: current.needs_approval == true ? current.approval_fingerprint : nil) }
                    }.modifier(WakeButton(prominent: true))
                }
                else if current.can_start {
                    Button(current.needs_approval == true ? "信任并唤醒" : "唤醒") {
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
            Text(label).foregroundStyle(quiet).frame(width: 63, alignment: .leading)
            Text(value).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
        }.font(.system(size: 11))
    }

    private func perform(_ action: String) {
        Task { await store.perform(current.id, action, autoOpen: autoOpen) }
    }
}
