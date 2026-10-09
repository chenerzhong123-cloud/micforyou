import Foundation

enum CLIError: LocalizedError {
    case configMissing
    case executableMissing(String)
    case commandFailed(Int32, String)
    case invalidOutput(String)

    var errorDescription: String? {
        switch self {
        case .configMissing:
            "尚未找到 MicForYou 配置。请先完成 configure。"
        case let .executableMissing(path):
            "找不到控制程序：\(path)。请在项目目录运行 uv sync。"
        case let .commandFailed(code, message):
            "命令失败（\(code)）：\(message)"
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
        as type: T.Type
    ) async throws -> T {
        let data = try await run(arguments)
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            let rendered = String(decoding: data, as: UTF8.self)
            throw CLIError.invalidOutput("\(error.localizedDescription)\n\(rendered)")
        }
    }

    func run(_ arguments: [String]) async throws -> Data {
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
            process.waitUntilExit()
            try output.synchronize()
            let rendered = try Data(contentsOf: outputURL)
            guard process.terminationStatus == 0 else {
                let message = String(decoding: rendered, as: UTF8.self)
                throw CLIError.commandFailed(process.terminationStatus, message)
            }
            return rendered
        }.value
    }
}
