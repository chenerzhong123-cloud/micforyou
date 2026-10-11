import SwiftUI

struct SettingsView: View {
    @ObservedObject var model: AppModel

    private var isActive: Bool {
        model.status?.runtime.isActive == true
    }

    var body: some View {
        ScrollView {
        VStack(alignment: .leading, spacing: 20) {
            VStack(alignment: .leading, spacing: 4) {
                Text("MicForYou")
                    .font(.title2.weight(.semibold))
                Text("先设置音频路由，再注册你的声音。以后点击开始即可使用。")
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
                                model.selectedInput == model.status?.inputDevice ||
                                model.status?.inputDevice.isEmpty != false
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
                    if model.isBundled && !model.driverInstalled {
                        HStack {
                            Text("请安装随 App 附带的音频组件，重启后刷新设备。")
                                .font(.caption)
                            Button("安装音频组件…") { model.openDriverGuide() }
                            Button("刷新") { Task { await model.refreshDevices() } }
                        }
                    } else {
                        Text("在豆包的输入设备中选择 BlackHole 2ch。")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                .padding(8)
            }
            .disabled(model.isWorking || isActive)

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
                    Button(model.status?.ready == true ? "重新注册…" : "注册我的声音…") {
                        model.enrollmentSheet = true
                    }
                    .disabled(isActive || model.isWorking || model.selectedInput.isEmpty ||
                              (model.isBundled ? !model.driverInstalled : model.status?.ready != true))
                }
                .padding(8)
            }

            if let job = model.setupJob {
                VStack(alignment: .leading, spacing: 8) {
                    if model.setupRunning {
                        if job.phase == "recording", let recording = job.recording {
                            ProgressView(value: min(recording.elapsedSeconds / recording.durationSeconds, 1))
                        } else {
                            ProgressView()
                                .controlSize(.small)
                        }
                        HStack {
                            Text(job.stage).font(.caption)
                            Spacer()
                            if !model.enrollmentSheet {
                                Button("取消设置") { Task { await model.cancelSetup() } }
                            }
                        }
                    } else if job.status != "IDLE" {
                        Text(job.stage).font(.caption)
                            .foregroundStyle(job.status == "FAILED" ? .red : .secondary)
                    }
                }
            }

            HStack {
                Text("声音提取模型由 Ke Zhang 开发，来自 REAL-TSE WeSep。")
                    .font(.caption).foregroundStyle(.secondary)
                Link("项目", destination: URL(string: "https://github.com/REAL-TSE/wesep-real-tse")!)
                if model.isBundled {
                    Button("许可与致谢") { model.openLicenses() }
                }
            }

            Label {
                VStack(alignment: .leading, spacing: 3) {
                    Text("试用版本")
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
        }
        .frame(width: 620, height: 610)
        .task {
            await model.refreshDevices()
            while !Task.isCancelled {
                await model.refresh()
                try? await Task.sleep(for: .seconds(2))
            }
        }
        .sheet(isPresented: $model.enrollmentSheet) {
            EnrollmentSheet(model: model)
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
