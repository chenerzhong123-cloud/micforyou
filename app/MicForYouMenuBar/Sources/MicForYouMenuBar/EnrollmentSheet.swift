import SwiftUI

/// Guided first-time / re-registration flow: read a short passage aloud for
/// about 15 seconds, automatic recording checks, then automatic model
/// preparation. The passage stays visible through countdown and recording;
/// timing always comes from the backend job, never from a local fake timer.
struct EnrollmentSheet: View {
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) private var dismiss

    static let passage = """
        今天上午九点十五分，我们讨论新的工作安排。我会先整理笔记，再确认 \
        需要完成的事情。请把时间和地点记下来，准备好后，我们就开始。
        """

    private var job: SetupJob? { model.setupJob }

    private typealias FlowState = EnrollmentFlow.State

    private var state: FlowState {
        EnrollmentFlow.state(job: job, attemptToken: model.enrollmentAttemptToken)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("注册你的声音")
                    .font(.title2.weight(.semibold))
                Spacer()
                Button {
                    if state == .countdown || state == .recording {
                        model.confirmCloseEnrollment = true
                    } else {
                        dismiss()
                    }
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.tertiary)
                }
                .buttonStyle(.plain)
                .help(state == .preparing ? "任务会在后台继续" : "关闭")
            }

            switch state {
            case .idle, .failed:
                introduction
                if state == .failed, let job {
                    Label(job.stage, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                }
                HStack {
                    Button(state == .failed ? "重新录音" : "开始录音") {
                        Task { await model.enrollVoice() }
                    }
                    .keyboardShortcut(.defaultAction)
                    .disabled(model.isWorking || model.selectedInput.isEmpty)
                    if state == .failed {
                        Button("完成") { dismiss() }
                    }
                }
                if model.selectedInput.isEmpty {
                    Text("请先在“设置”中选择实体麦克风。")
                        .font(.caption).foregroundStyle(.secondary)
                }

            case .countdown:
                passageView
                VStack(spacing: 6) {
                    Text("准备录音，等倒计时结束再开始朗读")
                        .font(.headline)
                    if let remaining = job?.recording?.remainingSeconds {
                        Text("\(Int(remaining.rounded(.up)))")
                            .font(.system(size: 56, weight: .bold))
                            .contentTransition(.numericText())
                    } else {
                        ProgressView()
                    }
                }
                .frame(maxWidth: .infinity)
                cancelButton

            case .recording:
                passageView
                VStack(spacing: 8) {
                    Text("正在录音 · 自然朗读即可")
                        .font(.headline)
                    if let recording = job?.recording {
                        ProgressView(value: min(recording.elapsedSeconds / recording.durationSeconds, 1))
                        Text(String(format: "剩余 %.0f 秒", max(recording.remainingSeconds, 0)))
                            .font(.caption).foregroundStyle(.secondary)
                            .contentTransition(.numericText())
                    } else {
                        ProgressView()
                    }
                    Text("提前读完就从头继续，看到“录音完成”后再停。")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
                cancelButton

            case .checking:
                passageView
                HStack(spacing: 10) {
                    ProgressView().controlSize(.small)
                    Text("录音完成，可以停止朗读。正在检查录音…")
                }
                .frame(maxWidth: .infinity)
                cancelButton

            case .preparing:
                VStack(spacing: 8) {
                    HStack(spacing: 10) {
                        ProgressView().controlSize(.small)
                        Text(job?.stage ?? "正在为你的声音准备模型，请稍候…")
                    }
                    // Keep the stop-reading notice visible here too: the
                    // checking phase can be shorter than one poll interval.
                    Text("录音完成，可以停止朗读。")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
                Button("后台继续") { dismiss() }

            case .done:
                Label("设置完成", systemImage: "checkmark.circle.fill")
                    .font(.title3.weight(.medium))
                    .foregroundStyle(.green)
                Text("在豆包输入法中选择 BlackHole 2ch，然后开始过滤。")
                Button("完成") { dismiss() }
                    .keyboardShortcut(.defaultAction)
            }

            if let error = model.errorMessage, state != .done {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(24)
        .frame(width: 560, height: 520)
        .interactiveDismissDisabled(state == .countdown || state == .recording)
        .task {
            // Backend-provided timing at a cadence that can render a 3-second
            // countdown; no local clock guessing.
            while !Task.isCancelled {
                await model.refreshSetup()
                try? await Task.sleep(for: .milliseconds(400))
            }
        }
        .confirmationDialog(
            "关闭将取消本次注册",
            isPresented: $model.confirmCloseEnrollment,
            titleVisibility: .visible
        ) {
            Button("取消注册并关闭", role: .destructive) {
                Task {
                    await model.cancelSetup()
                    dismiss()
                }
            }
            Button("继续录音", role: .cancel) {}
        } message: {
            Text("正在录音或倒计时，关闭窗口会停止本次采集；已保存的旧注册不受影响。")
        }
    }

    private var introduction: some View {
        VStack(alignment: .leading, spacing: 12) {
            if !model.selectedInput.isEmpty {
                Label("麦克风：\(model.selectedInput)", systemImage: "mic")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Text("在安静环境，用你平时的麦克风和说话方式朗读下面这段话，约需 15 秒。准备好后点击开始，等倒计时结束再开口。")
                .font(.body)
                .fixedSize(horizontal: false, vertical: true)
            passageView
        }
    }

    private var passageView: some View {
        GroupBox {
            Text(Self.passage)
                .font(.title3)
                .lineSpacing(6)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(6)
        }
    }

    private var cancelButton: some View {
        HStack {
            Spacer()
            Button("取消注册", role: .destructive) {
                Task {
                    await model.cancelSetup()
                }
            }
        }
    }
}
