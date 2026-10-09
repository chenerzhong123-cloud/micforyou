import Foundation

@main
struct ModelCheck {
    static func main() throws {
        let data = Data(#"""
        {
          "ready": true,
          "input_device": "External Microphone",
          "output_device": "BlackHole 2ch",
          "fault_policy": "silence",
          "device_errors": [],
          "quality_notice": "partial filtering only",
          "runtime": {
            "pid": 1234,
            "status": "STARTING",
            "detail": "process started",
            "log_path": "/tmp/bridge.log",
            "bridge_health": {
              "status": "RUNNING",
              "detail": "route is open",
              "final_mode": "tse",
              "degraded": false
            }
          }
        }
        """#.utf8)
        let value = try JSONDecoder().decode(ProductStatus.self, from: data)
        precondition(value.ready)
        precondition(value.runtime.status == "STARTING")
        precondition(value.runtime.effectiveStatus == "RUNNING")
        precondition(value.runtime.isActive)
        precondition(StatusAppearance.forStatus("FAULT") == .danger)
        precondition(StatusAppearance.forStatus("DEGRADED") == .danger)
        precondition(StatusAppearance.forStatus("RUNNING") == .good)
        let paused = RuntimeStatus(
            status: "PAUSED",
            detail: "released",
            logPath: "/tmp/bridge.log",
            bridgeHealth: BridgeHealth(
                status: "STOPPED", detail: "bridge finished",
                finalMode: "tse", degraded: false, modeRevision: 0
            ), pid: nil, processingMode: nil, modeRevision: nil
        )
        precondition(paused.effectiveStatus == "STOPPED")
        precondition(!paused.isActive)
        let rawData = Data(#"""
        {"status":"PAUSED","pid":1234,"processing_mode":"passthrough","mode_revision":2,
         "detail":"raw continues","bridge_health":{"status":"PAUSED","final_mode":"passthrough","mode_revision":2,"degraded":false}}
        """#.utf8)
        let raw = try JSONDecoder().decode(RuntimeStatus.self, from: rawData)
        precondition(raw.effectiveStatus == "PAUSED")
        precondition(raw.isActive)
        precondition(StatusAppearance.forStatus("PAUSED") == .warning)
        let fault = RuntimeStatus(status: "PAUSED", detail: "raw", logPath: nil,
            bridgeHealth: BridgeHealth(status: "FAULT", detail: "device lost", finalMode: "none", degraded: true, modeRevision: 2),
            pid: 1234, processingMode: "passthrough", modeRevision: 2)
        precondition(fault.effectiveStatus == "FAULT")
        precondition(fault.isActive)
        let stale = RuntimeStatus(status: "PAUSED", detail: "raw", logPath: nil,
            bridgeHealth: BridgeHealth(status: "RUNNING", detail: "old mode", finalMode: "tse", degraded: false, modeRevision: 1),
            pid: 1234, processingMode: "passthrough", modeRevision: 2)
        precondition(stale.effectiveStatus == "PAUSED")
        print("MicForYouMenuBar model check PASS")
    }
}
