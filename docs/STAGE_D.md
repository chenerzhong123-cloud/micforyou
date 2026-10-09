# Stage D：Mac A 日常运行入口

日期：2026-09-22。状态：`CLI + MAC A HOT-PLUG PASS / USER-ACCEPTED EXPERIMENTAL EFFECT`。用户确认真实办公室处理后减少了部分他人声和噪声，并接受继续项目；但目标缺席样本仍向豆包输出了可辨认的他人语音，因此不得标记为“只保留本人”或严格隐私隔离。

MicForYou 不修改 macOS 默认输入，也不实现 ASR。日常链路仍是：

```text
explicit physical microphone → REAL-TSE/ONNX → BlackHole 2ch → 豆包输入法
```

## 已配置的 Mac A

本机配置保存在：

```text
~/Library/Application Support/MicForYou/config.json
```

配置已通过 `status` 和 5 秒真实设备 smoke test。它引用本地 enrollment、个性化 ONNX 和官方 REAL-TSE 虚拟环境；这些私有或大型文件不会上传 GitHub。

## 每次使用（后台控制流程）

1. 在豆包输入法中选择 `BlackHole 2ch`。
2. 在项目目录运行：

```bash
uv run micforyou status
uv run micforyou start
```

3. `status` 必须显示 `"ready": true`；启动后 `runtime.bridge_health.status` 会从 `STARTING` 变为 `RUNNING`。
4. 后台运行期间可关闭 Terminal。控制命令为：

```bash
uv run micforyou pause   # 暂停过滤，原音继续输入，麦克风仍在使用
uv run micforyou resume  # 在同一音频进程和 Stream 内重建过滤状态后继续
uv run micforyou stop    # 释放麦克风，并记为 STOPPED
```

5. 停止后按需把豆包麦克风恢复为日常物理麦克风。

后台控制状态保存在 `~/Library/Application Support/MicForYou/state.json`；日志只含运行事件和指标，不含音频或豆包文字。`pause` 在音频块边界切到原音直通，丢弃旧过滤队列与输出；`resume` 保持设备不重开，建立新的 resampler、STFT/OLA、recurrent state 和有界队列后切回过滤。原音含旁人及环境声音，只有 `stop` 才释放麦克风。

同一组操作已由 [原生菜单栏应用](MENU_BAR_APP.md)封装，包括实体麦克风选择和重新注册确认。菜单栏退出不会暗中停止一个仍在运行的隐私优先 bridge，按钮会明确显示“退出界面（音频继续）”。

仍保留 `uv run micforyou run` 作为前台诊断模式，可用 `Control-C` 停止。

## 更换实体麦克风

先结束音频，再列出设备并只修改输入项：

```bash
uv run micforyou devices
uv run micforyou set-input "MacBook Air Microphone"
uv run micforyou status
```

软件绝不会因为原设备消失而自动执行这一步。换麦克风后 `set-input` 会提示需要重新注册/短基线；运行 `uv run micforyou enroll` 后再开始日常使用。

MicForYou 从不修改系统默认输入，所以“恢复原输入”只涉及豆包自己的设备选择。

## 故障策略

- `silence`：默认、隐私优先。有限恢复仍失败后保持静音。
- `passthrough`：连续优先。有限恢复仍失败后，把同一个已选实体麦克风原音送到 BlackHole。终端会立即并每 30 秒重复显示 `UNFILTERED` 警告，报告标记 `degraded=true` 和 `final_mode=passthrough`。当前只允许前台 `run` 使用；后台 `start` 会拒绝该策略，因为后台日志不能代替常驻警告界面。

停止后可运行 `uv run micforyou set-policy silence|passthrough` 切换策略，不能在运行中静默切换。不会自动选择另一支麦克风。

默认 `continue_tse` 会在已选物理输入消失时保持静音、等待最多 120 秒；同名输入重新出现后，以重新解析的设备索引重开同一条 TSE → BlackHole 链路。运行中同时检查 PortAudio `input_underflow` 和短命独立进程取得的新 CoreAudio 设备清单；无法确认原设备仍在时按失败关闭处理。它不依赖 macOS 将旧流自动接到内置麦克风。故障默认静音；主动暂停则明确输出所选设备原音，断链恢复保留用户选择的处理模式。若有意改用另一支麦克风，请先用 `configure` 明确更改 `--input-device`，再开始新的运行。

### 2026-09-21 真实拔插验收

Mac A M5、`External Microphone`、ONNX CPU/1 thread、8 frames 实测 300 秒：

- 耳机连接时，豆包完整识别 TSE 基线句；
- 拔出后约在运行第 33.02 秒收到 `input underflow` 并关闭采集；对 MacBook microphone 说测试句时豆包无文字；
- 同一耳机在静音等待期间返回，等待 76.39 秒后重新打开 TSE；豆包完整识别恢复句；
- 最终 `final_mode=tse`，`reconnections=1`，`passthrough=null`，恢复后的第二次尝试无 fault；
- 恢复后 bridge latency p95 为 260.20 ms，模型调用 p95 为 29.26 ms；整段进程平均约占一个 CPU 核的 31.3%，峰值 RSS 约 1.06 GB。

运行 JSON 与语音均仅保存在本机私有工作目录，不提交 Git。

## 重新注册

在安静环境中运行：

```bash
uv run micforyou enroll
```

程序录制 45 秒候选语音，自动选择最高 RMS 的 6 秒窗口，在本地重新导出个性化 ONNX，并执行 100 块 Torch/ONNX 数值对照。只有 `PASS` 才会替换当前 enrollment 和 ONNX；旧文件会加时间戳备份。失败候选和报告留在本地供诊断，不会上传。

注册必须使用日常实际输入设备。2026-09-21 实测中，使用 MacBook microphone 的旧注册搭配有线耳机输入时，TSE 输出无法稳定被豆包识别；改用同一有线耳机重新注册并通过数值校验后，基线、断链和恢复句均可识别。换电脑不必必然重训模型，但换麦克风后应重新注册并做短基线验收。

## 已知限制

- 真实办公室验收中，本人片段语义得到保留，但 13 秒目标缺席片段仍产生完整的他人转写；Stage B 质量门失败。故障静音只保护运行时异常，不能弥补模型在正常运行时的错放行。
- REAL-TSE 源码/权重尚无足够清晰的统一分发许可，当前只作为本机原型，不能宣称可商业分发。
- Mac A 30 分钟峰值 RSS 约 1.03 GB，后续应优化；Mac B M1 不能使用这套性能结论。
- 当前独立设备清单检查每秒启动一个短命 Python 进程，优先保证 CLI 原型的隐私边界；它使本次平均 CPU 使用高于此前稳定性基线。原生应用阶段应改成 CoreAudio 设备属性监听，避免轮询进程开销。
- 当前具备 CLI 与原生菜单栏 UI。隐私优先后台模式可关闭 Terminal；连续优先仍要求前台可见。
- `pause/resume` 已实现为同一 Stream 内的过滤 / 原音切换，继续时不复用旧流式模型状态；本次自动与合成输入验证见 [记录](PAUSE_PASSTHROUGH_VALIDATION.md)，真实麦克风与输入法验收仍待完成。

## 卸载/恢复

停止进程并将豆包输入改回物理麦克风即可恢复日常使用。配置文件可以保留；若要完全移除，先备份需要保留的 enrollment，再删除应用配置和本地模型。BlackHole 是否卸载由用户单独决定，MicForYou 不自动删除音频驱动。
