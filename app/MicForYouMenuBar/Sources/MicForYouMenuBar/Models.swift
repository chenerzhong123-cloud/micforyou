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
    let voice: String?
    let performance: String?
    let performanceReason: String?
    let recording: RecordingProgress?

    enum CodingKeys: String, CodingKey {
        case status, stage, progress, phase, reason, token, voice
        case performance
        case performanceReason = "performance_reason"
        case recording
    }

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
/// Read-only uninstall inventory rendered in the confirmation window.
struct UninstallInventory: Decodable {
    let targets: [String]
    let keep: [String]

    private struct Raw: Decodable {
        struct Item: Decodable {
            let kind: String
            let reason: String?
        }
        let targets: [Item]
        struct KeepItem: Decodable {
            let path: String
            let reason: String
        }
        let schema: String
        let keep: [KeepItem]
    }

    enum CodingKeys: String, CodingKey {
        case rawTargets = "targets"
        case rawKeep = "keep"
    }

    init(from decoder: Decoder) throws {
        let raw = try Raw(from: decoder)
        guard raw.schema == "micforyou/uninstall-plan/1" else {
            throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath,
                                                    debugDescription: "unsupported uninstall plan"))
        }
        let labels = ["app": "应用本体（含内置模型与运行环境）",
                      "old_app": "旧位置的应用副本",
                      "support_dir": "声音注册、个人模型、配置与报告",
                      "prefs": "应用偏好", "caches": "缓存",
                      "saved_state": "窗口状态", "tmp_dir": "本机临时控制文件"]
        self.targets = raw.targets.map { labels[$0.kind] ?? $0.kind }
        self.keep = raw.keep.compactMap(\.reason)
    }
}

enum EnrollmentFlow {
    enum State: Equatable {
        case idle, countdown, recording, checking, preparing
        case failed
        case done
        // Voice saved and the machine check reached a verdict that needs the
        // user: stable-but-slower (explicit trial) or blocked (retest).
        case waitingTrial
        case performanceBlocked
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
        case "WAITING":
            if job.performance == "latency_warning" { return .waitingTrial }
            return .performanceBlocked
        case "FAILED":
            if job.voice == "saved" {
                return .performanceBlocked
            }
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
