import AppKit
import Foundation
import AVFoundation

@MainActor
final class AppModel: ObservableObject {
    @Published var status: ProductStatus?
    @Published var devices: [AudioDevice] = []
    @Published var selectedInput = ""
    @Published var busy = false
    @Published var errorMessage: String?
    @Published var enrollmentSheet = false
    @Published var confirmCloseEnrollment = false
    @Published var setupJob: SetupJob?
    @Published var driverInstalled = false
    var isBundled: Bool { client?.isBundled == true }
    var setupRunning: Bool { setupJob?.status == "RUNNING" }
    var isWorking: Bool { busy || setupRunning }

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
            if !value.inputDevice.isEmpty && !setupRunning { selectedInput = value.inputDevice }
            if client.isBundled {
                setupJob = try await client.run(["setup-status"], as: SetupJob.self)
            }
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func refreshDevices() async {
        guard let client else { return }
        do {
            let values = try await client.run(["devices"], as: [AudioDevice].self)
            driverInstalled = values.contains { $0.name == "BlackHole 2ch" }
            devices = values.filter {
                $0.maxInputChannels > 0 && !$0.name.localizedCaseInsensitiveContains("BlackHole")
            }
            if selectedInput.isEmpty { selectedInput = devices.first?.name ?? "" }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func perform(_ command: String) async {
        guard let client, !isWorking else { return }
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

    func enrollVoice() async {
        guard let client, !isWorking else { return }
        guard await AVCaptureDevice.requestAccess(for: .audio) else {
            errorMessage = "请在系统设置 → 隐私与安全性 → 麦克风中允许 MicForYou 使用麦克风。"
            return
        }
        if !client.isBundled {
            await perform("enroll")
            return
        }
        busy = true
        defer { busy = false }
        do {
            setupJob = try await client.run(["setup-start", "--input-device", selectedInput],
                                             as: SetupJob.self)
            errorMessage = nil
        } catch { errorMessage = error.localizedDescription }
    }

    /// Fast setup-status polling while the registration sheet is visible; the
    /// 3-second countdown needs sub-second updates from real backend timing.
    func refreshSetup() async {
        guard let client, client.isBundled else { return }
        if let job = try? await client.run(["setup-status"], as: SetupJob.self) {
            setupJob = job
        }
    }

    func cancelSetup() async {
        guard let client, setupRunning else { return }
        do { _ = try await client.run(["setup-cancel"]) }
        catch { errorMessage = error.localizedDescription }
    }

    func openDriverGuide() {
        if let root = Bundle.main.resourceURL {
            let installer = root.appending(path: "Installers/BlackHole2ch-0.7.1.pkg")
            if FileManager.default.fileExists(atPath: installer.path) {
                NSWorkspace.shared.open(installer)
                return
            }
        }
        NSWorkspace.shared.open(URL(string: "https://existential.audio/blackhole/")!)
    }

    func openLicenses() {
        guard let root = Bundle.main.resourceURL else { return }
        NSWorkspace.shared.open(root.appending(path: "Runtime/licenses/MODEL_NOTICES.md"))
    }

    func changeInput() async {
        guard let client, !isWorking, !selectedInput.isEmpty else { return }
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
