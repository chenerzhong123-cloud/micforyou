import Foundation

@main struct UninstallProtocolCheck {
    static func main() throws {
        let args = CommandLine.arguments
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
        let failed = cleanTargets(plan, home: home, delete: { _ in throw ExecutorError.refused("injected failure") })
        try require(failed.first?.status == "failed" && exists(support.path), "失败被错误报告为成功")
        try require(!summary(failed, keep: []).contains("已移除"), "失败目标列为已移除")
        let removed = cleanTargets(plan, home: home)
        let retried = cleanTargets(plan, home: home)
        try require(removed.first?.status == "removed" && retried.first?.status == "absent", "清理或幂等重试失败")
        print("native failure/retry/summary PASS")
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
