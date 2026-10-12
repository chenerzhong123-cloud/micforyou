import SwiftUI

/// Offline, scrollable step-by-step guide for routing Doubao IME through
/// BlackHole 2ch. Purely informational: closing it never claims the input
/// method was configured or verified.
struct DoubaoGuideView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("MicForYou 使用你的实体麦克风，处理声音后送到 BlackHole 2ch；豆包再从 BlackHole 2ch 接收声音并转成文字。")
                    .fixedSize(horizontal: false, vertical: true)

                step(1, "确认 MicForYou 的麦克风") {
                    Text("在 MicForYou 的设置中，选择 MacBook 麦克风或你平时使用的外接麦克风（这里选实体麦克风，不选 BlackHole）。完成声音注册与性能检查。")
                }

                step(2, "让豆包接收处理后的声音") {
                    Text("打开豆包输入法的设置。如果当前版本提供麦克风／输入设备选项，选择 BlackHole 2ch。")
                    Text("如果找不到相关选项，可用下面的系统设置方式（任何时候都适用）：").padding(.top, 4)
                    Text("1. 点击“打开系统声音设置”，或点左上角 Apple 菜单 → 系统设置 → 声音。\n2. 找到“输入”，在输入设备列表中选择 **BlackHole 2ch**。\n3. 回到豆包，结束当前语音输入后重新开始，让它使用更新后的输入设备。\n4. 如果豆包自己指定了另一个麦克风，仍需在豆包中改为 BlackHole 或“跟随系统”——系统输入的改变不一定覆盖应用内的独立设置。")
                    Text("说明：这种方式会影响跟随系统输入的其他应用；结束 MicForYou 后，如需直接用原麦克风，请在同一位置改回实体麦克风。系统声音的输出继续用扬声器／耳机，不需要改成 BlackHole，也不需要创建聚合或多输出设备。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.top, 4)
                    HStack {
                        Button("打开系统声音设置") { model.openSystemSoundSettings() }
                        Button("刷新设备") { Task { await model.refreshDevices() } }
                    }
                    .padding(.top, 4)
                }

                step(3, "开始过滤，再开始听写") {
                    Text("回到 MicForYou，点击“开始过滤”，等菜单显示“正在过滤”。打开一个可输入文字的地方，启动豆包语音输入，说一句短话，确认出现文字。")
                }

                GroupBox("如果没有文字／没有找到 BlackHole") {
                    VStack(alignment: .leading, spacing: 6) {
                        bullet("找不到 BlackHole：若刚安装音频组件，按安装提示重启 Mac，再刷新设备；仍没有就使用设置里的“安装音频组件…”。")
                        bullet("没有文字：先看 MicForYou 是否“正在过滤”，再核对豆包／系统输入设备和麦克风权限；“正在恢复／已安全静音”应回到 MicForYou 排查。")
                        bullet("麦克风权限：查看 系统设置 → 隐私与安全性 → 麦克风 中实际请求录音的应用；不同版本的应用名称可能不同。")
                        bullet("“结束”会停止这条声音链路；“暂停过滤”仍会传原始声音，不能当作停止收音。")
                    }
                    .padding(6)
                }

                HStack {
                    Spacer()
                    Button("我已设置，关闭") { model.closeDoubaoGuide() }
                        .keyboardShortcut(.defaultAction)
                }
            }
            .padding(24)
        }
        .frame(minWidth: 560, minHeight: 520)
    }

    private func step(_ number: Int, _ title: String,
                      @ViewBuilder content: () -> some View) -> some View {
        GroupBox {
            HStack(alignment: .top, spacing: 10) {
                Text("\(number)")
                    .font(.headline)
                    .frame(width: 26, height: 26)
                    .background(Circle().fill(Color.accentColor.opacity(0.15)))
                VStack(alignment: .leading, spacing: 6) {
                    Text(title).font(.headline)
                    content()
                        .font(.body)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(6)
        }
    }

    private func bullet(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 6) {
            Text("·")
            Text(text).fixedSize(horizontal: false, vertical: true)
        }
        .font(.caption)
    }
}
