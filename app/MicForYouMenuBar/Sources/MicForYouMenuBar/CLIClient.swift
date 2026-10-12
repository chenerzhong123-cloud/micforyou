import Foundation

enum CLIError: LocalizedError {
    case configMissing
    case executableMissing(String)
    case commandFailed(Int32, String)
    case readTimeout(String)
    case unstoppable(Int32)
    case invalidOutput(String)

    var errorDescription: String? {
        switch self {
        case .configMissing:
            "尚未找到 MicForYou 配置。请先完成 configure。"
        case let .executableMissing(path):
            "找不到控制程序：\(path)。请在项目目录运行 uv sync。"
        case let .commandFailed(code, message):
            "命令失败（\(code)）：\(message)"
        case let .readTimeout(detail):
            detail.isEmpty
                ? "控制程序查询超时，已停止该查询；请稍后重试。"
                : "控制程序查询超时，已停止该查询：\(detail)"
        case let .unstoppable(pid):
            "控制程序查询（PID \(pid)）超时且强制终止无效，请联系支持。"
        case let .invalidOutput(message):
            "无法读取控制程序输出：\(message)"
        }
    }
}

struct SavedConfig: Decodable {
    let projectRoot: String

    enum CodingKeys: String, CodingKey {
        case projectRoot = "project_root"
    }
}

struct CLIClient: Sendable {
    let executable: URL
    let projectRoot: URL
    var argumentsPrefix: [String] = []
    var isBundled: Bool { !argumentsPrefix.isEmpty }

    static func discover(resourceURL: URL? = Bundle.main.resourceURL) throws -> CLIClient {
        if let resources = resourceURL {
            let root = resources.appending(path: "Runtime")
            let python = root.appending(path: "python/bin/python3.12")
            let bootstrap = root.appending(path: "bootstrap.py")
            if FileManager.default.fileExists(atPath: root.appending(path: "bundle-manifest.json").path) {
                guard FileManager.default.isExecutableFile(atPath: python.path),
                      FileManager.default.fileExists(atPath: bootstrap.path) else {
                    throw CLIError.executableMissing(python.path)
                }
                return CLIClient(executable: python, projectRoot: root,
                                 argumentsPrefix: ["-E", "-s", "-B", bootstrap.path])
            }
        }
        let support = FileManager.default.homeDirectoryForCurrentUser
            .appending(path: "Library/Application Support/MicForYou")
        let configURL = support.appending(path: "config.json")
        guard let data = try? Data(contentsOf: configURL) else {
            throw CLIError.configMissing
        }
        let config = try JSONDecoder().decode(SavedConfig.self, from: data)
        let root = URL(filePath: config.projectRoot, directoryHint: .isDirectory)
        let executable = root.appending(path: ".venv/bin/micforyou")
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw CLIError.executableMissing(executable.path)
        }
        return CLIClient(executable: executable, projectRoot: root)
    }

    func run<T: Decodable & Sendable>(
        _ arguments: [String],
        as type: T.Type,
        timeout: TimeInterval? = nil
    ) async throws -> T {
        let data = try await run(arguments, timeout: timeout)
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            let rendered = String(decoding: data, as: UTF8.self)
            throw CLIError.invalidOutput("\(error.localizedDescription)\n\(rendered)")
        }
    }

    /// Runs the CLI. `timeout` bounds the whole process lifecycle for
    /// read-only queries only — never for workers, audio operations, or the
    /// uninstall takeover, which keep their own lifecycle rules. On timeout
    /// or caller cancellation the child is asked to quit, then after a short
    /// grace killed, and only a reaped child lets us report "stopped".
    func run(_ arguments: [String], timeout: TimeInterval? = nil) async throws -> Data {
        let controller = CLIProcessController()
        return try await withTaskCancellationHandler {
            try await Task.detached(priority: .userInitiated) {
                try Self.runOne(controller: controller, executable: executable,
                                arguments: argumentsPrefix + arguments,
                                projectRoot: projectRoot, isBundled: isBundled,
                                timeout: timeout)
            }.value
        } onCancel: {
            controller.requestStop(cancelledByCaller: true)
        }
    }

    private static func runOne(controller: CLIProcessController, executable: URL,
                               arguments: [String], projectRoot: URL,
                               isBundled: Bool, timeout: TimeInterval?) throws -> Data {
        let process = Process()
        let outputURL = FileManager.default.temporaryDirectory
            .appending(path: "micforyou-ui-\(UUID().uuidString).log")
        FileManager.default.createFile(atPath: outputURL.path, contents: nil)
        let output = try FileHandle(forWritingTo: outputURL)
        defer {
            try? output.close()
            try? FileManager.default.removeItem(at: outputURL)
        }
        process.executableURL = executable
        process.arguments = arguments
        var environment = ProcessInfo.processInfo.environment
        environment.removeValue(forKey: "PYTHONHOME")
        environment.removeValue(forKey: "PYTHONPATH")
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        if isBundled {
            environment["MICFORYOU_BUNDLE_ROOT"] = projectRoot.path
        }
        process.environment = environment
        process.currentDirectoryURL = projectRoot
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = output
        process.standardError = output
        do {
            try process.run()
        } catch {
            throw CLIError.executableMissing(executable.path)
        }
        controller.attach(process: process)

        controller.waitUntil(deadline: timeout.map { Date().addingTimeInterval($0) })
        if process.isRunning {
            // Timeout (or caller cancellation): graceful quit, one-second
            // grace, then SIGKILL. The overall return time includes the
            // grace, and "stopped" is only claimed once the child is reaped.
            controller.requestStop(cancelledByCaller: false)
        }
        if process.isRunning {
            controller.escalateToKill(process)
        }
        if process.isRunning {
            // Unreachable after SIGKILL, but never claim a stop we did not
            // achieve.
            throw CLIError.unstoppable(process.processIdentifier)
        }
        try output.synchronize()
        let rendered = try Data(contentsOf: outputURL)
        if let stopped = controller.takeStopReason() {
            switch stopped {
            case .cancelled:
                throw CancellationError()
            case .timedOut:
                let detail = String(decoding: rendered.suffix(400), as: UTF8.self)
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                throw CLIError.readTimeout(detail)
            }
        }
        guard process.terminationStatus == 0 else {
            let message = String(decoding: rendered, as: UTF8.self)
            throw CLIError.commandFailed(process.terminationStatus, message)
        }
        return rendered
    }
}

/// Owns one CLI child process and its bounded lifecycle. All state is
/// guarded by a lock because the cancellation handler can fire from any
/// thread the moment the surrounding task is cancelled.
final class CLIProcessController: @unchecked Sendable {
    enum StopReason { case timedOut, cancelled }

    private let lock = NSLock()
    private var process: Process?
    private var stopReason: StopReason?
    private var deadline: Date?

    func attach(process: Process) {
        lock.lock()
        self.process = process
        let pending = stopReason
        lock.unlock()
        if pending != nil {
            process.terminate()
        }
    }

    /// Graceful stop entry point, shared by timeout expiry and caller
    /// cancellation. The first reason wins; the run loop escalates to kill
    /// if SIGTERM is ignored.
    func requestStop(cancelledByCaller: Bool) {
        lock.lock()
        if stopReason == nil {
            stopReason = cancelledByCaller ? .cancelled : .timedOut
        }
        let process = self.process
        lock.unlock()
        process?.terminate()
    }

    func takeStopReason() -> StopReason? {
        lock.lock()
        defer { lock.unlock() }
        return stopReason
    }

    /// Polls for exit in small slices so that a cancellation request or the
    /// deadline is noticed promptly (DispatchSemaphore waits are not
    /// cancellable; polling with RunLoop slices keeps the helper responsive).
    func waitUntil(deadline: Date?) {
        lock.lock()
        self.deadline = deadline
        lock.unlock()
        while true {
            lock.lock()
            let process = self.process
            let reason = stopReason
            let limit = self.deadline
            lock.unlock()
            guard let process else { return }
            if !process.isRunning { return }
            if reason != nil { return }
            if let limit, Date() >= limit { return }
            RunLoop.current.run(until: Date().addingTimeInterval(0.02))
        }
    }

    func escalateToKill(_ process: Process) {
        process.terminate()
        let grace = Date().addingTimeInterval(1.0)
        while process.isRunning && Date() < grace {
            RunLoop.current.run(until: Date().addingTimeInterval(0.02))
        }
        if process.isRunning {
            kill(process.processIdentifier, SIGKILL)
            let hard = Date().addingTimeInterval(2.0)
            while process.isRunning && Date() < hard {
                RunLoop.current.run(until: Date().addingTimeInterval(0.02))
            }
        }
    }
}
