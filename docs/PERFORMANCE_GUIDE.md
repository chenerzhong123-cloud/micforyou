# 性能分级与启动前检查指南

面向要在某台具体 Mac 上运行 MicForYou 实时桥的操作者（用户本人或 Agent）。日期：2026-09-15。结论按"当前这台机器、当前这次运行"理解；任何 Mac 在每次启用前都应重新执行第 1 步。

## 为什么每次启用前都要 benchmark

同一台 MacBook Air M5 在 2026-09-15 当天不同时段的 8-frame 完整路径 RTF 实测值在 1.42 与 0.51 之间波动，差异完全来自后台桌面负载与电源状态。任何"上次能跑"的经验都不能代替本次测量，这也是 live bridge 刻意要求显式 `--frames-per-chunk`、没有默认值的原因。benchmark 与建议函数不会替你启动服务。

## 第 1 步：运行全路径 benchmark

覆盖完整 48 kHz → 16 kHz → TSE → 16 kHz → 48 kHz 路径（不是只测模型 forward），输入是进程内确定性合成音频，不含任何人声，也不写任何音频文件：

```bash
cd /Users/deuce/claudeproject/productlearning/micforyou
/Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse/.venv-official/bin/python \
  experiments/benchmark_real_tse.py \
  --repo /Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse \
  --model-dir /Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse/pretrained/tfmap_context_causal_100 \
  --audio-seconds 60 --frames 8 16 24 32 \
  --result /Users/deuce/claudeproject/codexworks/micforyou/runs/benchmark.json
```

JSON 包含设备/系统信息（芯片、电源、负载）、输入属性、每个帧数候选的 RTF、模型调用 p50/p95/max、块数、输出长度匹配、非有限样本数、peak、错误与运行时间。只看 `recommendation` 一段即可得到建议。

也可以从已有 benchmark JSON 单独重算建议：`uv run micforyou recommend-frames --benchmark .../benchmark.json`。

## 第 2 步：读懂建议等级

| 等级 | 含义 | 判定（可解释，阈值在 JSON 中一并输出） |
| --- | --- | --- |
| `fast` | 有充足余量的最低延迟候选 | RTF ≤ 0.60，且 p95 模型调用能在一个 chunk 间隔内完成，且核心延迟估计 ≤ 350 ms |
| `balanced` | 默认建议 | RTF ≤ 0.80（≥ 20% 余量），核心延迟估计 ≤ 350 ms |
| `conservative` | 更大 chunk，优先连续性 | RTF ≤ 0.90，核心延迟估计 ≤ 400 ms；取满足条件的最大帧数 |
| `unsupported` | 没有候选能安全实时 | 拒绝建议运行；不要挑一个"最接近"的值硬跑 |

核心延迟估计 = 24 ms STFT 等待 + 帧数 × 8 ms 批等待 + p95 模型调用，是**下界**：它不含队列排队、CoreAudio、BlackHole 和豆包缓冲。350/400 ms 预算对应 SPEC AT-07 的 500 ms 端到端目标减去 150/100 ms 外部预留。

任何候选一旦出现错误、输出长度不匹配、非有限样本、或模型调用次数不足以稳定分位数（< 10 次），直接判无效并在 reasons 里说明，不参与分级。

## 第 3 步：用配速延迟工具复核（必须，benchmark 不能替代）

benchmark 看不到实时队列动态。Mac A 实测：16-frame benchmark RTF 0.37、核心估计 198 ms，但配速运行中 bridge 内部 p95 达 341 ms——差值来自排队与突发排放，只有实时配速能暴露。复核命令（同样只用合成脉冲，无隐私音频）：

```bash
.../.venv-official/bin/python experiments/measure_bridge_latency.py \
  --repo ... --model-dir ... --enrollment .../target-enrollment.flac \
  --frames-per-chunk <候选值> --duration 120 \
  --result /Users/deuce/claudeproject/codexworks/micforyou/runs/latency.json
```

判断标准：若 `bridge_latency.latency_ms_p95` 已接近 500 ms，MicForYou 内部路径本身就没有足够余量，应换更小的候选重测或拒绝启用。出现 `status: FAULT` 或持续 underrun 时，该候选也不可用。CoreAudio、BlackHole → 豆包和豆包本身的时间尚未自动测量，因此这个工具只能筛掉明显不可能达标的配置；它**不能**单独判定 SPEC AT-07 的端到端 p95≤500 ms 已通过。

该工具加 `--duration 1800` 即 30 分钟实时配速模拟 soak（见 `docs/STAGE_C.md`）。

## 第 4 步：明确哪些部分不能自动测量

- **能自动测**：进入 bridge 的音频时间点 → bridge 写出音频时间点（MicForYou 音频路径内部延迟），以及 BlackHole 设备回环（当前 Mac A 环境回采失效，见 STAGE_C）。
- **不能自动测**：CoreAudio 采集硬件缓冲、BlackHole → 豆包传递、豆包解码/界面。豆包文字出现时间只能由用户手动记录为**单独的端到端体验指标**，绝不能当作音频实时延迟报告。

需要人工的操作（一次性集中完成，不要反复打断用户）：

1. 用惯用方式对豆包说短句，手动记录“说完 → 文字出现”的秒数，作为单独的用户体验指标。不要从该值减去 `bridge_latency`：二者的起点不同，且前者还包含豆包的断句、静音判定、解码和 UI 行为，差值没有可解释性。
2. 若要验证 BlackHole 回采，重启后跑 `uv run micforyou probe-loopback .../route-test.wav`，正常应得到接近 2026-09-13 基线（256 ms、gain≈1.0）。

## 何时拒绝启用

- benchmark 建议 `unsupported`；
- 建议候选在配速复核中 FAULT、持续 underrun，或 bridge 内部 p95 已 ≥ 400 ms（几乎必然超 AT-07）；
- 机器使用电池且 RTF 接近阈值（电池功率下性能可能进一步下降，当前工具会记录电源状态但不自动降级）。

拒绝启用不是失败：输出静音、不透传原始麦克风是本项目的强制安全语义，宁可不跑也不带病运行。

## Mac A 结果快照（2026-09-15，AC 电源，负载约 3.5）

**Mac A 已验证**：benchmark 与建议函数可重复运行（fast/8，核心估计 121.5 ms）；配速延迟 8f p95 202 ms、16f p95 341/341 ms、24f p95 381/430 ms；故障静音语义有单元测试覆盖；30 分钟 16f 模拟 soak 见 STAGE_C。BlackHole 自动回采当前失效（9-13 正常、9-15 静音），已列为环境项。

**Mac B 已完成当前 REAL-TSE 的性能淘汰**：Mac B M1 的 PyTorch、ORT CPU 和 corrected CoreML benchmark 均未通过实时门槛，Dynamic INT8 还失败 correctness；最佳有效结果为 CoreML 24f/4 threads 的 RTF 1.052。因此不要再对该模型执行第 2–3 步或 live/soak，结论为 `CURRENT REAL-TSE ON M1: STOP`。这不代表 Mac B 硬件永久不支持 MicForYou；替换为新模型后必须从第 1 步重新分级。

**全用户设备仍未知**：现有样本覆盖 Mac A 和一台 M1 Mac B，但不同芯片、内存、负载与麦克风组合下的分布仍未测量，不能宣称通用性能。

## 边界提醒

- 建议函数只输出建议；live bridge 仍要求显式 `--frames-per-chunk`，本项目没有也不做运行时自动调参。
- 所有结果 JSON、日志、音频都在 `/Users/deuce/claudeproject/codexworks/micforyou/` 或本机忽略路径，不入 Git。
- 本链路唯一的 ASR 是豆包；本指南工具全部使用合成信号，不引入也不调用任何识别能力。
