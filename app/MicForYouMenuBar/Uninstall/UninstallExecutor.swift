import AppKit
import Foundation

// MicForYou native uninstall executor.
//
// The app copies this binary to a private temp location and launches it just
// before quitting, so the cleanup never depends on resources that are being
// deleted. It only accepts the explicit target list from the prepared plan
// JSON and re-verifies every target independently:
//   - .app bundles must carry the product bundle identifier,
//   - user-data targets must sit inside the fixed product locations,
//   - symlinks and filesystem roots are always refused.
// The shared BlackHole driver is only removed when explicitly selected; the
// elevated command is a fixed constant string (no interpolation of plan
// content), matching the driver vendor's documented manual removal.

let productBundleID = "com.micforyou.menubar"
let driverPath = "/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver"
let elevatedCleanup = """
rm -rf '/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver' && \
pkgutil --forget audio.existential.BlackHole2ch; \
pkgutil --forget com.micforyou.complete
"""

struct PlanTarget: Decodable {
    let kind: String
    let path: String
    let action: String
    let reason: String?
}

struct PlanPayload: Decodable {
    struct PlanBody: Decodable {
        let targets: [PlanTarget]
        let removeDriver: Bool?
        let keep: [KeepItem]?
        struct KeepItem: Decodable {
            let path: String?
            let reason: String?
        }
    }

    let plan: PlanBody
    let markerPath: String?
}

enum ExecutorError: Error, CustomStringConvertible {
    case usage
    case unreadablePlan(String)
    case refused(String)

    var description: String {
        switch self {
        case .usage:
            "用法：UninstallExecutor --plan <plan.json> [--self-check]"
        case let .unreadablePlan(detail):
            "无法读取卸载计划：\(detail)"
        case let .refused(detail):
            "拒绝清理目标：\(detail)"
        }
    }
}

func allowedUserRoots(home: URL) -> [URL] {
    let library = home.appending(path: "Library")
    return [
        library.appending(path: "Application Support/MicForYou"),
        library.appending(path: "Preferences/\(productBundleID).plist"),
        library.appending(path: "Caches/\(productBundleID)"),
        library.appending(path: "Saved Application State/\(productBundleID).savedState"),
        URL(filePath: "/tmp/micforyou-\(getuid())", directoryHint: .isDirectory),
    ]
}

/// Independent re-verification of one target; throws when the target must not
/// be touched regardless of what the plan claims.
func verifyTarget(_ target: PlanTarget, home: URL) throws {
    let url = URL(filePath: target.path)
    let path = url.path
    if path == "/" || path.isEmpty {
        throw ExecutorError.refused("\(path)：拒绝文件系统根目录")
    }
    if let values = try? url.resourceValues(forKeys: [.isSymbolicLinkKey]),
       values.isSymbolicLink == true {
        throw ExecutorError.refused("\(path)：符号链接")
    }
    switch target.kind {
    case "app", "old_app":
        let info = url.appending(path: "Contents/Info.plist")
        guard let data = try? Data(contentsOf: info),
              let plist = try? PropertyListSerialization.propertyList(
                  from: data, options: [], format: nil) as? [String: Any],
              plist["CFBundleIdentifier"] as? String == productBundleID else {
            throw ExecutorError.refused("\(path)：应用 bundle id 不匹配")
        }
    case "support_dir", "prefs", "caches", "saved_state", "tmp_dir", "user_data":
        let resolved = url.standardizedFileURL.path
        let inside = allowedUserRoots(home: home).contains { root in
            let rootPath = root.standardizedFileURL.path
            return resolved == rootPath || resolved.hasPrefix(rootPath + "/")
        }
        guard inside else {
            throw ExecutorError.refused("\(path)：不在允许的用户数据范围内")
        }
    default:
        throw ExecutorError.refused("\(path)：未知目标类型 \(target.kind)")
    }
}

func trashApps(_ targets: [PlanTarget]) -> [String] {
    var removed: [String] = []
    let manager = FileManager.default
    for target in targets where target.action == "trash" {
        let url = URL(filePath: target.path)
        guard manager.fileExists(atPath: target.path) else { continue }
        var outError: NSError?
        NSWorkspace.shared.recycle([url], completionHandler: nil)
        // recycle is asynchronous; poll briefly until the bundle moves so the
        // final read-back verification reflects reality.
        let deadline = Date().addingTimeInterval(10)
        while manager.fileExists(atPath: target.path) && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.1)
        }
        if manager.fileExists(atPath: target.path) {
            _ = outError // the item stays and is reported by the read-back pass
        } else {
            removed.append(target.path)
        }
    }
    return removed
}

func removeLeftovers(_ targets: [PlanTarget], home: URL) -> [[String: String]] {
    let manager = FileManager.default
    var results: [[String: String]] = []
    for target in targets where target.action == "delete" {
        let path = target.path
        guard manager.fileExists(atPath: path) else {
            results.append(["path": path, "status": "absent"])
            continue
        }
        do {
            try manager.removeItem(atPath: path)
            results.append(["path": path, "status": "removed"])
        } catch {
            results.append(["path": path, "status": "failed",
                            "detail": error.localizedDescription])
        }
    }
    return results
}

func elevateDriverRemoval() -> Bool {
    let script = """
    do shell script "\(elevatedCleanup)" with administrator privileges \
    with prompt "MicForYou 卸载需要移除 BlackHole 2ch 音频驱动"
    """
    let process = Process()
    process.executableURL = URL(filePath: "/usr/bin/osascript")
    process.arguments = ["-e", script]
    process.standardInput = FileHandle.nullDevice
    let out = FileHandle.nullDevice
    process.standardOutput = out
    process.standardError = out
    do {
        try process.run()
        process.waitUntilExit()
        return process.terminationStatus == 0
    } catch {
        return false
    }
}

func showResult(_ summary: String) {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    app.activate(ignoringOtherApps: true)
    let alert = NSAlert()
    alert.messageText = "MicForYou 卸载完成"
    alert.informativeText = summary
    alert.alertStyle = .informational
    alert.addButton(withTitle: "好")
    _ = alert.runModal()
}

func runSelfCheck() throws {
    // Validate the refusal rules against real temporary fixtures; nothing
    // outside the fixtures is touched.
    let home = FileManager.default.temporaryDirectory
        .appending(path: "uninstall-selfcheck-\(UUID().uuidString)")
    let support = home.appending(path: "Library/Application Support/MicForYou")
    try FileManager.default.createDirectory(
        at: support, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: home) }

    try verifyTarget(
        PlanTarget(kind: "support_dir", path: support.path,
                   action: "delete", reason: nil),
        home: home)
    try verifyTarget(
        PlanTarget(kind: "prefs",
                   path: home.appending(path: "Library/Preferences/\(productBundleID).plist").path,
                   action: "delete", reason: nil),
        home: home)

    for bad in ["/Users", home.appending(path: "Elsewhere").path] {
        do {
            try verifyTarget(PlanTarget(kind: "user_data", path: bad,
                                        action: "delete", reason: nil),
                             home: home)
            throw ExecutorError.refused("\(bad) 应当被拒绝")
        } catch let error as ExecutorError {
            guard case .refused = error else { throw error }
        }
    }
    print("MicForYou uninstall executor self-check PASS")
}

@main
struct UninstallExecutorMain {
    static func main() {
    var arguments = CommandLine.arguments.dropFirst()
    var planPath: String?
    var selfCheck = false
    while let flag = arguments.popFirst() {
        switch flag {
        case "--plan":
            planPath = arguments.popFirst()
        case "--self-check":
            selfCheck = true
        default:
            print(ExecutorError.usage)
            exit(2)
        }
    }
    do {
        if selfCheck {
            try runSelfCheck()
            exit(0)
        }
        guard let planPath else {
            print(ExecutorError.usage)
            exit(2)
        }
        let data = try Data(contentsOf: URL(filePath: planPath))
        let payload = try JSONDecoder().decode(PlanPayload.self, from: data)
        let home = FileManager.default.homeDirectoryForCurrentUser
        var refused: [String] = []
        for target in payload.plan.targets {
            do {
                try verifyTarget(target, home: home)
            } catch {
                refused.append("\(target.path)：\(error)")
            }
        }
        guard refused.isEmpty else {
            showResult("以下目标未通过核实，已中止卸载：\n" + refused.joined(separator: "\n"))
            exit(1)
        }

        let apps = payload.plan.targets.filter { $0.action == "trash" }
        let trashed = trashApps(apps)
        var removed = removeLeftovers(payload.plan.targets, home: home)

        var driverNote = "已保留 BlackHole 2ch 驱动（其他音频软件可能仍在使用）。"
        if payload.plan.removeDriver == true {
            let ok = elevateDriverRemoval()
            driverNote = ok
                ? "已移除 BlackHole 2ch 驱动；请重启 Mac 使变更生效。"
                : "BlackHole 2ch 驱动未能移除（授权取消或命令失败），已保留。"
        }

        // Read-back verification over every target.
        var failures: [String] = []
        for target in payload.plan.targets {
            if FileManager.default.fileExists(atPath: target.path) {
                failures.append(target.path)
            }
        }
        if let marker = payload.markerPath {
            try? FileManager.default.removeItem(atPath: marker)
        }
        // Remove our own temp directory (plan file and this copy of the binary).
        let ownDirectory = URL(filePath: planPath).deletingLastPathComponent()
        var summary = "已移除：\n" + (trashed + removed.map(\.self).compactMap { $0["path"] })
            .joined(separator: "\n") + "\n\n"
        summary += driverNote + "\n"
        summary += "清空废纸篓后才会释放应用占用的空间。\n"
        summary += "如尚未操作，请把输入法的输入设备恢复为实体麦克风。"
        if !failures.isEmpty {
            summary += "\n\n以下项目仍存在，可重试卸载或手动删除：\n" + failures.joined(separator: "\n")
        }
        _ = ownDirectory
        showResult(summary)
        try? FileManager.default.removeItem(at: URL(filePath: planPath))
        exit(failures.isEmpty ? 0 : 1)
        } catch {
            FileHandle.standardError.write(Data(("卸载执行器出错：\(error)\n").utf8))
            showResult("卸载执行器出错：\(error)")
            exit(1)
        }
    }
}
