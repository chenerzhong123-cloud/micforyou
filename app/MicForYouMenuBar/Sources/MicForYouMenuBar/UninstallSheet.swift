import SwiftUI

/// Dedicated uninstall confirmation window. The plan is read-only until the
/// user confirms; deletion itself is handed to the native executor after the
/// app quits, so cleanup never depends on resources being removed.
struct UninstallSheet: View {
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("卸载 MicForYou")
                .font(.title2.weight(.semibold))

            Text("卸载会先停止录音和后台音频任务，再移除应用。请先把豆包或系统声音设置中的输入设备恢复为实体麦克风；MicForYou 不会修改第三方软件的设置。")
                .fixedSize(horizontal: false, vertical: true)

            if let plan = model.uninstallPlan {
                GroupBox("将移除") {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(plan.targets, id: \.self) { item in
                            Label(item, systemImage: "trash")
                                .font(.caption)
                        }
                        if plan.targets.isEmpty {
                            Text("应用本体不存在（视为已移除）").font(.caption)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(4)
                }
                if !plan.keep.isEmpty {
                    GroupBox("将保留") {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(plan.keep, id: \.self) { item in
                                Label(item, systemImage: "checkmark.circle")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(4)
                    }
                }
            } else if model.uninstallError == nil {
                ProgressView().controlSize(.small)
                Text("正在核对将删除与保留的项目…").font(.caption).foregroundStyle(.secondary)
            }

            Toggle(isOn: $model.uninstallKeepData) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("保留声音注册与设置")
                    Text(model.uninstallKeepData
                         ? "将保留注册录音、个人模型与配置，方便以后重装。"
                         : "将删除注册录音、个人模型、配置与运行报告；删除后需要重新注册。")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }

            Toggle(isOn: $model.uninstallRemoveDriver) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("同时移除 BlackHole 2ch 音频驱动")
                    Text("该驱动可能被其他音频软件使用；移除需要管理员授权并重启 Mac。默认保留。")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }

            if let error = model.uninstallError {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack {
                Spacer()
                Button("取消") { dismiss() }
                Button("卸载", role: .destructive) {
                    Task { await model.performUninstall() }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(model.uninstallPlan == nil || model.uninstallBusy)
            }

            if model.uninstallBusy {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("正在停止任务并准备卸载…").font(.caption)
                }
            }
        }
        .padding(22)
        .frame(width: 520)
        .task { await model.loadUninstallPlan() }
        .onChange(of: model.uninstallKeepData) { _, _ in
            Task { await model.loadUninstallPlan() }
        }
        .onChange(of: model.uninstallRemoveDriver) { _, _ in
            Task { await model.loadUninstallPlan() }
        }
    }
}
