import Foundation

struct BridgeHealth: Codable, Equatable {
    let status: String
    let detail: String?
    let finalMode: String?
    let degraded: Bool?
    let modeRevision: Int?

    enum CodingKeys: String, CodingKey {
        case status, detail, degraded
        case finalMode = "final_mode"
        case modeRevision = "mode_revision"
    }
}

struct RuntimeStatus: Codable, Equatable {
    let status: String
    let detail: String?
    let logPath: String?
    let bridgeHealth: BridgeHealth?
    let pid: Int?
    let processingMode: String?
    let modeRevision: Int?

    enum CodingKeys: String, CodingKey {
        case status, detail, pid
        case processingMode = "processing_mode"
        case modeRevision = "mode_revision"
        case logPath = "log_path"
        case bridgeHealth = "bridge_health"
    }

    var effectiveStatus: String {
        if status == "PAUSED" && pid == nil && processingMode != "passthrough" {
            return "STOPPED" // legacy pause released capture
        }
        if ["STOPPED", "FAULT", "STOPPING"].contains(status) {
            return status
        }
        if let health = bridgeHealth {
            if ["RECOVERING", "FAULT", "DEGRADED", "UNKNOWN"].contains(health.status) {
                return health.status
            }
            if (health.modeRevision ?? 0) >= (modeRevision ?? 0) {
                return health.status
            }
        }
        return status
    }

    var effectiveDetail: String? {
        effectiveStatus == status ? detail ?? bridgeHealth?.detail : bridgeHealth?.detail ?? detail
    }

    var isActive: Bool {
        pid != nil || ["STARTING", "RUNNING", "PAUSED", "RECOVERING", "DEGRADED", "STOPPING"]
            .contains(effectiveStatus)
    }
}

struct ProductStatus: Codable, Equatable {
    let ready: Bool
    let inputDevice: String
    let outputDevice: String
    let faultPolicy: String
    let deviceErrors: [String]
    let runtime: RuntimeStatus
    let qualityNotice: String

    enum CodingKeys: String, CodingKey {
        case ready, runtime
        case inputDevice = "input_device"
        case outputDevice = "output_device"
        case faultPolicy = "fault_policy"
        case deviceErrors = "device_errors"
        case qualityNotice = "quality_notice"
    }
}

struct AudioDevice: Codable, Identifiable, Hashable {
    let index: Int
    let name: String
    let maxInputChannels: Int

    enum CodingKeys: String, CodingKey {
        case index, name
        case maxInputChannels = "max_input_channels"
    }

    var id: String { "\(index):\(name)" }
}

enum StatusAppearance: Equatable {
    case neutral, good, warning, danger

    static func forStatus(_ status: String) -> StatusAppearance {
        switch status {
        case "RUNNING": .good
        case "STARTING", "RECOVERING", "PAUSED", "STOPPING": .warning
        case "DEGRADED", "FAULT": .danger
        default: .neutral
        }
    }
}
