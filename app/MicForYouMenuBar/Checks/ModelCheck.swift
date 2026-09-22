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
                finalMode: "tse", degraded: false
            )
        )
        precondition(paused.effectiveStatus == "PAUSED")
        print("MicForYouMenuBar model check PASS")
    }
}
