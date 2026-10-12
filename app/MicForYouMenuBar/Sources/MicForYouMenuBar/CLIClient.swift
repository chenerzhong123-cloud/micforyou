import Foundation

enum CLIError: LocalizedError {
    case configMissing
    case executableMissing(String)
    case commandFailed(Int32, String)
    case readTimeout(String)
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

    /// Runs the CLI. `timeout` bounds the whole process lifetime: on expiry
    /// the child is terminated and reaped before the error is thrown, so a
    /// hung read-only query can never leave the UI waiting past the deadline.
    /// It is only ever passed for read-only queries — never for workers,
    /// audio operations, or the uninstall takeover.
    func run(_ arguments: [String], timeout: TimeInterval? = nil) async throws -> Data {
        try await Task.detached(priority: .userInitiated) {
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
            process.arguments = argumentsPrefix + arguments
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
            try process.run()
            if let timeout {
                if !Self.awaitExit(of: process, timeout: timeout) {
                    process.terminate()
                    _ = Self.awaitExit(of: process, timeout: 3)
                    output.synchronizeFile()
                    let partial = (try? Data(contentsOf: outputURL)) ?? Data()
                    let detail = String(decoding: partial.suffix(400), as: UTF8.self)
                        .trimmingCharacters(in: .whitespacesAndNewlines)
                    throw CLIError.readTimeout(detail)
                }
            } else {
                process.waitUntilExit()
            }
            try output.synchronize()
            let rendered = try Data(contentsOf: outputURL)
            guard process.terminationStatus == 0 else {
                let message = String(decoding: rendered, as: UTF8.self)
                throw CLIError.commandFailed(process.terminationStatus, message)
            }
            return rendered
        }.value
    }

    /// Waits for process exit with a deadline. `waitUntilExit` itself is not
    /// cancellable, so the wait happens on a helper queue and only the wait
    /// is bounded; an exited process always satisfies later waits too.
    private static func awaitExit(of process: Process, timeout: TimeInterval) -> Bool {
        let semaphore = DispatchSemaphore(value: 0)
        DispatchQueue(label: "micforyou.cli.exit", qos: .userInitiated).async {
            process.waitUntilExit()
            semaphore.signal()
        }
        return semaphore.wait(timeout: .now() + timeout) == .success
    }
}
