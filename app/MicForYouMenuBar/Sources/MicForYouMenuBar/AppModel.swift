import AppKit
import Foundation
import AVFoundation
import SwiftUI

enum DevicesPhase: Equatable {
    case unknown, loading, loaded, failed
}

@MainActor
final class AppModel: NSObject, ObservableObject {
    @Published var status: ProductStatus?
    @Published var devices: [AudioDevice] = []
    @Published var devicesPhase: DevicesPhase = .unknown
    @Published var devicesError: String?
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
    var isWorking: Bool { busy || setupRunning || uninstallBusy }

    private var client: CLIClient?

    override init() {
        super.init()
        do {
            client = try CLIClient.discover()
        } catch {
            errorMessage = error.localizedDescription
        }
        if CommandLine.arguments.contains("--open-settings") {
            // Measurement hook: open Settings right after launch so window
            // first-frame timing can be taken reproducibly.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
                UITiming.event("settings.openRequested", ["source": "launchFlag"])
                self?.openSettings()
            }
        }
        if let index = CommandLine.arguments.firstIndex(of: "--settings-cycles"),
           index + 1 < CommandLine.arguments.count,
           let count = Int(CommandLine.arguments[index + 1]), count > 0 {
            Task { [weak self] in
                try? await Task.sleep(for: .seconds(1.0))
                for cycle in 1...count {
                    UITiming.event("settings.cycleOpen", ["cycle": String(cycle)])
                    self?.openSettings()
                    // Leave room for parallel data loads before closing.
                    try? await Task.sleep(for: .seconds(3.5))
                    UITiming.event("settings.cycleClose", [:])
                    self?.closeSettings()
                    try? await Task.sleep(for: .seconds(0.6))
                }
                UITiming.event("settings.cyclesDone")
            }
        }
    }

    // MARK: - Settings window

    /// Centrally managed settings window (replaces the SwiftUI Settings
    /// scene, whose programmatic activation is unreliable in a menu-bar-only
    /// app and whose first-frame behavior we could not measure).
    private var settingsWindow: NSWindow?
    private var settingsWindowObservers: [NSObjectProtocol] = []
    /// Gates the settings window's polling task: the window is kept alive for
    /// instant reopening, so hiding it must also stop its 2-second refresh
    /// loop instead of silently querying in the background forever.
    @Published var settingsVisible = false

    func openSettings() {
        UITiming.event("settings.openRequested", ["source": "user"])
        settingsVisible = true
        if let window = settingsWindow {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 620, height: 610),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "MicForYou 设置"
        window.isReleasedWhenClosed = false
        window.center()
        window.delegate = self
        window.contentView = NSHostingView(rootView: SettingsView(model: self))
        settingsWindow = window
        // Window-server callbacks double as interaction-ready timing marks:
        // key window accepts input, occlusion-visible means it is composited.
        // (Block-based observers are removed when their token deallocates, so
        // the tokens must live as long as the window.)
        let center = NotificationCenter.default
        settingsWindowObservers.append(
            center.addObserver(forName: NSWindow.didBecomeKeyNotification, object: window,
                               queue: .main) { _ in UITiming.event("settings.becameKey") })
        settingsWindowObservers.append(
            center.addObserver(forName: NSWindow.didChangeOcclusionStateNotification,
                               object: window, queue: .main) { note in
                if let changed = note.object as? NSWindow,
                   changed.occlusionState.contains(.visible) {
                    UITiming.event("settings.occlusionVisible")
                }
            })
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func closeSettings() {
        settingsVisible = false
        settingsWindow?.orderOut(nil)
    }

    @Published var statusLoading = false
    private var statusInFlight = false
    private var setupInFlight = false
    private var devicesInFlight = false

    /// Parallel read-only refresh: status and setup status never wait on each
    /// other, and concurrent callers share one flight instead of stacking
    /// duplicate CLI processes.
    func refresh() async {
        guard !busy, !uninstallBusy, let client else { return }
        async let statusResult = loadStatusIfFree(client)
        async let setupResult = client.isBundled ? loadSetupIfFree(client) : nil
        let (value, job) = await (statusResult, setupResult)
        if let value {
            status = value
            if !value.inputDevice.isEmpty && !setupRunning {
                selectedInput = value.inputDevice
            }
            errorMessage = nil
        }
        if let job { setupJob = job }
    }

    private func loadStatusIfFree(_ client: CLIClient) async -> ProductStatus? {
        guard !statusInFlight else { return nil }
        statusInFlight = true
        defer { statusInFlight = false }
        statusLoading = true
        defer { statusLoading = false }
        let value = try? await client.run(["status"], as: ProductStatus.self, timeout: 5)
        if value != nil { UITiming.event("settings.statusLoaded") }
        return value
    }

    private func loadSetupIfFree(_ client: CLIClient) async -> SetupJob? {
        guard !setupInFlight else { return nil }
        setupInFlight = true
        defer { setupInFlight = false }
        let job = try? await client.run(["setup-status"], as: SetupJob.self, timeout: 5)
        if job != nil { UITiming.event("settings.setupLoaded") }
        return job
    }

    /// Devices have a distinct phase so the UI can tell "still reading" from
    /// "loaded and empty" from "failed" — never showing a fake fault while a
    /// bounded query is still in flight.
    func refreshDevices() async {
        guard let client, !uninstallBusy, !devicesInFlight else { return }
        devicesInFlight = true
        defer { devicesInFlight = false }
        devicesPhase = .loading
        devicesError = nil
        do {
            let values = try await client.run(["devices"], as: [AudioDevice].self, timeout: 5)
            driverInstalled = values.contains { $0.name == "BlackHole 2ch" }
            devices = values.filter {
                $0.maxInputChannels > 0 && !$0.name.localizedCaseInsensitiveContains("BlackHole")
            }
            if selectedInput.isEmpty { selectedInput = devices.first?.name ?? "" }
            devicesPhase = .loaded
            UITiming.event("settings.devicesLoaded")
        } catch {
            devicesPhase = .failed
            devicesError = error.localizedDescription
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
        guard !uninstallBusy else { return }
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
        guard !uninstallBusy else { return }
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
        guard let client, client.isBundled, !uninstallBusy else { return }
        if let job = try? await client.run(["setup-status"], as: SetupJob.self,
                                           timeout: 5) {
            setupJob = job
        }
    }

    // MARK: - Performance retest and trial approval

    func startRetest() async {
        guard let client, !isWorking, !uninstallBusy else { return }
        busy = true
        defer { busy = false }
        do {
            setupJob = try await client.run(["setup-retest"], as: SetupJob.self)
            enrollmentAttemptToken = setupJob?.token
            enrollmentSheet = true
            errorMessage = nil
        } catch { errorMessage = error.localizedDescription }
    }

    func approveTrial() async {
        guard let client, !isWorking, !uninstallBusy else { return }
        busy = true
        defer { busy = false }
        do {
            _ = try await client.run(["setup-approve"])
            if let job = try? await client.run(["setup-status"], as: SetupJob.self,
                                               timeout: 5) {
                setupJob = job
            }
            errorMessage = nil
        } catch { errorMessage = error.localizedDescription }
    }

    // MARK: - Doubao setup guide

    private var guideWindow: NSWindow?

    func openDoubaoGuide() {
        if let window = guideWindow {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 640, height: 560),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "设置豆包语音输入"
        window.isReleasedWhenClosed = false
        window.center()
        window.contentView = NSHostingView(rootView: DoubaoGuideView(model: self))
        guideWindow = window
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func closeDoubaoGuide() {
        guideWindow?.orderOut(nil)
    }

    func openSystemSoundSettings() {
        let urls = [
            URL(string: "x-apple.systempreferences:com.apple.Sound-Settings"),
            URL(string: "x-apple.systempreferences:com.apple.sound-settings"),
        ].compactMap { $0 }
        for url in urls {
            if NSWorkspace.shared.open(url) { return }
        }
        NSWorkspace.shared.open(URL(fileURLWithPath: "/System/Applications/System Settings.app"))
    }

    // MARK: - Uninstall

    func loadUninstallPlan() async {
        guard let client, !uninstallBusy else { return }
        var arguments = ["uninstall", "--plan-only"]
        if uninstallKeepData { arguments.append("--keep-data") }
        if uninstallRemoveDriver { arguments.append("--remove-driver") }
        do {
            uninstallPlan = try await client.run(arguments, as: UninstallInventory.self,
                                                 timeout: 5)
            uninstallError = nil
        } catch {
            uninstallError = error.localizedDescription
        }
    }

    func performUninstall() async {
        guard let client, !busy, !uninstallBusy else { return }
        uninstallBusy = true
        defer { uninstallBusy = false }
        let work = FileManager.default.temporaryDirectory
            .appending(path: "micforyou-uninstall-\(UUID().uuidString)")
        var executorProcess: Process?
        var handedOff = false
        defer {
            if !handedOff { try? FileManager.default.removeItem(at: work) }
        }
        do {
            try FileManager.default.createDirectory(at: work, withIntermediateDirectories: true,
                                                     attributes: [.posixPermissions: 0o700])
            guard let resources = Bundle.main.resourceURL else {
                throw CLIError.executableMissing("App Resources")
            }
            let executor = work.appending(path: "executor")
            try FileManager.default.copyItem(at: resources.appending(path: "UninstallExecutor"), to: executor)
            try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: executor.path)
            var options: [String] = []
            if uninstallKeepData { options.append("--keep-data") }
            if uninstallRemoveDriver { options.append("--remove-driver") }
            let initial = work.appending(path: "inventory.json")
            let final = work.appending(path: "plan.json")
            _ = try await client.run(["uninstall", "--plan-only", "--result", initial.path] + options)
            let process = Process()
            process.executableURL = executor
            process.arguments = ["--prepare-plan", initial.path, "--plan", final.path,
                                 "--parent-pid", String(ProcessInfo.processInfo.processIdentifier)]
            process.standardInput = FileHandle.nullDevice
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
            try process.run()
            executorProcess = process
            let deadline = Date().addingTimeInterval(130)
            while !FileManager.default.fileExists(atPath: work.appending(path: "ready").path) {
                guard process.isRunning, Date() < deadline else {
                    let detail = (try? String(contentsOf: work.appending(path: "error"), encoding: .utf8))
                        ?? "卸载执行器未就绪或授权取消；未删除个人数据。"
                    throw NSError(domain: "MicForYou.Uninstall", code: 1,
                                  userInfo: [NSLocalizedDescriptionKey: detail])
                }
                try await Task.sleep(for: .milliseconds(100))
            }
            _ = try await client.run(["uninstall", "--result", final.path,
                                      "--executor-pid", String(process.processIdentifier),
                                      "--executor-path", executor.path] + options)
            guard process.isRunning else {
                throw NSError(domain: "MicForYou.Uninstall", code: 2,
                              userInfo: [NSLocalizedDescriptionKey: "执行器接管失败；未删除个人数据。"])
            }
            handedOff = true
            NSApplication.shared.terminate(nil)
        } catch {
            try? Data().write(to: work.appending(path: "abort"), options: .atomic)
            if let process = executorProcess {
                let deadline = Date().addingTimeInterval(5)
                while process.isRunning && Date() < deadline {
                    try? await Task.sleep(for: .milliseconds(100))
                }
                if process.isRunning { process.terminate() }
            }
            // Startup remains frozen until the executor has stopped waiting.
            if let process = executorProcess {
                _ = try? await client.run(["uninstall", "--abort", "--executor-pid", String(process.processIdentifier)])
            }
            uninstallError = error.localizedDescription
        }
    }

    func cancelSetup() async {
        guard let client, setupRunning, !uninstallBusy else { return }
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

extension AppModel: NSWindowDelegate {
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        closeSettings()
        return true
    }
}
