# Stage D：Mac A 日常运行入口

日期：2026-09-20。状态：`CLI MVP PASS`；原生菜单栏 UI、真实耳机拔插和 Mac B 运行仍未完成。

MicForYou 不修改 macOS 默认输入，也不实现 ASR。日常链路仍是：

```text
MacBook Air Microphone → REAL-TSE/ONNX → BlackHole 2ch → 豆包输入法
```

## 已配置的 Mac A

本机配置保存在：

```text
~/Library/Application Support/MicForYou/config.json
```

配置已通过 `status` 和 5 秒真实设备 smoke test。它引用本地 enrollment、个性化 ONNX 和官方 REAL-TSE 虚拟环境；这些私有或大型文件不会上传 GitHub。

## 每次使用

1. 在豆包输入法中选择 `BlackHole 2ch`。
2. 在项目目录运行：

```bash
uv run micforyou status
uv run micforyou run
```

3. `status` 必须显示 `"ready": true`。运行窗口保持打开。
4. 停止时按 `Control-C`，然后按需把豆包麦克风恢复为日常物理麦克风。

MicForYou 从不修改系统默认输入，所以“恢复原输入”只涉及豆包自己的设备选择。

## 故障策略

- `silence`：默认、隐私优先。有限恢复仍失败后保持静音。
- `passthrough`：连续优先。有限恢复仍失败后，把同一个已选实体麦克风原音送到 BlackHole。终端会立即并每 30 秒重复显示 `UNFILTERED` 警告，报告标记 `degraded=true` 和 `final_mode=passthrough`。

切换策略需重新运行一次 `configure`，不能在运行中静默切换。不会自动选择另一支麦克风。

## 重新注册

在安静环境中运行：

```bash
uv run micforyou enroll
```

程序录制 45 秒候选语音，自动选择最高 RMS 的 6 秒窗口，在本地重新导出个性化 ONNX，并执行 100 块 Torch/ONNX 数值对照。只有 `PASS` 才会替换当前 enrollment 和 ONNX；旧文件会加时间戳备份。失败候选和报告留在本地供诊断，不会上传。

## 已知限制

- REAL-TSE 源码/权重尚无足够清晰的统一分发许可，当前只作为本机原型，不能宣称可商业分发。
- Mac A 30 分钟峰值 RSS 约 1.03 GB，后续应优化；Mac B M1 不能使用这套性能结论。
- 真实可拔插耳机的断连/重连仍待 AT-10 补测。
- 当前是 CLI MVP，没有菜单栏常驻状态；终端必须保持可见，尤其是连续优先模式的警告。
- 当前 `Control-C` 会安全停止并释放麦克风；独立的“暂停后原地继续”按钮尚未实现，属于原生 UI 阶段待办。

## 卸载/恢复

停止进程并将豆包输入改回物理麦克风即可恢复日常使用。配置文件可以保留；若要完全移除，先备份需要保留的 enrollment，再删除应用配置和本地模型。BlackHole 是否卸载由用户单独决定，MicForYou 不自动删除音频驱动。
