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
    @Published var uninstallSheet = false
    @Published var uninstallPlan: UninstallInventory?
    @Published var uninstallKeepData = false
    @Published var uninstallRemoveDriver = false
    @Published var uninstallBusy = false
    @Published var uninstallError: String?
    /// Worker token of the registration attempt this window session started
    /// or adopted; only its own READY may present as completed.
    @Published var enrollmentAttemptToken: String?
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
            let job = try await client.run(["setup-start", "--input-device", selectedInput],
                                           as: SetupJob.self)
            setupJob = job
            enrollmentAttemptToken = job.token
            errorMessage = nil
        } catch { errorMessage = error.localizedDescription }
    }

    /// Open the registration window. An ongoing job is adopted so reopening
    /// shows its progress; a finished (possibly stale) job never blocks a new
    /// attempt — the sheet starts from the preview state instead.
    func openEnrollment() {
        if setupJob?.status == "RUNNING" {
            enrollmentAttemptToken = setupJob?.token
        } else {
            enrollmentAttemptToken = nil
        }
        enrollmentSheet = true
    }

    /// Fast setup-status polling while the registration sheet is visible; the
    /// 3-second countdown needs sub-second updates from real backend timing.
    func refreshSetup() async {
        guard let client, client.isBundled else { return }
        if let job = try? await client.run(["setup-status"], as: SetupJob.self) {
            setupJob = job
        }
    }

    // MARK: - Uninstall

    func loadUninstallPlan() async {
        guard let client else { return }
        var arguments = ["uninstall", "--plan-only"]
        if uninstallKeepData { arguments.append("--keep-data") }
        if uninstallRemoveDriver { arguments.append("--remove-driver") }
        do {
            uninstallPlan = try await client.run(arguments, as: UninstallInventory.self)
            uninstallError = nil
        } catch {
            uninstallError = error.localizedDescription
        }
    }

    func performUninstall() async {
        guard let client, !uninstallBusy else { return }
        uninstallBusy = true
        defer { uninstallBusy = false }
        do {
            // Stop tasks, delete current-user data, and write the executor plan.
            let work = FileManager.default.temporaryDirectory
                .appending(path: "micforyou-uninstall-\(UUID().uuidString)")
            try FileManager.default.createDirectory(at: work, withIntermediateDirectories: true)
            let planURL = work.appending(path: "plan.json")
            var arguments = ["uninstall", "--result", planURL.path]
            if uninstallKeepData { arguments.append("--keep-data") }
            if uninstallRemoveDriver { arguments.append("--remove-driver") }
            _ = try await client.run(arguments)

            // Copy the native executor out of the app bundle so it survives
            // the app's own deletion, then quit and let it take over.
            guard let resources = Bundle.main.resourceURL else {
                throw CLIError.executableMissing("App Resources")
            }
            let executorSource = resources.appending(path: "UninstallExecutor")
            let executor = work.appending(path: "executor")
            try FileManager.default.copyItem(at: executorSource, to: executor)
            try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: executor.path)

            let process = Process()
            process.executableURL = executor
            process.arguments = ["--plan", planURL.path]
            process.standardInput = FileHandle.nullDevice
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
            process.qualityOfService = .userInitiated
            try process.run()
            NSApplication.shared.terminate(nil)
        } catch {
            uninstallError = error.localizedDescription
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
