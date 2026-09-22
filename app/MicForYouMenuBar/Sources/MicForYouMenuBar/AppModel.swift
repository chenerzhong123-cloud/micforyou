import AppKit
import Foundation

@MainActor
final class AppModel: ObservableObject {
    @Published var status: ProductStatus?
    @Published var devices: [AudioDevice] = []
    @Published var selectedInput = ""
    @Published var busy = false
    @Published var errorMessage: String?

    private var client: CLIClient?

    init() {
        do {
            client = try CLIClient.discover()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func refresh() async {
        guard !busy, let client else { return }
        do {
            let value = try await client.run(["status"], as: ProductStatus.self)
            status = value
            selectedInput = value.inputDevice
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func refreshDevices() async {
        guard let client else { return }
        do {
            let values = try await client.run(["devices"], as: [AudioDevice].self)
            devices = values.filter {
                $0.maxInputChannels > 0 && !$0.name.localizedCaseInsensitiveContains("BlackHole")
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func perform(_ command: String) async {
        guard let client, !busy else { return }
        busy = true
        defer { busy = false }
        do {
            _ = try await client.run([command])
            errorMessage = nil
            await refreshAfterAction(client)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func changeInput() async {
        guard let client, !busy, !selectedInput.isEmpty else { return }
        busy = true
        defer { busy = false }
        do {
            _ = try await client.run(["set-input", selectedInput])
            errorMessage = nil
            await refreshAfterAction(client)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func openLog() {
        guard let path = status?.runtime.logPath else { return }
        NSWorkspace.shared.open(URL(filePath: path))
    }

    private func refreshAfterAction(_ client: CLIClient) async {
        try? await Task.sleep(for: .milliseconds(250))
        do {
            let value = try await client.run(["status"], as: ProductStatus.self)
            status = value
            selectedInput = value.inputDevice
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
