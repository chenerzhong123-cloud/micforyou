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

struct SetupJob: Decodable {
    let status: String
    let stage: String
    let progress: Double
    // Structured setup state; absent in jobs written by older versions.
    let phase: String?
    let reason: String?
    let token: String?
    let recording: RecordingProgress?

    struct RecordingProgress: Decodable {
        let durationSeconds: Double
        let countdownSeconds: Double?
        let elapsedSeconds: Double

        enum CodingKeys: String, CodingKey {
            case durationSeconds = "duration_seconds"
            case countdownSeconds = "countdown_seconds"
            case elapsedSeconds = "elapsed_seconds"
        }

        var remainingSeconds: Double {
            if let countdown = countdownSeconds, elapsedSeconds < countdown {
                return countdown - elapsedSeconds
            }
            return max(durationSeconds - elapsedSeconds, 0)
        }
    }
}

/// Pure mapping from the persisted setup job to the registration window's
/// flow state. A persisted READY only counts as this window's success when its
/// worker token matches the attempt started (or adopted) in this window;
/// otherwise the sheet shows a fresh preview so the user can register again.
enum EnrollmentFlow {
    enum State: Equatable {
        case idle, countdown, recording, checking, preparing, failed, done
    }

    static func state(job: SetupJob?, attemptToken: String?) -> State {
        guard let job else { return .idle }
        switch job.status {
        case "RUNNING":
            switch job.phase {
            case "countdown": return .countdown
            case "recording": return .recording
            case "checking": return .checking
            default: return .preparing
            }
        case "READY":
            if let token = job.token, token == attemptToken { return .done }
            return .idle
        case "FAILED":
            return .failed
        default:
            return .idle
        }
    }
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
