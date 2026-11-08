import Foundation
import Darwin

struct WakeError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

/// A single child process for the lifetime of the application. All control messages use inherited pipes.
// The serial queue owns the process, file handles, buffer and pending requests.
final class ServiceBridge: @unchecked Sendable {
    let dataDirectory: URL
    private let resources: URL
    private let queue = DispatchQueue(label: "dev.wake.launcher.pipe")
    private var process: Process?
    private var input: FileHandle?
    private var output: FileHandle?
    private var reader: DispatchSourceRead?
    private var diagnostics: FileHandle?
    private var buffer = Data()
    private var callbacks: [String: (Result<Data, Error>) -> Void] = [:]
    private var closed = false

    init(resources: URL, dataDirectory: URL) {
        self.resources = resources
        self.dataDirectory = dataDirectory
    }

    func request<T: Decodable>(_ method: String, parameters: [String: Any] = [:],
                               language: WakeLanguage = .current, as type: T.Type) async throws -> T {
        let requestID = UUID().uuidString
        var message = try JSONSerialization.data(withJSONObject: [
            "id": requestID, "method": method, "params": parameters, "language": language.rawValue
        ])
        message.append(10)
        let request = message
        let result: Data = try await withCheckedThrowingContinuation { continuation in
            queue.async { [self] in
                do {
                    guard !self.closed else { throw WakeError(message: l("Wake has quit.", language: language)) }
                    if self.process?.isRunning != true { try self.start() }
                    guard let input = self.input else { throw WakeError(message: l("The local engine is unavailable. Try refreshing.", language: language)) }
                    self.callbacks[requestID] = { continuation.resume(with: $0) }
                    try input.write(contentsOf: request)
                    let timeout: TimeInterval = method == "sync" ? 90 : 45
                    self.queue.asyncAfter(deadline: .now() + timeout) { [weak self] in
                        self?.callbacks.removeValue(forKey: requestID)?(.failure(WakeError(message: l("The local operation timed out. Try refreshing.", language: language))))
                    }
                } catch {
                    if let callback = self.callbacks.removeValue(forKey: requestID) {
                        callback(.failure(error))
                        self.disconnect(l("The local connection was lost. Refresh to reconnect."))
                    }
                    else { continuation.resume(throwing: error) }
                }
            }
        }
        return try JSONDecoder().decode(type, from: result)
    }

    private func start() throws {
        disconnect(l("The local connection was reset. Try refreshing."))
        let fm = FileManager.default
        try fm.createDirectory(at: dataDirectory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let log = dataDirectory.appendingPathComponent("Wake.log")
        if !fm.fileExists(atPath: log.path) { fm.createFile(atPath: log.path, contents: nil, attributes: [.posixPermissions: 0o600]) }
        diagnostics = try FileHandle(forWritingTo: log)
        try diagnostics?.seekToEnd()
        let child = Process()
        child.executableURL = resources.appendingPathComponent("Python/bin/python3.12")
        child.arguments = ["-I", "-S", "-B", "-u", resources.appendingPathComponent("Core/ipc.py").path,
                           "--data-dir", dataDirectory.path, "--seed", resources.appendingPathComponent("products.seed.json").path,
                           "--migration", resources.appendingPathComponent("migration.json").path]
        child.currentDirectoryURL = dataDirectory
        var environment = ProcessInfo.processInfo.environment
        let localBin = fm.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin").path
        environment["PATH"] = "\(localBin):/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        child.environment = environment
        let incoming = Pipe(), outgoing = Pipe()
        child.standardInput = incoming
        child.standardOutput = outgoing
        child.standardError = diagnostics
        let outputHandle = outgoing.fileHandleForReading
        buffer.removeAll(keepingCapacity: true)
        try child.run()
        input = incoming.fileHandleForWriting
        output = outputHandle
        process = child
        let source = DispatchSource.makeReadSource(fileDescriptor: outputHandle.fileDescriptor, queue: queue)
        source.setEventHandler { [weak self, weak outputHandle] in
            guard let self, let handle = outputHandle, self.output === handle else { return }
            var bytes = [UInt8](repeating: 0, count: 65_536)
            let length = Darwin.read(handle.fileDescriptor, &bytes, bytes.count)
            if length > 0 {
                self.consume(Data(bytes.prefix(length)))
            } else if length == 0 || errno != EINTR {
                self.disconnect(l("The local engine stopped. Refresh to reconnect."))
            }
        }
        source.setCancelHandler { try? outputHandle.close() }
        reader = source
        source.resume()
    }

    private func consume(_ data: Data) {
        buffer.append(data)
        guard buffer.count <= 8 * 1024 * 1024 else {
            disconnect(l("The local response was too large. Try refreshing."))
            return
        }
        while let end = buffer.firstIndex(of: 10) {
            let line = Data(buffer[..<end])
            buffer.removeSubrange(...end)
            guard let decoded = try? JSONSerialization.jsonObject(with: line) as? [String: Any],
                  let id = decoded["id"] as? String else {
                disconnect(l("The local response could not be read. Try refreshing."))
                return
            }
            guard let callback = callbacks.removeValue(forKey: id) else { continue }
            if decoded["ok"] as? Bool == true, let result = decoded["result"],
               let encoded = try? JSONSerialization.data(withJSONObject: result) {
                callback(.success(encoded))
            } else {
                callback(.failure(WakeError(message: decoded["error"] as? String ?? l("The local operation did not finish."))))
            }
        }
    }

    private func failPending(_ message: String) {
        let pending = callbacks
        callbacks.removeAll()
        for callback in pending.values { callback(.failure(WakeError(message: message))) }
    }

    private func disconnect(_ message: String) {
        if let reader { reader.cancel() }
        else { try? output?.close() }
        reader = nil
        try? input?.close()
        failPending(message)
        input = nil
        output = nil
        process = nil
        buffer.removeAll(keepingCapacity: true)
        try? diagnostics?.close()
        diagnostics = nil
    }

    func close() {
        queue.sync {
            // EOF lets accepted startup tasks finish before the controller exits.
            // Product processes already have detached sessions and their own logs.
            closed = true
            disconnect(l("Wake has quit."))
        }
    }
}
