# Handoff：在 Mac A 完成性能分级与延迟测量

将本文件原样交给接手的 Agent。任务只在当前 Mac A 上完成；**不要等待 Mac B，也不要尝试 SSH、远程控制或推断 Mac B 的性能**。

## 项目与边界

仓库：`https://github.com/chenerzhong123-cloud/micforyou.git`，主分支当前包含 Mac B 的离线录音评估和当前 Mac 的 BlackHole → 豆包 A/B 验收。

MicForYou 的链路是：实体麦克风 → 48 kHz/16 kHz 流式重采样 → 声纹条件 REAL-TSE → BlackHole 2ch → 豆包输入法。豆包是唯一 ASR；**禁止实现、调用或接入任何新的 ASR**。不能记录或提交日常麦克风音频、声纹录音、模型权重或转写隐私内容。模型目前只适用于本机研究验证，不可重新分发。

保留这些安全性质：

- 输入必须是显式实体麦克风，输出必须显式为 `BlackHole 2ch`；拒绝 BlackHole 作为输入和同设备回环。
- 故障、队列溢出或推理异常时只输出静音，绝不透传原始麦克风，也不自动换麦。
- 不修改系统默认输入/输出；豆包的 BlackHole 选择由用户手动完成。
- 不把 Mac A 的性能结论写成 Mac B 或通用用户设备结论。

先完整阅读 `DESIGN.md`、`SPEC.md`、适用的 `AGENTS.md`、`docs/STAGE_C.md`，再改代码。

## 已知事实（不要重复探索）

- 当前 Mac A：MacBook Air M5 / 16 GB；BlackHole 2ch 已安装并验证能送入豆包。
- Mac B：只有离线录音和受控转写证据，没有实时运行、延迟或稳定性数据。
- 选定模型是 REAL-TSE `tfmap_context_causal_100`，源码提交 `2a540977a348fbaa92e623210505430e2cec608d`；权重 SHA-256 为 `97c01b79b0cf1a5b914a4a3bc1113c1864752ebdd320f528e77a53202447fef2`。
- 官方隔离环境在当前机 artifact 区：`/Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse/.venv-official`。
- `experiments/run_real_tse_bridge.py` 已有显式 `--frames-per-chunk`，刻意没有默认值。
- 完整离线桥的现实负载数据：8 frames RTF 约 1.42、p95 92.50 ms，无法稳定实时；16 frames RTF 约 0.92、p95 119.97 ms；24 frames RTF 约 0.70、p95 141.18 ms。24 frames 的推断核心预计延迟约 357 ms，叠加设备和豆包缓冲可能超过 500 ms。
- 最难 Mac B 派生离线音频的 125 s / 24-frame soak：RTF 0.670、p95 136.10 ms、max 226.34 ms、长度精确匹配、无非有限数据。
- 现有单元测试：`uv run pytest -q`，此前为 6 passed。

## 本次目标

在 Mac A 完成下面三项。它们是工程能力与可移植性工作，不是 Mac B 最终验收。

### 1. 性能分级与启动前 benchmark

实现可重复的本机 benchmark，至少比较 8、16、24 frames（可增加合理候选值）。它必须覆盖完整的 48 kHz → 16 kHz → TSE → 16 kHz → 48 kHz 路径，而不是只测模型 forward。

输出机器可读 JSON，至少包含：设备/系统信息、输入音频属性、frames、RTF、模型调用 p50/p95/max、处理块数、输出长度匹配、非有限样本、peak、错误与运行时间。不要把音频写入 Git。

根据 benchmark 结果实现一个**明确、可解释的建议函数或 CLI**，只返回以下之一：

- `fast`：有充足 headroom 的最低延迟候选；
- `balanced`：默认建议，RTF 必须有保守余量；
- `conservative`：更大 chunk，优先连续性；
- `unsupported`：没有候选能安全实时，拒绝建议运行。

不要伪造自动调参：输出建议和依据即可，实际 live bridge 仍应要求用户显式传 `--frames-per-chunk`，除非你能通过测试证明新的显式选择机制安全且不破坏现有约束。

### 2. 可审计的延迟测量

实现或补齐一个能在 Mac A 重复运行的**音频链路延迟**测量工具。它需要测量“送进 bridge 的音频时间点”到“bridge 写到 BlackHole 输出的音频时间点”的分布（p50/p95/max），并明确区分：

- 可自动测量的 MicForYou 音频路径延迟；
- 不能由本项目可靠自动测量的豆包解码/界面延迟。

不能把豆包文本出现时间伪装成纯音频实时延迟；若要纳入豆包，只能作为用户手动记录的单独端到端体验指标。测量工具应使用合成脉冲、时间戳或其他不含用户语音的方法，避免录音隐私。说明测量误差、时钟边界和无法覆盖的 CoreAudio/豆包部分。

如果 BlackHole 的单设备限制使自动回采不可行，不要绕过安全限制。实现 bridge 内部可审计的时间戳统计，并把 BlackHole/豆包外部部分明确列为手动验收项目。

### 3. Mac A 压力、稳定性与故障保护

在不需要 Mac B 或私有录音的前提下，扩展现有离线/模拟路径：

- 至少一次 30 分钟等价的完整路径 soak；若真实时间成本太高，可提供明确标记为模拟/加速的快速测试，但不得用它替代真实 30 分钟结论。
- 队列压力、模型异常和无效设备/回环配置的测试或可复现故障演练。
- 验证异常时输出为静音，绝不出现原始输入直通。

若需要用户操作实际 BlackHole 或豆包，先停止并把操作集中写进文档；不要反复打断用户。

## 交付要求

1. 代码、测试与说明文档全部提交到 Git；提交前运行 `uv run pytest -q`、相关脚本的 smoke test 和 `git diff --check`。
2. 输出报告必须分开写：`Mac A 已验证`、`Mac B 未验证`、`全用户设备仍未知`。
3. 更新 `docs/STAGE_C.md`，但不得把 Stage C 标为 PASS，除非 SPEC.md 的 AT-07 至 AT-10 真实完成。
4. 新增一个短文档，说明用户面对不同性能设备时如何运行 benchmark、怎样选择 fast/balanced/conservative、何时拒绝启用。
5. 所有报告、结果 JSON、模型和音频放在 `/Users/deuce/claudeproject/codexworks/micforyou/` 或本机忽略路径，不入 Git。
6. 最终回复必须给出：提交 hash、变更文件、运行过的命令和结果、尚不能得出的结论，以及下一次 Mac B 只需执行的最小验收步骤。

## 非目标

- 不做 UI 产品化、常驻菜单栏应用、自动安装器或云端服务。
- 不重新选择模型，除非当前模型在本次测试中出现可复现的正确性/安全失败；若出现，先报告证据，不要静默替换。
- 不修改、删除或上传已有个人音频和 artifact 数据。
- 不把 Mac B 录音提交到仓库。
