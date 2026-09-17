# Mac B 离线续跑包

目的：在不能 SSH、不能共享桌面的 Mac B 上，独立完成真实耳机 → TSE → BlackHole → 豆包的后续验收。Git 只传脚本和文档；模型、录音、运行 JSON 与任何转写内容都不提交。

当前仓库提交的离线结论只说明：Mac B 有线耳机录音的离线 TSE 效果良好，且其离线输出可在另一台 Mac 经 BlackHole 被豆包转写。它**不**说明 Mac B 本机已经跑过实时链路、延迟或稳定性。以下流程已并入 2026-09-16 Mac A 真机验收的全部教训（提交 `191ad63`），照此执行即可，无需其他上下文。

## 在 Mac B 初始化

安装 Xcode Command Line Tools、Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)，然后执行：

```bash
git clone https://github.com/chenerzhong123-cloud/micforyou.git
cd micforyou
uv sync --extra dev
uv run pytest -q          # 应为 30 passed
uv run python tools/mac_b_handoff.py --output handoff/mac-b-inventory.json
```

将 `handoff/mac-b-inventory.json` 用 AirDrop、USB 或你认可的同步方式带回本任务。它只含 macOS、仓库提交和音频设备清单，不含录音。先检查其中同时存在有线耳机麦克风与 `BlackHole 2ch`；如果缺失，先安装 BlackHole 并按安装器要求重启，不要继续做实时测试。

需要授予的权限集中如下：

1. Terminal（或你执行命令的终端）获得 macOS「麦克风」权限。**验证方法**：录 5 秒并持续说话，若 `peak` 为 0.0 说明权限未授予（macOS 对无权限应用喂纯零，不报错）；去 系统设置 → 隐私与安全性 → 麦克风 手动打开，或删除该 App 的记录让弹窗重现。
2. 豆包输入法获得它正常语音输入所需的权限。
3. 豆包输入法设置 → 语音输入 → 麦克风选择 `BlackHole 2ch`（仅在阶段 3 实时测试时切换，平时保持物理麦克风）。不要修改系统声音输出；耳机仍应是系统输出。

## 录音资产

已采集的三段 Mac B 录音没有上传到 Git。这是正确的：它们属于个人声纹数据。若本机仍保留此前的 `micforyou-device-b-*.zip`，解压后保存在 Mac B 的私有目录即可；若不存在，重新录制：

```bash
open tools/capture_kit/run.command
```

选择有线耳机麦克风，绝不选择 `BlackHole`。该工具会输出一个含三段 WAV 与 `manifest.json` 的 zip；音频只在你明确要交给后续离线评估时，通过 AirDrop/USB 传回，绝不 `git add`。

## 获取研究模型（不进入 Git）

REAL-TSE 的源码和权重不属于本仓库。其权重许可证未明确，所以只可作本机研究验证，不能二次分发。

```bash
mkdir -p "$PWD/local-models"
git clone https://github.com/REAL-TSE/wesep-real-tse.git "$PWD/local-models/wesep-real-tse"
git -C "$PWD/local-models/wesep-real-tse" checkout 2a540977a348fbaa92e623210505430e2cec608d
uv venv --python 3.12 "$PWD/local-models/wesep-real-tse/.venv-official"
uv pip install --python "$PWD/local-models/wesep-real-tse/.venv-official/bin/python" -r experiments/requirements-real-tse.txt
```

按 [REAL-TSE 官方 README](https://github.com/REAL-TSE/wesep-real-tse/tree/2a540977a348fbaa92e623210505430e2cec608d) 的 Google Drive 链接下载预训练包，解压后应有：

```text
local-models/wesep-real-tse/pretrained/tfmap_context_causal_100/avg_model.pt
local-models/wesep-real-tse/pretrained/tfmap_context_causal_100/config.yaml
```

校验权重，只有结果为下列 SHA-256 才继续：

```bash
shasum -a 256 local-models/wesep-real-tse/pretrained/tfmap_context_causal_100/avg_model.pt
# 97c01b79b0cf1a5b914a4a3bc1113c1864752ebdd320f528e77a53202447fef2
```

## 阶段 1 · Mac B 性能分级（无需语音，约 8 分钟）

Mac B 没有任何实时性能数据，且 Mac A 实测同一配置的 RTF 在同一天可波动 0.51↔1.42、用户正常使用电脑时模型每调用慢约一倍——所以**不要照搬任何帧数，先在本机实测**，并在"正常使用状态"（后台照常开着）下测，不要刻意清空负载：

```bash
local-models/wesep-real-tse/.venv-official/bin/python experiments/benchmark_real_tse.py \
  --repo "$PWD/local-models/wesep-real-tse" \
  --model-dir "$PWD/local-models/wesep-real-tse/pretrained/tfmap_context_causal_100" \
  --audio-seconds 60 --frames 8 16 24 32 \
  --result handoff/mac-b-benchmark.json
```

记下 JSON 中 `recommendation.frames_per_chunk`（记为 `<N>`）。若等级是 `unsupported`：停止，带回 JSON 即可，本机不适合实时启用。否则对 `<N>` 做配速复核：

```bash
local-models/wesep-real-tse/.venv-official/bin/python experiments/measure_bridge_latency.py \
  --repo "$PWD/local-models/wesep-real-tse" \
  --model-dir "$PWD/local-models/wesep-real-tse/pretrained/tfmap_context_causal_100" \
  --enrollment "/ABSOLUTE/PATH/TO/enrollment_b.wav" \
  --frames-per-chunk <N> --duration 120 \
  --result handoff/mac-b-paced.json
```

`status` 必须为 `COMPLETED` 且 `errors` 为空才继续；出现 `FAULT` 换更大帧数重测一次，仍失败则带回两个 JSON 停止。判定标准详见 `docs/PERFORMANCE_GUIDE.md`（注意：该工具只能筛掉明显不达标配置，不能证明 AT-07 通过）。2026-09-17 的 M1 Mac B 两次 upstream 单线程 benchmark 均为 `unsupported`，所以不要安装 BlackHole 或强行继续 live。先在最新版仓库做一次短线程扫描：

```bash
for n in 2 4; do
  local-models/wesep-real-tse/.venv-official/bin/python experiments/benchmark_real_tse.py \
    --repo "$PWD/local-models/wesep-real-tse" \
    --model-dir "$PWD/local-models/wesep-real-tse/pretrained/tfmap_context_causal_100" \
    --audio-seconds 10 --frames 8 16 24 32 --torch-threads "$n" \
    --result "handoff/mac-b-benchmark-threads-${n}.json"
done
```

若 2/4 threads 仍全部 `unsupported`，当前 PyTorch CPU 后端的 M1 结论即确认，停止 live 并转向更轻模型/后端。若出现受支持候选，用相同 `--torch-threads` 重跑 60 秒 benchmark，再把该参数原样带入 paced 与 live 命令。详见 `docs/MAC_B_20260917_RESULTS.md`。

## 阶段 2 · 豆包句尾基线对照（需要说话，不用 bridge，约 10 分钟）

Mac A 发现链路中间歇性丢失句尾，但缺少豆包直连基线无法归因。**豆包保持物理麦克风（不切 BlackHole）**，用惯用操作对以下三句各录入 3–5 次，逐字复制结果到 `handoff/doubao-baseline.txt`，并标注每次首字/句尾是否完整：

2026-09-17 当前 Mac B 轮次中，用户选择跳过此基线，并确认可假定直连录制清晰完整。该陈述只记作用户预期，不算 AT-08 实测证据；不会阻塞 CPU/模型性能工作。

1. `现在测试第一句话。`
2. `轻声说话也需要保留开头和结尾。`
3. `最后一句用于检查停止录音会不会截断尾音。`

## 阶段 3 · 实时链路验收（需要说话，约 45 分钟）

先运行阶段 1 的 benchmark 与配速复核；只有建议不是 `unsupported` 且没有 `FAULT` / 持续 underrun 才继续。将豆包切到 `BlackHole 2ch`。注册语音讲稿与朗读文本可直接复用 `docs/MAC_A_LIVE_SESSION.md` 中的三段（45 秒注册 / 两分钟连续 / 三短句）。

不要跳到 30 分钟测试。先以 120 秒启动，确认不会回环、不会透传原始麦克风、输出设备确为 BlackHole：

```bash
local-models/wesep-real-tse/.venv-official/bin/python experiments/run_real_tse_bridge.py \
  --repo "$PWD/local-models/wesep-real-tse" \
  --model-dir "$PWD/local-models/wesep-real-tse/pretrained/tfmap_context_causal_100" \
  --enrollment "/ABSOLUTE/PATH/TO/enrollment_b.wav" \
  --input-device "EXACT WIRED-HEADSET MICROPHONE NAME" \
  --frames-per-chunk <N> \
  --duration 120 \
  --result handoff/live-120s.json
```

`<N>` 必须是阶段 1 的建议值，不要照抄示例数字。若 `live-120s.json` 的 `model_call_ms_p95` 超过 `model_chunk_ms`、或出现 `FAULT`：停止，携带 JSON 回来分析；不要把 chunk 增大后直接宣称低延迟。

120 秒通过后，同参数 `--duration 1800` 完成 30 分钟测试，结果存 `handoff/live-1800s.json`。运行期间用豆包录入阶段 2 的三句短语各至少 3 次，逐字复制到 `handoff/doubao-transcripts.txt`（连同每次首字/句尾/秒表秒数）。**Mac A 教训**：若豆包中途从出字变为无反应，记下发生时间并保留终端里的完整 JSON——这是 CoreAudio 挂起的特征证据（Mac A 上两次复现，均发生在多轮按键录入之后）；不要重启音频服务后再当无事发生，先把证据存下来。结束后把豆包麦克风切回物理麦克风并确认正常。

包含工作内容、姓名或隐私的录音和转写都不要传入 Git。

## 需带回本任务的最小包

```text
handoff/mac-b-inventory.json          # 必需：设备与环境
handoff/mac-b-benchmark.json          # 必需：Mac B 性能分级
handoff/mac-b-paced.json              # 仅 benchmark 支持实时后才会存在
handoff/live-120s.json                # 仅 paced 复核通过后才会存在
handoff/live-1800s.json               # 仅 120 秒 live 通过后才会存在
handoff/doubao-baseline.txt           # 必需：AT-08 归因基线
handoff/doubao-transcripts.txt        # 仅非敏感测试句的逐字输出
```

如果实时桥无法启动，也带回终端错误文本、`mac-b-inventory.json` 和所用命令；不要传回模型目录或声纹录音。收到这些无音频资料后，就可以继续判断 AT-07 至 AT-10，并决定是否需要重新录制或调整 chunk。
