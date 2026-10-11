import Foundation

@main struct UninstallProtocolCheck {
    static func main() throws {
        let args = CommandLine.arguments
        if args.contains("--cleanup-check") {
            let work = URL(filePath: args[0]).deletingLastPathComponent()
            try removeWorkDirectory(work)
            try require(!exists(work.path), "执行器临时目录仍存在")
            print("native own-directory cleanup PASS")
            return
        }
        let home = URL(filePath: args[1])
        for path in args.dropFirst(2) {
            let data = try Data(contentsOf: URL(filePath: path))
            let ui = try JSONDecoder().decode(UninstallInventory.self, from: data)
            let plan = try JSONDecoder().decode(PlanBody.self, from: data)
            try verifyPlan(plan, home: home)
            try require(ui.targets.count == plan.targets.count && ui.keep.count == plan.keep.count, "UI 丢失目标或保留项目")
            let envelope: [String: Any] = ["schema": "micforyou/uninstall-handoff/1",
                "plan": try JSONSerialization.jsonObject(with: data), "stopped": ["all_stopped": true],
                "marker_path": home.appending(path: ".micforyou-coordination/uninstall.lock").path]
            let payload = try JSONDecoder().decode(PlanPayload.self, from: JSONSerialization.data(withJSONObject: envelope))
            try require(payload.plan.removeDriver == plan.removeDriver && payload.plan.removeUserData == plan.removeUserData && payload.stopped.allStopped, "snake_case 选项解码不一致")
            try verifyMarker(payload.markerPath, home: home)
            print("protocol PASS remove_driver=\(plan.removeDriver) remove_user_data=\(plan.removeUserData)")
        }
        try runSelfCheck()
        let fakeApp = home.appending(path: "Unexpected/MicForYou.app")
        let contents = fakeApp.appending(path: "Contents")
        try FileManager.default.createDirectory(at: contents, withIntermediateDirectories: true)
        try PropertyListSerialization.data(fromPropertyList: ["CFBundleIdentifier": productBundleID],
                                           format: .xml, options: 0).write(to: contents.appending(path: "Info.plist"))
        for action in ["trash", "delete"] {
            var refused = false
            do { try verifyTarget(PlanTarget(kind: "app", path: fakeApp.path, action: action, reason: nil), home: home) }
            catch { refused = true }
            try require(refused && exists(fakeApp.path), "任意位置同 bundle id 的 App 被接受")
        }
        let fixed = home.appending(path: "Applications/MicForYou.app")
        try FileManager.default.createDirectory(at: fixed.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.moveItem(at: fakeApp, to: fixed)
        try verifyTarget(PlanTarget(kind: "old_app", path: fixed.path, action: "trash", reason: nil), home: home)
        var wrongActionRefused = false
        do { try verifyTarget(PlanTarget(kind: "old_app", path: fixed.path, action: "delete", reason: nil), home: home) }
        catch { wrongActionRefused = true }
        try require(wrongActionRefused, "App delete 动作被接受")
        try FileManager.default.removeItem(at: fixed)
        try verifyTarget(PlanTarget(kind: "old_app", path: fixed.path, action: "trash", reason: nil), home: home)
        print("native bundle path/action/idempotence PASS")
        let support = home.appending(path: "Library/Application Support/MicForYou")
        let target = PlanTarget(kind: "support_dir", path: support.path, action: "delete", reason: nil)
        let plan = PlanBody(schema: "micforyou/uninstall-plan/1", targets: [target], removeDriver: false,
                            removeUserData: true, keep: [], appReceiptInstalled: false)
        var ready = false
        var authorizationFailed = false
        do {
            try prepareExecution(plan, home: home, authorize: { throw ExecutorError.refused("permission denied") },
                                 ready: { ready = true })
        } catch { authorizationFailed = true }
        try require(authorizationFailed && !ready && exists(support.path), "权限拒绝仍进入删除")
        var takeoverFailed = false
        do {
            try prepareExecution(plan, home: home, authorize: {},
                                 ready: { throw ExecutorError.refused("takeover failed") })
        } catch { takeoverFailed = true }
        try require(takeoverFailed && exists(support.path), "接管失败仍进入删除")
        var parentRefused = false
        do {
            try awaitParentExit(7, deadline: Date().addingTimeInterval(-1), canceled: { false },
                                alive: { _ in true }, sleep: {})
        } catch { parentRefused = true }
        try require(parentRefused && exists(support.path), "主 App 未退出仍进入删除")
        var canceled = false
        do {
            try awaitParentExit(7, deadline: Date().addingTimeInterval(1), canceled: { true },
                                alive: { _ in false }, sleep: {})
        } catch { canceled = true }
        try require(canceled && exists(support.path), "取消仍进入删除")
        var polls = 0
        try awaitParentExit(7, deadline: Date().addingTimeInterval(1), canceled: { false },
                            alive: { _ in polls < 2 }, sleep: { polls += 1 })
        try require(polls == 2, "未等主 App 退出")
        let failed = cleanTargets(plan, home: home, delete: { _ in throw ExecutorError.refused("injected failure") })
        try require(failed.first?.status == "failed" && exists(support.path), "失败被错误报告为成功")
        try require(!summary(failed, keep: []).contains("已移除"), "失败目标列为已移除")
        let removed = cleanTargets(plan, home: home)
        let retried = cleanTargets(plan, home: home)
        try require(removed.first?.status == "removed" && retried.first?.status == "absent", "清理或幂等重试失败")
        let partialDriver = driverReadback(driverExisted: true, driverRemaining: false,
                                          receiptExisted: true, receiptRemaining: true)
        try require(partialDriver[0].status == "removed" && partialDriver[1].status == "failed", "驱动部分失败状态不准确")
        let absentDriver = driverReadback(driverExisted: false, driverRemaining: false,
                                         receiptExisted: false, receiptRemaining: false)
        try require(absentDriver.allSatisfy { $0.status == "absent" }, "不存在的驱动被列为移除")
        print("native failure/retry/summary/driver-readback PASS")
        // Execute the production two-phase privileged script with only fake
        // commands, under the normal user. No osascript, driver or receipts.
        for mode in ["abort", "success", "receipt-failure"] {
            let folder = home.appending(path: mode)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let events = folder.appending(path: "events")
            let fakeDriver = "printf driver >> " + shellQuote(events.path)
            let fakeReceipt = mode == "receipt-failure" ? "exit 7" : "printf receipt >> " + shellQuote(events.path)
            let process = Process()
            process.executableURL = URL(filePath: "/bin/sh")
            process.arguments = ["-c", privilegeScript(work: folder, driverCommand: fakeDriver, receiptCommand: fakeReceipt)]
            try process.run()
            func wait(_ name: String) throws {
                let deadline = Date().addingTimeInterval(3)
                while !exists(folder.appending(path: name).path) {
                    try require(process.isRunning && Date() < deadline, "fake privilege wait failed")
                    Thread.sleep(forTimeInterval: 0.01)
                }
            }
            try wait("privilege-ready")
            try require(!exists(events.path), "权限准备阶段发生删除")
            if mode == "abort" {
                try Data().write(to: folder.appending(path: "abort"))
            } else {
                try Data().write(to: folder.appending(path: "driver-commit"))
                try wait("driver-done")
                let recorded = try String(contentsOf: events, encoding: .utf8)
                try require(recorded == "driver", "receipt 提前清理")
                try Data().write(to: folder.appending(path: "receipt-commit"))
            }
            process.waitUntilExit()
            if mode == "abort" { try require(!exists(events.path) && process.terminationStatus != 0, "取消仍执行删除") }
            else if mode == "receipt-failure" { try require(process.terminationStatus == 7 && !exists(folder.appending(path: "privilege-done").path), "receipt 失败被覆盖") }
            else { try require(process.terminationStatus == 0 && exists(folder.appending(path: "privilege-done").path), "权限阶段未完成") }
        }
        print("native privilege handshake/cancellation/receipt PASS")
    }
}
