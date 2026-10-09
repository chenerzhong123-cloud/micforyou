import SwiftUI

struct SettingsView: View {
    @ObservedObject var model: AppModel

    private var isActive: Bool {
        model.status?.runtime.isActive == true
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            VStack(alignment: .leading, spacing: 4) {
                Text("MicForYou")
                    .font(.title2.weight(.semibold))
                Text("选择声音来源。输出固定交给 BlackHole，再由豆包完成语音识别。")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            GroupBox("音频链路") {
                VStack(spacing: 12) {
                    settingRow(icon: "mic", title: "实体麦克风") {
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
                        .frame(width: 220)

                        Button("应用") { Task { await model.changeInput() } }
                            .disabled(
                                model.selectedInput.isEmpty ||
                                model.selectedInput == model.status?.inputDevice
                            )
                    }

                    Divider()

                    settingRow(icon: "waveform", title: "输出") {
                        Text("BlackHole 2ch")
                            .foregroundStyle(.secondary)
                        Image(systemName: "lock.fill")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                    }
                }
                .padding(8)
            }
            .disabled(model.busy || isActive)

            GroupBox("你的声音") {
                HStack(spacing: 12) {
                    Image(systemName: "person.wave.2")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                        .frame(width: 24)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("声音注册")
                        Text("更换常用麦克风或本人声音识别明显变差时再重新注册。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("重新注册…") { model.confirmEnrollment = true }
                        .disabled(model.status?.ready != true || isActive || model.busy)
                }
                .padding(8)
            }

            Label {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Experimental Alpha")
                        .font(.subheadline.weight(.medium))
                    Text("当前版本可减少部分他人声，但不能保证完全隔离；目标缺席时仍可能放行。默认故障策略为静音。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            } icon: {
                Image(systemName: "person.crop.circle.badge.exclamationmark")
                    .foregroundStyle(.orange)
            }

            if isActive {
                Label("过滤或原音直通时不能切换麦克风或重新注册。请先在菜单中结束。", systemImage: "info.circle")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if let error = model.errorMessage {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer()
        }
        .padding(24)
        .frame(width: 560, height: 440)
        .task {
            await model.refresh()
            await model.refreshDevices()
        }
        .alert("重新注册声音", isPresented: $model.confirmEnrollment) {
            Button("取消", role: .cancel) {}
            Button("开始 45 秒录音") {
                Task { await model.perform("enroll") }
            }
        } message: {
            Text("请使用当前日常麦克风，在安静环境自然朗读。检查通过后才会替换现有注册；失败不会覆盖旧版本。")
        }
    }

    private func settingRow<Content: View>(
        icon: String,
        title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .foregroundStyle(.secondary)
                .frame(width: 20)
            Text(title)
            Spacer()
            content()
        }
    }
}
