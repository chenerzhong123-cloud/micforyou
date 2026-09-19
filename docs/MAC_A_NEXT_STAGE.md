# Mac A 下一阶段 TODO

日期：2026-09-19。当前范围：以 Mac A（M5）完成可用原型；Mac B（M1）只作为后续兼容性与性能优化验收，不阻塞本阶段。

## 当前固定基线

- 链路：实体麦克风 → REAL-TSE → BlackHole 2ch → 豆包输入法；豆包仍是唯一 ASR。
- Mac A 当前候选配置为 ONNX CPU、`8 frames`、`1 ORT thread`、`100 ms output prefill`、6 秒有界 enrollment。这是本机当前回归配置，不是所有设备的默认值。
- 故障策略可选 `silence`（默认）或用户明确启用的 `passthrough`；两者都先有限自动恢复，且绝不自动换到其他麦克风。
- 模型、推理后端、chunk 和线程数保持显式配置；Capture、TSE Adapter、Output、Controller、Metrics 之间不绑定具体模型，以便以后接入小模型、ONNX 或 CoreML。

## 按顺序执行

1. **发现音频链路“假运行”——代码完成，待真实回归**：监测 CoreAudio callback 心跳；超过阈值没有新 callback 就进入 `FAULT`，记录明确原因并安全结束。本项不需要用户操作。
2. **有限自动恢复与熔断——代码完成，待真实瞬时故障回归**：Controller 对块处理、队列和 callback 故障先静音，关闭旧 stream、清空音频并重建模型流状态，再显式重开原来的输入与 BlackHole 输出；5 分钟内默认最多恢复 2 次，继续失败则锁定 FAULT。禁止换麦和原声透传。本项不需要用户录音。
3. **修复停止与 drain 边界——代码完成，待真实回归**：避免停止录音时的输出 ring 突增、队列溢出或尾音被内部丢弃；用模拟负载和自动测试验证。本项不需要用户操作。
4. **Mac A 120 秒回归——ONNX 工程回归通过，用户语音待测**：`8 frames + 1 ORT thread + 100 ms prefill + 6 秒 enrollment` 完成真实设备回归；本人语音与豆包交互留到下一项集中验证。
5. **Mac A 30 分钟豆包交互验收——通过**：ONNX 链路连续完成 1800.67 秒；三次豆包启停均有完整文字。工程指标见下文。
6. **句尾 A/B——通过**：物理麦克风与 TSE/BlackHole 均保留首字和最后的“尾音”；两边都出现豆包的标点与“停止录音时”措辞变化，没有 TSE 新增截尾证据。
7. **物理故障演练——部分完成**：推理异常、队列故障、恢复熔断和可选 passthrough 已自动验证；当前没有可拔插耳机，真实设备拔插仍待后续补测。
8. **Stage C 判定**：汇总 AT-07～AT-10。达到标准才改为 `PASS`；否则保留具体失败项，不用界面包装。
9. **进入 Stage D**：提供最小启停、暂停、设备选择、重新注册、状态/错误、恢复原输入和卸载说明；不申请 Accessibility，不实现 ASR。
10. **后续性能升级轨道**：在稳定接口后替换/增加 TSE Adapter 和 runtime profile，按每台设备先 benchmark 再选 backend/chunk；Mac B 重新从质量门和实时门开始，不把 Mac A 参数直接外推。

## 下一次需要用户集中配合的时点

完成第 1～3 项自动工程验证后，再一次性请求：允许 Terminal 使用麦克风、确认豆包输入为 `BlackHole 2ch`、朗读固定文本、多次启停豆包，以及最后执行耳机拔插。此前不要求重复录音。

## 2026-09-19 自动工程回归

- 10 秒、`16 frames / 1 thread`：`STOPPED`，无 fault；bridge latency p95 `360.03 ms`。
- 120 秒、`16 frames / 1 thread`：约 72 秒 input queue overflow，正确进入故障静音并退出；说明单线程不能作为当前负载下的可靠默认值。
- 120 秒、`24 frames / 1 thread`：约 21 秒 input queue overflow，bridge latency p95 `719.98 ms`；稳定性和延迟均不合格。
- 30 秒线程复核：`16 frames / 2 threads` 与 `/ 4 threads` 均完成，性能接近，因此选择资源占用更克制的 2 threads。
- 120 秒、`16 frames / 2 threads`：`STOPPED`，无 fault、callback stall 或 stream status；模型调用 p95 `93.89 ms`，bridge latency p95 `360.07 ms`，输入队列峰值 12/50 blocks。
- 300 秒、`16 frames / 2 threads / inter-op 1 / prefill 250 ms`：稳定但 bridge p95 `500.15 ms`，不采用。
- 900 秒、`16 frames / 2 threads / inter-op 1 / prefill 150 ms`：无 fault，但出现 2 次系统 input overflow，bridge p95 `520.03 ms`，不采用为最终目标配置。
- 180 秒、`16 frames / 2 threads / inter-op 1 / prefill 100 ms`：无 fault、无 callback stall，bridge p95 `380.18 ms`，输入队列峰值 12/50 blocks；作为下一轮长时与豆包交互的候选配置。
- 900 秒、同一 `100 ms prefill` 配置：在约 883 秒时因一次输入 overflow 后的输出 burst 触发 `output queue exceeded its bound`，进入故障静音；bridge p95 当时 `499.99 ms`，另有 2 次系统 input overflow。不能据此进入 30 分钟豆包验收。

旧 PyTorch 候选在 900 秒内失败，已由 ONNX 候选替代。6 秒个性化 FP32 ONNX 的 100 块 Torch 对照 PASS；120 秒真实设备运行保持 `final_mode=tse`，模型 p95 `29.29 ms`、bridge p95 `260.16 ms`、输入队列峰值 3 blocks，且没有 fault、恢复、stream status 或 passthrough。

同配置 15 分钟稳态测试也保持 `final_mode=tse`，模型 p95 `29.24 ms`、bridge p95 `260.17 ms`、输入队列峰值 6/50 blocks，无 fault、恢复或 passthrough。前后半段 5 秒采样的输入队列均值为 0.422/0.427 blocks，output ring 均值为 6447/6436 frames，没有持续增长。CoreAudio 报告了 2 次 `input overflow`，因此当时只判为带有两次已报告输入不连续的工程稳定通过。运行 JSON 位于 `/Users/deuce/claudeproject/codexworks/micforyou/runs/`，不纳入 Git。

30 分钟豆包验收随后完成：`final_mode=tse`，无 fault、恢复、callback stall、stream status 或 passthrough；模型 p95 `29.21 ms`，bridge p95 `260.17 ms`，输入队列峰值 8/50 blocks，平均占单核 `42.50%`，峰值 RSS `1,028,014,080 bytes`。三次 TSE/BlackHole 豆包启停和一次物理麦克风基线都保留句首、句尾“尾音”；仅有相同类型的标点/措辞整理。AT-08 与 Mac A 的 AT-09 因此通过。下一项只剩真实耳机拔插 AT-10；没有耳机时不阻塞其他产品开发，但 Stage C 暂维持 `PARTIAL PASS`。

故障恢复 SLA 已补充：一次异常不会永久毒化整段会话。直接跳过坏块并沿用旧状态不安全，因此恢复单位是整个流式 pipeline；恢复期间输出静音并丢弃过期音频，之后继续当前会话。故障注入使用 50 ms ring 连续制造 overload，验证了两次自动恢复和第三次熔断，报告 `faults_recovered=2`、`total_rejected=1`。

故障策略已预留为产品配置：`silence`（隐私优先，默认）或 `passthrough`（连续优先）。连续优先仍先执行两次有限恢复；预算耗尽后停止 TSE，透传同一个 MacBook Air Microphone 到 BlackHole，并标记 `degraded=true`。故障注入验证最终进入 `final_mode=passthrough`，透传阶段完成 384 次 callback、无 stall，正常结束；音频未保存。未来 UI 必须常驻显示未过滤状态，并提供“重试过滤”。
