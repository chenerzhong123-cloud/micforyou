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
        VStack(alignment: .leading, spacing: 12) {
            header
            Divider()
            qualityNotice
            configuration
            controls
            Button("重新注册声音…") { model.confirmEnrollment = true }
                .disabled(model.busy || model.status?.ready != true || model.status?.runtime.isActive == true)
                .alert("重新注册声音", isPresented: $model.confirmEnrollment) {
                    Button("取消", role: .cancel) {}
                    Button("开始 45 秒录音") {
                        Task { await model.perform("enroll") }
                    }
                } message: {
                    Text("请使用当前日常麦克风，在安静环境自然朗读。通过 ONNX 正确性检查后才会替换现有注册；失败不会覆盖旧版本。")
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
        .padding(14)
        .frame(width: 360)
        .task {
            await model.refreshDevices()
            while !Task.isCancelled {
                await model.refresh()
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    private var header: some View {
        HStack {
            Image(systemName: iconName)
                .foregroundStyle(statusColor)
            VStack(alignment: .leading, spacing: 2) {
                Text("MicForYou").font(.headline)
                Text(statusLabel).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if model.busy { ProgressView().controlSize(.small) }
        }
    }

    private var qualityNotice: some View {
        Label(
            "实验版：可减少部分他人声，但目标缺席时仍可能放行，不能视为隐私隔离。",
            systemImage: "person.crop.circle.badge.exclamationmark"
        )
        .font(.caption)
        .foregroundStyle(.orange)
        .fixedSize(horizontal: false, vertical: true)
    }

    private var configuration: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("实体麦克风").font(.caption).foregroundStyle(.secondary)
            HStack {
                Picker("实体麦克风", selection: $model.selectedInput) {
                    if model.devices.isEmpty {
                        Text(model.selectedInput.isEmpty ? "未找到设备" : model.selectedInput)
                            .tag(model.selectedInput)
                    }
                    ForEach(model.devices) { device in
                        Text(device.name).tag(device.name)
                    }
                }
                .labelsHidden()
                .disabled(model.status?.runtime.isActive == true || model.busy)
                Button("应用") { Task { await model.changeInput() } }
                    .disabled(
                        model.busy || model.selectedInput.isEmpty ||
                        model.selectedInput == model.status?.inputDevice ||
                        model.status?.runtime.isActive == true
                    )
            }
            Text("豆包输入必须选择 BlackHole 2ch；软件不会修改系统默认输入。")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }

    private var controls: some View {
        HStack {
            if model.status?.runtime.status == "PAUSED" {
                Button("继续") { Task { await model.perform("resume") } }
                    .buttonStyle(.borderedProminent)
            } else if model.status?.runtime.isActive == true {
                Button("暂停") { Task { await model.perform("pause") } }
                    .buttonStyle(.bordered)
                Button("停止") { Task { await model.perform("stop") } }
                    .buttonStyle(.bordered)
            } else {
                Button("开始过滤") { Task { await model.perform("start") } }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.status?.ready != true)
            }
            Spacer()
            Button("刷新") { Task { await model.refresh() } }
        }
        .disabled(model.busy)
    }

    private var footer: some View {
        HStack {
            if model.status?.runtime.logPath != nil {
                Button("查看日志") { model.openLog() }
            }
            Spacer()
            Button(model.status?.runtime.isActive == true ? "退出界面（过滤继续）" : "退出界面") {
                NSApplication.shared.terminate(nil)
            }
        }
        .font(.caption)
    }

    private var statusLabel: String {
        switch runtimeStatus {
        case "RUNNING": "正在过滤"
        case "STARTING": "正在加载模型"
        case "RECOVERING": "正在恢复，当前静音"
        case "DEGRADED": "未过滤原音透传"
        case "PAUSED": "已暂停，麦克风已释放"
        case "FAULT": "故障，输出保持静音"
        case "STOPPED": model.status?.ready == true ? "已就绪" : "尚未就绪"
        default: "正在读取状态"
        }
    }

    private var iconName: String {
        switch appearance {
        case .good: "waveform.badge.mic"
        case .warning: "arrow.triangle.2.circlepath"
        case .danger: "exclamationmark.shield.fill"
        case .neutral: "mic.slash"
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
