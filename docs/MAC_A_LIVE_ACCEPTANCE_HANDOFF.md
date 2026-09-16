# Handoff：Mac A 的 BlackHole 回采与真实链路验收

将本文件原样交给接手的 Agent。用户已表示 Mac A 的 BlackHole 设置已恢复；本任务要验证并利用该状态，完成当前 Mac 的真实设备验收。**不要等待 Mac B，不要改系统默认音频设备，不要 SSH 或远程控制 Mac B。**

## 前置事实与边界

- 从仓库主分支最新提交开始；先阅读 `DESIGN.md`、`SPEC.md`、适用 `AGENTS.md`、`docs/STAGE_A.md`、`docs/STAGE_C.md`、`docs/PERFORMANCE_GUIDE.md`。
- 链路是：实体麦克风 → 48 kHz/16 kHz 流式重采样 → REAL-TSE → `BlackHole 2ch` → 豆包输入法。豆包是唯一 ASR；禁止引入其他 ASR。
- 只能显式打开实体输入和 `BlackHole 2ch` 输出；拒绝 BlackHole 输入、同设备回环和自动换麦。
- 溢出、推理异常、拔耳机或停止恢复时必须输出静音，绝不透传原始麦克风。
- 不提交、不上传任何麦克风音频、声纹录音、模型权重、运行 JSON 或私人转写；它们只放在 `/Users/deuce/claudeproject/codexworks/micforyou/` 或 Git 忽略路径。
- 所有结论只能称作 Mac A 证据，不能外推到 Mac B 或其他用户设备；Stage C 不得改为 PASS。

## 1. 验证 BlackHole 自动回采

只做验证，不改 Audio MIDI Setup 或 macOS 默认输入/输出：

```bash
uv run micforyou devices
uv run micforyou prepare-audio
uv run micforyou probe-loopback \
  /Users/deuce/claudeproject/codexworks/micforyou/test-data/route-test.wav \
  --result /Users/deuce/claudeproject/codexworks/micforyou/runs/mac-a-loopback-YYYYMMDD.json
```

验收：`BlackHole 2ch` 可见，结果包含非静音回采、lag、gain、相关性和 SNR。与 2026-09-13 的约 256 ms、gain≈1、SNR≈99.68 dB 基线并列记录。若仍为静音或命令失败：保存完整 JSON / 终端错误，标为环境未恢复；停止本子项，**不要**靠改默认设备或隐式回环绕过。后续真实桥路可继续，但 AT-07 自动外部测量仍未完成。

## 2. Mac A 真实 120 秒 bridge

先运行性能建议与配速复核。当前负载改变时，按 `docs/PERFORMANCE_GUIDE.md` 重跑 full-path benchmark 和 120 秒配速检查；只有建议不是 `unsupported` 且没有 `FAULT` / 持续 underrun 才继续。

```bash
uv run micforyou recommend-frames --benchmark \
  /Users/deuce/claudeproject/codexworks/micforyou/runs/20260915-benchmark-frames.json
```

从 `uv run micforyou devices` 复制精确的**实体**输入名。仅当本人说话或豆包操作必需时，集中请求用户一次：连接常用耳机或指定物理麦克风；在豆包语音设置选择 `BlackHole 2ch`；准备连续讲话两分钟。不要要求用户修改系统默认输出。

```bash
/Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse/.venv-official/bin/python experiments/run_real_tse_bridge.py \
  --repo /Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse \
  --model-dir /Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse/pretrained/tfmap_context_causal_100 \
  --enrollment "/ABSOLUTE/PATH/TO/PRIVATE/enrollment.wav" \
  --input-device "EXACT PHYSICAL MICROPHONE NAME" \
  --frames-per-chunk <EXPLICITLY_BENCHMARKED_VALUE> \
  --duration 120 \
  --result /Users/deuce/claudeproject/codexworks/micforyou/runs/mac-a-live-120s-YYYYMMDD.json
```

报告状态、实际设备、模型 p50/p95/max、队列峰值、underrun、callback 状态、bridge 内部延迟和错误。`FAULT`、自动换麦、原声透传或未报告断流即失败。成功只代表 Mac A 实时 bridge，不代表豆包端到端延迟。

## 3. Mac A 真实 30 分钟与豆包句尾

仅在 120 秒通过后，以相同设备/chunk 运行 `--duration 1800`。报告 CPU/内存、队列峰值、underrun、错误和 bridge 内部 p50/p95/max；不要把模拟 soak 当作替代。

豆包验收由用户完成：运行期间用正常操作方式录入 `docs/STAGE_A.md` 的三句短语，每句至少三次，逐字复制非敏感转写。检查首字、短词、句尾与停止录音后是否新增截断。提醒用户结束后将豆包麦克风从 `BlackHole 2ch` 恢复为日常物理麦克风，并确认普通语音输入恢复。

## 4. AT-07 的正确人工记录

并列保存而不相减：

1. 工具的 `bridge_latency.latency_ms_p95`：仅进入 bridge → 写向 BlackHole 的内部路径；
2. 用户多次记录“说完 → 豆包文字出现”的秒数：完整用户体验时间。

若 BlackHole 自动回采恢复，可将其 lag 作为额外设备路径证据；它仍不是豆包 UI 时间。除非建立共同时间基准的物理端到端测量，AT-07 仍为 `PARTIAL/NOT RUN`，不得报告为 ≤500 ms 通过。

## 交付

仅在真实测试暴露可复现 bug、指标缺失或文档错误时修改代码；新增改动须有测试。提交前运行 `uv run pytest -q`、相关 smoke test 和 `git diff --check`。最终报告分为 `Mac A 已验证`、`Mac A 未验证/失败`、`Mac B 未验证`、`全用户设备未知`，列出 JSON 本地绝对路径和核心数值，但不提交 JSON/音频。AT-07 至 AT-10 未完成时保持 `PARTIAL PASS`。
