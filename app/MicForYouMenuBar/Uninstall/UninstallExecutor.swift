import AppKit
import Foundation
import Darwin

let productBundleID = "com.micforyou.menubar"
let driverPath = "/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver"
let appReceipt = "com.micforyou.complete"
let driverReceipt = "audio.existential.BlackHole2ch"

struct PlanTarget: Codable, Equatable {
    let kind: String
    let path: String
    let action: String
    let reason: String?
}
struct PlanBody: Codable {
    struct KeepItem: Codable { let path: String; let reason: String }
    let schema: String
    let targets: [PlanTarget]
    let removeDriver: Bool
    let removeUserData: Bool
    let keep: [KeepItem]
    let appReceiptInstalled: Bool
    enum CodingKeys: String, CodingKey {
        case schema, targets, keep
        case removeDriver = "remove_driver", removeUserData = "remove_user_data"
        case appReceiptInstalled = "app_receipt_installed"
    }
}
struct PlanPayload: Decodable {
    struct StopReport: Decodable {
        let allStopped: Bool
        enum CodingKeys: String, CodingKey { case allStopped = "all_stopped" }
    }
    let schema: String
    let plan: PlanBody
    let markerPath: String
    let stopped: StopReport
    enum CodingKeys: String, CodingKey {
        case schema, plan, stopped
        case markerPath = "marker_path"
    }
}
enum ExecutorError: Error, CustomStringConvertible {
    case refused(String)
    var description: String {
        switch self { case let .refused(detail): return "拒绝卸载：\(detail)" }
    }
}
func require(_ condition: Bool, _ detail: String) throws {
    guard condition else { throw ExecutorError.refused(detail) }
}
func allowedLocations(home: URL) -> [String: URL] {
    ["app": URL(filePath: "/Applications/MicForYou.app"),
     "old_app": home.appending(path: "Applications/MicForYou.app"),
     "support_dir": home.appending(path: "Library/Application Support/MicForYou"),
     "prefs": home.appending(path: "Library/Preferences/\(productBundleID).plist"),
     "caches": home.appending(path: "Library/Caches/\(productBundleID)"),
     "saved_state": home.appending(path: "Library/Saved Application State/\(productBundleID).savedState"),
     "tmp_dir": URL(filePath: "/tmp/micforyou-\(getuid())")]
}
func exists(_ path: String) -> Bool {
    var info = stat()
    return lstat(path, &info) == 0
}
func verifyNoLinks(_ url: URL, allowSystemTmp: Bool = false) throws {
    var component = url
    while component.path != "/" {
        if ["/tmp": "/private/tmp", "/var": "/private/var"].contains(where: {
            component.path == $0.key && (try? FileManager.default.destinationOfSymbolicLink(atPath: component.path).trimmingCharacters(in: CharacterSet(charactersIn: "/"))) == $0.value.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        }) { break }
        var info = stat()
        if lstat(component.path, &info) == 0 {
            try require((info.st_mode & S_IFMT) != S_IFLNK, "\(component.path)：目标或父级为符号链接")
        }
        component.deleteLastPathComponent()
    }
}
func bundleID(_ url: URL) -> String? {
    guard let data = try? Data(contentsOf: url.appending(path: "Contents/Info.plist")),
          let plist = try? PropertyListSerialization.propertyList(from: data, options: [], format: nil) as? [String: Any]
    else { return nil }
    return plist["CFBundleIdentifier"] as? String
}
func verifyTarget(_ target: PlanTarget, home: URL) throws {
    let url = URL(filePath: target.path)
    let locations = allowedLocations(home: home)
    try require(locations[target.kind]?.path == target.path,
                "\(target.path)：类型与固定路径不匹配")
    let app = target.kind == "app" || target.kind == "old_app"
    try require(target.action == (app ? "trash" : "delete"), "\(target.path)：动作不匹配")
    try verifyNoLinks(url, allowSystemTmp: target.kind == "tmp_dir")
    if exists(target.path) {
        if app {
            try require(bundleID(url) == productBundleID, "\(target.path)：bundle id 不匹配")
        } else {
            let owner = try FileManager.default.attributesOfItem(atPath: target.path)[.ownerAccountID] as? NSNumber
            try require(owner?.uint32Value == getuid(), "\(target.path)：非当前用户所有")
        }
    } // absent fixed targets are safe and idempotent
}
func verifyPlan(_ plan: PlanBody, home: URL) throws {
    try require(plan.schema == "micforyou/uninstall-plan/1", "计划版本不支持")
    try require(Set(plan.targets.map(\.path)).count == plan.targets.count, "重复目标")
    for target in plan.targets {
        try verifyTarget(target, home: home)
        if !plan.removeUserData {
            try require(["app", "old_app", "tmp_dir"].contains(target.kind), "保留数据选项与目标冲突")
        }
    }
    if plan.removeDriver && exists(driverPath) {
        try verifyNoLinks(URL(filePath: driverPath))
        try require(bundleID(URL(filePath: driverPath)) == "audio.existential.BlackHole2ch", "驱动 bundle id 不匹配")
    }
}
func prepareExecution(_ plan: PlanBody, home: URL, authorize: () throws -> Void,
                      ready: () throws -> Void) throws {
    try verifyPlan(plan, home: home)
    try authorize()
    try ready()
}
func verifyMarker(_ path: String, home: URL) throws {
    try require(path == home.appending(path: ".micforyou-coordination/uninstall.lock").path, "marker 路径不匹配")
    try verifyNoLinks(URL(filePath: path))
}
func withCoordinator<T>(home: URL, _ action: () throws -> T) throws -> T {
    let root = home.appending(path: ".micforyou-coordination")
    try verifyNoLinks(root)
    let fd = open(root.appending(path: "guard.lock").path, O_RDWR | O_NOFOLLOW)
    try require(fd >= 0, "协调锁缺失")
    defer { close(fd) }
    try require(flock(fd, LOCK_EX) == 0, "无法锁定卸载协调器")
    defer { flock(fd, LOCK_UN) }
    return try action()
}
func releaseLease(_ path: String, home: URL) throws {
    try verifyMarker(path, home: home)
    try withCoordinator(home: home) {
        if exists(path) {
            let lease = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(filePath: path))) as? [String: Any]
            try require((lease?["executor_pid"] as? Int) == Int(getpid()), "marker 不属于本执行器")
            try FileManager.default.removeItem(atPath: path)
        }
    }
}
func verifyWorkDirectory(_ work: URL) throws {
    try verifyNoLinks(work)
    let tmp = FileManager.default.temporaryDirectory.resolvingSymlinksInPath()
    let canonical = work.resolvingSymlinksInPath()
    try require(canonical.deletingLastPathComponent() == tmp &&
                work.lastPathComponent.hasPrefix("micforyou-uninstall-"), "非自有执行器临时目录")
    try verifyNoLinks(canonical)
    let attrs = try FileManager.default.attributesOfItem(atPath: work.path)
    try require((attrs[.ownerAccountID] as? NSNumber)?.uint32Value == getuid() &&
                (attrs[.posixPermissions] as? NSNumber)?.intValue == 0o700, "临时目录权限或所有者不匹配")
    try require(URL(filePath: CommandLine.arguments[0]).resolvingSymlinksInPath() == canonical.appending(path: "executor"),
                "执行器不在自有目录内")
}
func shellQuote(_ text: String) -> String { "'" + text.replacingOccurrences(of: "'", with: "'\\''") + "'" }
func receiptExists(_ name: String) -> Bool {
    let process = Process()
    process.executableURL = URL(filePath: "/usr/sbin/pkgutil")
    process.arguments = ["--pkg-info", name]
    process.standardOutput = FileHandle.nullDevice
    process.standardError = FileHandle.nullDevice
    do { try process.run(); process.waitUntilExit(); return process.terminationStatus == 0 }
    catch { return true } // inability to inspect must not be reported as absent
}

func privilegeScript(work: URL, driverCommand: String, receiptCommand: String,
                     executorPID: Int32? = nil) -> String {
    let root = shellQuote(work.resolvingSymlinksInPath().path)
    let parentCheck = executorPID.map { "/bin/kill -0 \($0) 2>/dev/null || exit 1" } ?? ":"
    return """
    work=\(root)
    wait_for() {
      n=0
      while [ ! -f "$work/$1" ]; do
        [ -e "$work/abort" ] && exit 1
        \(parentCheck)
        n=$((n+1)); [ "$n" -gt 1200 ] && exit 1
        /bin/sleep 0.1
      done
      [ -e "$work/abort" ] && exit 1
    }
    printf '%s\\n' "$$" > "$work/privilege-ready" || exit 1
    wait_for driver-commit
    \(driverCommand)
    /usr/bin/touch "$work/driver-done" || exit 1
    wait_for receipt-commit
    \(receiptCommand)
    /usr/bin/touch "$work/privilege-done" || exit 1
    """
}

/// One privileged process is authorized before readiness, then waits for two
/// explicit commit signals. Cancel/timeout cannot trigger deletion. Commands
/// and receipts are fixed; only independently verified private temp paths vary.
final class PrivilegeSession {
    let work: URL
    let process: Process
    init(work: URL, plan: PlanBody) throws {
        self.work = work
        process = Process()
        let driver = plan.removeDriver ? """
        if [ -e '\(driverPath)' ]; then /bin/rm -rf '\(driverPath)' || exit 1; fi
        if /usr/sbin/pkgutil --pkg-info '\(driverReceipt)' >/dev/null 2>&1; then
            /usr/sbin/pkgutil --forget '\(driverReceipt)' >/dev/null || exit 1
        fi
        """ : ":"
        let receipt = """
        if /usr/sbin/pkgutil --pkg-info '\(appReceipt)' >/dev/null 2>&1; then
          /usr/sbin/pkgutil --forget '\(appReceipt)' >/dev/null || exit 1
        fi
        """
        let script = privilegeScript(work: work, driverCommand: driver, receiptCommand: receipt, executorPID: getpid())
        let escaped = script.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
        process.executableURL = URL(filePath: "/usr/bin/osascript")
        process.arguments = ["-e", "do shell script \"\(escaped)\" with administrator privileges with prompt \"MicForYou 卸载需要确认安装记录及所选驱动的清理权限\""]
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try process.run()
    }
    func awaitFile(_ name: String, timeout: TimeInterval = 120) throws {
        let deadline = Date().addingTimeInterval(timeout)
        while !exists(work.appending(path: name).path) {
            try require(process.isRunning && Date() < deadline && !exists(work.appending(path: "abort").path), "权限取消、执行失败或等待超时")
            Thread.sleep(forTimeInterval: 0.1)
        }
    }
    func abort() {
        try? Data().write(to: work.appending(path: "abort"))
        let deadline = Date().addingTimeInterval(3)
        while process.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.1) }
        if process.isRunning { process.terminate() }
    }
}
struct CleanupResult: Codable {
    let path: String
    let status: String
    let detail: String?
}
func cleanTargets(_ plan: PlanBody, home: URL,
                  trash: (URL) throws -> Void = { url in
                      NSWorkspace.shared.recycle([url], completionHandler: nil)
                      let deadline = Date().addingTimeInterval(10)
                      while exists(url.path) && Date() < deadline { Thread.sleep(forTimeInterval: 0.1) }
                  },
                  delete: (URL) throws -> Void = { try FileManager.default.removeItem(at: $0) }) -> [CleanupResult] {
    plan.targets.map { target in
        do {
            // Re-check at the point of use, including absent targets/parents.
            try verifyTarget(target, home: home)
            if !exists(target.path) { return CleanupResult(path: target.path, status: "absent", detail: nil) }
            let url = URL(filePath: target.path)
            if target.action == "trash" { try trash(url) } else { try delete(url) }
            try require(!exists(target.path), "删除后目标仍存在")
            return CleanupResult(path: target.path, status: "removed", detail: nil)
        } catch { return CleanupResult(path: target.path, status: "failed", detail: String(describing: error)) }
    }
}
func summary(_ results: [CleanupResult], keep: [PlanBody.KeepItem]) -> String {
    let removed = results.filter { $0.status == "removed" }.map(\.path)
    let absent = results.filter { $0.status == "absent" }.map(\.path)
    let failed = results.filter { $0.status == "failed" }.map { "\($0.path)：\($0.detail ?? "失败")" }
    return [("已移除", removed), ("已不存在", absent), ("已保留", keep.map { "\($0.path)：\($0.reason)" }),
            ("未完成，可重试", failed)].filter { !$0.1.isEmpty }
        .map { "\($0.0)：\n" + $0.1.joined(separator: "\n") }.joined(separator: "\n\n")
}
func showResult(_ text: String, success: Bool) {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    app.activate(ignoringOtherApps: true)
    let alert = NSAlert()
    alert.messageText = success ? "MicForYou 卸载完成" : "MicForYou 卸载未完成"
    alert.informativeText = text
    alert.alertStyle = success ? .informational : .warning
    alert.addButton(withTitle: "关闭")
    _ = alert.runModal()
}
func runSelfCheck() throws {
    let home = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appending(path: "uninstall-selfcheck-\(UUID().uuidString)")
    let fm = FileManager.default
    try fm.createDirectory(at: home, withIntermediateDirectories: true)
    defer { try? fm.removeItem(at: home) }
    let support = home.appending(path: "Library/Application Support/MicForYou")
    try fm.createDirectory(at: support, withIntermediateDirectories: true)
    try verifyTarget(PlanTarget(kind: "support_dir", path: support.path, action: "delete", reason: nil), home: home)
    func rejects(_ target: PlanTarget) throws {
        var didThrow = false
        do { try verifyTarget(target, home: home) } catch { didThrow = true }
        try require(didThrow, "self-check 未拒绝 \(target.path) \(target.action)")
    }
    try rejects(PlanTarget(kind: "app", path: support.path, action: "delete", reason: nil))
    try rejects(PlanTarget(kind: "support_dir", path: support.path, action: "trash", reason: nil))
    try rejects(PlanTarget(kind: "user_data", path: "/Users", action: "delete", reason: nil))
    try fm.removeItem(at: home.appending(path: "Library"))
    let outside = home.appending(path: "elsewhere")
    try fm.createDirectory(at: outside, withIntermediateDirectories: true)
    try fm.createSymbolicLink(at: home.appending(path: "Library"), withDestinationURL: outside)
    try rejects(PlanTarget(kind: "support_dir", path: support.path, action: "delete", reason: nil))
    print("MicForYou uninstall executor self-check PASS")
}
#if !UNINSTALL_TESTING
@main struct UninstallExecutorMain {
    static func main() {
        if CommandLine.arguments.contains("--self-check") {
            do { try runSelfCheck(); exit(0) } catch { print(error); exit(1) }
        }
        let args = CommandLine.arguments
        func arg(_ name: String) -> String? {
            guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
            return args[i + 1]
        }
        let home = FileManager.default.homeDirectoryForCurrentUser
        var work: URL?
        var session: PrivilegeSession?
        var lease: String?
        var committed = false
        var parentPID: Int32?
        var outcome: [CleanupResult] = []
        var retainedItems: [PlanBody.KeepItem] = []
        do {
            guard let initial = arg("--prepare-plan"), let final = arg("--plan"),
                  let parent = arg("--parent-pid").flatMap(Int32.init), parent > 1 else {
                throw ExecutorError.refused("缺少准备计划、接管计划或主 App 身份")
            }
            parentPID = parent
            let directory = URL(filePath: initial).deletingLastPathComponent()
            try verifyWorkDirectory(directory)
            try require(initial == directory.appending(path: "inventory.json").path &&
                        final == directory.appending(path: "plan.json").path, "准备或接管计划路径不匹配")
            try verifyNoLinks(URL(filePath: initial))
            try verifyNoLinks(URL(filePath: final))
            work = directory
            let plan = try JSONDecoder().decode(PlanBody.self, from: Data(contentsOf: URL(filePath: initial)))
            try prepareExecution(plan, home: home, authorize: {
                if plan.removeDriver || plan.appReceiptInstalled || receiptExists(appReceipt) {
                    session = try PrivilegeSession(work: directory, plan: plan)
                    try session?.awaitFile("privilege-ready")
                }
            }, ready: {
                let shellPID = (try? String(contentsOf: directory.appending(path: "privilege-ready"), encoding: .utf8))
                    .flatMap { Int($0.trimmingCharacters(in: .whitespacesAndNewlines)) }
                let companionPIDs = [session.map { Int($0.process.processIdentifier) }, shellPID].compactMap { $0 }
                try JSONSerialization.data(withJSONObject: ["companion_pids": companionPIDs])
                    .write(to: directory.appending(path: "ready"), options: .atomic)
            })
            let deadline = Date().addingTimeInterval(120)
            while !exists(final) {
                try require(Date() < deadline && kill(parent, 0) == 0 && !exists(directory.appending(path: "abort").path), "主 App 退出、取消或接管超时；未删除数据")
                Thread.sleep(forTimeInterval: 0.1)
            }
            try verifyNoLinks(URL(filePath: final))
            let payload = try JSONDecoder().decode(PlanPayload.self, from: Data(contentsOf: URL(filePath: final)))
            try require(payload.schema == "micforyou/uninstall-handoff/1" && payload.stopped.allStopped, "任务未全部停止")
            try require(payload.plan.removeDriver == plan.removeDriver && payload.plan.removeUserData == plan.removeUserData, "接管选项已改变")
            try verifyPlan(payload.plan, home: home)
            try verifyMarker(payload.markerPath, home: home)
            lease = payload.markerPath
            retainedItems = payload.plan.keep
            while kill(parent, 0) == 0 {
                try require(Date() < deadline && !exists(directory.appending(path: "abort").path), "主 App 尚未退出，未删除数据")
                Thread.sleep(forTimeInterval: 0.1)
            }
            try verifyPlan(payload.plan, home: home)
            try withCoordinator(home: home) {
                let owner = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(filePath: payload.markerPath))) as? [String: Any]
                try require((owner?["executor_pid"] as? Int) == Int(getpid()), "卸载协调状态已改变")
            }
            committed = true
            var results: [CleanupResult] = []
            if let session {
                try Data().write(to: directory.appending(path: "driver-commit"))
                try session.awaitFile("driver-done")
                if plan.removeDriver {
                    try require(!exists(driverPath) && !receiptExists(driverReceipt), "驱动或驱动安装记录仍存在；保留 App 与个人数据")
                    results.append(CleanupResult(path: driverPath, status: "removed", detail: nil))
                }
            }
            results += cleanTargets(payload.plan, home: home)
            if let session, !results.contains(where: { result in
                result.status == "failed" && payload.plan.targets.contains(where: { target in
                    target.path == result.path && target.action == "trash"
                })
            }) {
                try Data().write(to: directory.appending(path: "receipt-commit"))
                do {
                    try session.awaitFile("privilege-done")
                    try require(!receiptExists(appReceipt), "App 安装记录仍存在")
                    results.append(CleanupResult(path: appReceipt, status: "removed", detail: nil))
                } catch { results.append(CleanupResult(path: appReceipt, status: "failed", detail: String(describing: error))) }
            }
            outcome = results
            try releaseLease(payload.markerPath, home: home)
            lease = nil
            let success = !results.contains { $0.status == "failed" }
            session?.abort()
            try FileManager.default.removeItem(at: directory)
            work = nil
            showResult(summary(results, keep: payload.plan.keep) + "\n\n清空废纸篓后释放应用空间。移除驱动后请重启 Mac；请把输入法输入设备恢复为实体麦克风。", success: success)
            exit(success ? 0 : 1)
        } catch {
            session?.abort()
            if let lease { try? releaseLease(lease, home: home) }
            if let work {
                try? Data(String(describing: error).utf8).write(to: work.appending(path: "error"), options: .atomic)
                // Before commit, the App reads error and owns temp cleanup.
                // Afterwards the executor must remove its surviving copy.
                if committed || parentPID.map({ kill($0, 0) != 0 }) == true {
                    try? FileManager.default.removeItem(at: work)
                }
            }
            if committed {
                showResult(summary(outcome, keep: retainedItems) + "\n\n\(error)\n已执行的删除无法自动恢复。", success: false)
            }
            FileHandle.standardError.write(Data("\(error)\n".utf8))
            exit(1)
        }
    }
}
#endif
