import SwiftUI

struct MenuContentView: View {
    @ObservedObject var model: AppModel

    private var runtimeStatus: String {
        model.status?.runtime.effectiveStatus ?? "UNKNOWN"
    }

    private var appearance: StatusAppearance {
        StatusAppearance.forStatus(runtimeStatus)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header
            routeSummary
            primaryControls

            if let message = importantMessage {
                Label(message.text, systemImage: message.icon)
                    .font(.caption)
                    .foregroundStyle(message.color)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if let error = model.errorMessage {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Divider()
            footer
        }
        .padding(16)
        .frame(width: 328)
        .task {
            while !Task.isCancelled {
                await model.refresh()
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    private var header: some View {
        HStack(spacing: 11) {
            Image(nsImage: NSApplication.shared.applicationIconImage)
                .resizable()
                .scaledToFit()
                .frame(width: 38, height: 38)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay(alignment: .bottomTrailing) {
                    Circle()
                        .fill(statusColor)
                        .frame(width: 9, height: 9)
                        .overlay(Circle().stroke(.background, lineWidth: 2))
                        .accessibilityHidden(true)
                }
                .accessibilityLabel("MicForYou")

            VStack(alignment: .leading, spacing: 2) {
                Text(statusLabel)
                    .font(.headline)
                Text(statusDetail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            Spacer()
            if model.isWorking {
                ProgressView().controlSize(.small)
            } else {
                Text("Alpha")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 3)
                    .background(.quaternary, in: Capsule())
            }
        }
    }

    private var routeSummary: some View {
        HStack(spacing: 8) {
            Image(systemName: "mic")
            Text(model.status?.inputDevice ?? "正在读取麦克风")
                .lineLimit(1)
            Image(systemName: "chevron.right")
                .font(.caption2)
                .foregroundStyle(.tertiary)
            Text("BlackHole 2ch")
                .lineLimit(1)
        }
        .font(.caption)
        .foregroundStyle(.secondary)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.55), in: RoundedRectangle(cornerRadius: 8))
    }

    @ViewBuilder
    private var primaryControls: some View {
        if runtimeStatus == "PAUSED" {
            HStack {
                actionButton("继续过滤", systemImage: "play.fill", command: "resume", prominent: true)
                actionButton("结束", systemImage: "stop.fill", command: "stop")
            }
        } else if ["RUNNING", "DEGRADED"].contains(runtimeStatus) {
            HStack {
                actionButton("暂停过滤", systemImage: "pause.fill", command: "pause", prominent: true)
                actionButton("结束", systemImage: "stop.fill", command: "stop")
            }
        } else if ["STARTING", "RECOVERING", "STOPPING"].contains(runtimeStatus) {
            HStack {
                Button {
                } label: {
                    Label(statusLabel, systemImage: "hourglass")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(true)
                actionButton("结束", systemImage: "stop.fill", command: "stop")
            }
        } else if model.status?.runtime.isActive == true {
            actionButton("结束", systemImage: "stop.fill", command: "stop")
        } else if model.status?.ready == true {
            actionButton(
                runtimeStatus == "FAULT" ? "重新尝试" : "开始过滤",
                systemImage: runtimeStatus == "FAULT" ? "arrow.clockwise" : "waveform.badge.mic",
                command: "start",
                prominent: true
            )
        } else {
            SettingsLink {
                Label("打开设置", systemImage: "gearshape")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
        }
    }

    @ViewBuilder
    private func actionButton(
        _ title: String,
        systemImage: String,
        command: String,
        prominent: Bool = false
    ) -> some View {
        if prominent {
            Button {
                Task { await model.perform(command) }
            } label: {
                Label(title, systemImage: systemImage)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(model.isWorking)
        } else {
            Button {
                Task { await model.perform(command) }
            } label: {
                Label(title, systemImage: systemImage)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .controlSize(.large)
            .disabled(model.isWorking)
        }
    }

    private var footer: some View {
        HStack(spacing: 12) {
            SettingsLink {
                Label("设置", systemImage: "gearshape")
            }
            .keyboardShortcut(",")

            if model.status?.runtime.logPath != nil {
                Button("日志") { model.openLog() }
            }

            Spacer()
            Button("退出界面") { NSApplication.shared.terminate(nil) }
                .help(model.status?.runtime.isActive == true ? "音频会继续在后台运行；结束才释放麦克风" : "退出 MicForYou 界面")
        }
        .font(.caption)
        .buttonStyle(.plain)
        .foregroundStyle(.secondary)
    }

    private var importantMessage: (text: String, icon: String, color: Color)? {
        switch runtimeStatus {
        case "RUNNING":
            return ("豆包输入保持为 BlackHole 2ch", "checkmark.circle", .secondary)
        case "RECOVERING":
            return ("正在重建音频链路；恢复前不会输出声音", "shield.lefthalf.filled", .orange)
        case "DEGRADED":
            return ("警告：当前输出未经过滤的原始声音", "exclamationmark.shield.fill", .red)
        case "FAULT":
            return ("已安全静音。可检查设备后重新尝试", "speaker.slash.fill", .red)
        case "PAUSED":
            return ("原音直通中，包含身旁人声；结束才释放麦克风", "pause.circle", .orange)
        default:
            if let error = model.status?.deviceErrors.first {
                return (error, "mic.slash", .orange)
            }
            return nil
        }
    }

    private var statusLabel: String {
        switch runtimeStatus {
        case "RUNNING": "正在过滤"
        case "STARTING": "正在加载"
        case "RECOVERING": "正在恢复"
        case "STOPPING": "正在结束"
        case "DEGRADED": "原音透传"
        case "PAUSED": "过滤已暂停"
        case "FAULT": "已安全静音"
        case "STOPPED": model.status?.ready == true ? "可以开始" : "需要完成设置"
        default: "正在读取状态"
        }
    }

    private var statusDetail: String {
        switch runtimeStatus {
        case "RUNNING": "仅处理声音，不转写文字"
        case "STARTING": "首次加载可能需要一点时间"
        case "RECOVERING": "异常片段已跳过"
        case "STOPPING": "正在释放麦克风"
        case "DEGRADED": "连续优先模式"
        case "PAUSED": "原始声音继续输入"
        case "FAULT": "隐私优先模式"
        case "STOPPED": model.status?.ready == true ? "隐私优先 · 故障时静音" : "检查实体麦克风"
        default: "MicForYou"
        }
    }

    private var statusColor: Color {
        switch appearance {
        case .good: .green
        case .warning: .orange
        case .danger: .red
        case .neutral: .secondary
        }
    }
}
