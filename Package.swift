// swift-tools-version: 5.10
import PackageDescription
let package = Package(
    name: "Wake",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "Wake", targets: ["WakeApp"])],
    targets: [.executableTarget(name: "WakeApp")]
)
