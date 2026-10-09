import Foundation

@main
struct StandaloneCheck {
    static func main() async throws {
        guard CommandLine.arguments.count == 2 else {
            fatalError("Usage: standalone-check /path/to/MicForYou.app")
        }
        let app = URL(filePath: CommandLine.arguments[1])
        let client = try CLIClient.discover(resourceURL: app.appending(path: "Contents/Resources"))
        precondition(client.isBundled)
        let folder = FileManager.default.temporaryDirectory.appending(path: "micforyou-first-use-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: folder) }
        let config = folder.appending(path: "config.json")
        let value = try await client.run(["status", "--config", config.path], as: ProductStatus.self)
        precondition(!value.ready)
        precondition(value.inputDevice.isEmpty)
        precondition(value.runtime.effectiveStatus == "STOPPED")
        let job = try await client.run(["setup-status", "--config", config.path], as: SetupJob.self)
        precondition(job.status == "IDLE")
        print("Swift bundled CLI + first-use status PASS")
    }
}
