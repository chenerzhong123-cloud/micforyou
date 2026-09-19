# Mac A 真实链路验收：用户一次性操作脚本

日期：2026-09-16。给用户（或陪同 Agent）的集中操作单；全部环节一次完成，约 35–40 分钟。前置工程检查已由 Agent 完成，见文末"已就绪状态"。

## 开始前

1. **麦克风**：连接日常耳机后告知 Agent（会重新枚举设备取精确名称）；或直接用内建 `MacBook Air Microphone`（结论只代表该场景）。
2. **豆包**：豆包输入法 设置 → 语音输入 → 麦克风选择 → `BlackHole 2ch`。**不要**修改 macOS 系统默认输入/输出。

## 第 1 步：录制注册语音（约 1 分钟）

安静环境、距麦克风正常距离，用**自然中文说 45 秒**，包含正常音量和较轻音量（不要耳语），内容任意（非敏感）。3 秒倒计时后开始：

```bash
cd /Users/deuce/claudeproject/productlearning/micforyou
uv run micforyou record --input-device "精确麦克风名" \
  --output-file /Users/deuce/claudeproject/codexworks/micforyou/test-data/human/enrollment.wav \
  --duration 45
```

原始 45 秒录音会保留；ONNX 运行准备会自动选择其中最高 RMS 的 6 秒窗口并记录起止，不会把整段 45 秒放进每次实时推理。

首次注册或重录后，先在本机导出与该 6 秒窗口绑定的 ONNX（这是本地模型准备，不是训练）：

```bash
/Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse/.venv-official/bin/python experiments/export_real_tse_onnx.py \
  --repo /Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse \
  --model-dir /Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse/pretrained/tfmap_context_causal_100 \
  --enrollment /Users/deuce/claudeproject/codexworks/micforyou/test-data/human/enrollment.wav \
  --enrollment-seconds 6 \
  --output /Users/deuce/claudeproject/codexworks/micforyou/models/real_tse_core_fp32_personalized.onnx \
  --report /Users/deuce/claudeproject/codexworks/micforyou/runs/mac-a-onnx-export-personalized.json
```

## 第 2 步：120 秒真实 bridge（连续讲话 2 分钟）

启动后**立即开始连续自然讲话**（读书/自由说话均可，含轻声段落），直到程序自动结束：

```bash
/Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse/.venv-official/bin/python experiments/run_real_tse_bridge.py \
  --repo /Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse \
  --model-dir /Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse/pretrained/tfmap_context_causal_100 \
  --enrollment /Users/deuce/claudeproject/codexworks/micforyou/test-data/human/enrollment.wav \
  --enrollment-seconds 6 \
  --input-device "精确麦克风名" \
  --backend onnx \
  --onnx /Users/deuce/claudeproject/codexworks/micforyou/models/real_tse_core_fp32_personalized.onnx \
  --onnx-threads 1 \
  --frames-per-chunk 8 \
  --prefill-ms 100 \
  --duration 120 \
  --result /Users/deuce/claudeproject/codexworks/micforyou/runs/mac-a-live-120s-20260916.json
```

`8` 来自 2026-09-16 本机 benchmark 建议（fast/8）；换机器或负载大变时按 `docs/PERFORMANCE_GUIDE.md` 重测。出现 `FAULT` 或退出码 2 即失败，把 JSON 交给 Agent。

## 第 3 步：30 分钟运行 + 豆包验收（约 30 分钟）

同命令改 `--duration 1800`、结果名 `mac-a-live-30min-20260916.json`。运行期间用**惯用的豆包操作**录入以下三句（来自 `docs/STAGE_A.md`），**每句至少 3 次**：

1. `现在测试第一句话。`
2. `轻声说话也需要保留开头和结尾。`
3. `最后一句用于检查停止录音会不会截断尾音。`

每次记录四项（建议直接在旁边开备忘录）：

- 豆包**逐字**转写结果（非敏感内容）；
- 首字/短词是否缺失；
- 句尾是否被截断（尤其停止录音后）；
- "说完 → 豆包文字出现"的秒数（掐表多次，**单独记录，不要与任何工具值相减**——AT-07 规则）。

## 第 4 步：恢复

豆包 麦克风选择 恢复为日常物理麦克风，确认普通语音输入恢复正常。系统设置无需改动（本次从未改过系统默认）。

## 已就绪状态（2026-09-16，Agent 侧）

- 今日 benchmark：8/16/24f RTF 0.509/0.364/0.318，建议 **fast/8**（`runs/20260916-benchmark-frames.json`）。
- 8f 配速复核：COMPLETED，bridge 内部 p95 201.4 ms，无 FAULT（`runs/20260916-latency-8f.json`）。
- 真实设备 120s（内建麦、公开注册语料、无语音内容）：STOPPED 干净，p95 模型 37.4 ms，bridge 内部 p50/p95 200/220 ms，无故障（`runs/mac-a-device-120s-20260916.json`）——验证了设备路径，**不代替**第 2 步。
- BlackHole 自动回采**仍为静音**（`runs/mac-a-loopback-20260916.json`，gain 0.0/相关 0.0）：标为环境未恢复，AT-07 自动外部测量未完成；不要为测量改系统设置。
