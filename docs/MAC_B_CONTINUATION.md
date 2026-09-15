# Mac B 离线续跑包

目的：在不能 SSH、不能共享桌面的 Mac B 上，独立完成真实耳机 → TSE → BlackHole → 豆包的后续验收。Git 只传脚本和文档；模型、录音、运行 JSON 与任何转写内容都不提交。

当前仓库提交的离线结论只说明：Mac B 有线耳机录音的离线 TSE 效果良好，且其离线输出可在另一台 Mac 经 BlackHole 被豆包转写。它**不**说明 Mac B 本机已经跑过实时链路、延迟或稳定性。

## 在 Mac B 初始化

安装 Xcode Command Line Tools、Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)，然后执行：

```bash
git clone https://github.com/chenerzhong123-cloud/micforyou.git
cd micforyou
uv sync --extra dev
uv run pytest -q
uv run python tools/mac_b_handoff.py --output handoff/mac-b-inventory.json
```

将 `handoff/mac-b-inventory.json` 用 AirDrop、USB 或你认可的同步方式带回本任务。它只含 macOS、仓库提交和音频设备清单，不含录音。先检查其中同时存在有线耳机麦克风与 `BlackHole 2ch`；如果缺失，先安装 BlackHole 并按安装器要求重启，不要继续做实时测试。

需要授予的权限集中如下：

1. Terminal（或你执行命令的终端）获得 macOS「麦克风」权限。
2. 豆包输入法获得它正常语音输入所需的权限。
3. 豆包输入法设置 → 语音输入 → 麦克风选择 `BlackHole 2ch`。不要修改系统声音输出；耳机仍应是系统输出。

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

## 实时验收顺序

不要跳到 30 分钟测试。先以 120 秒启动，确认不会回环、不会透传原始麦克风、输出设备确为 BlackHole：

```bash
uv run micforyou devices
local-models/wesep-real-tse/.venv-official/bin/python experiments/run_real_tse_bridge.py \
  --repo "$PWD/local-models/wesep-real-tse" \
  --model-dir "$PWD/local-models/wesep-real-tse/pretrained/tfmap_context_causal_100" \
  --enrollment "/ABSOLUTE/PATH/TO/enrollment_b.wav" \
  --input-device "EXACT WIRED-HEADSET MICROPHONE NAME" \
  --frames-per-chunk 16 \
  --duration 120 \
  --result handoff/live-120s.json
```

`16` 是起始探针，不是最终配置。若 `live-120s.json` 的 RTF 接近或超过 1，先停止，携带该 JSON 回来分析；不要把 chunk 增大后直接宣称低延迟。若稳定，再分别用 `--duration 1800` 完成 30 分钟测试，并以同样方式保存 JSON。

豆包验收时，用文档 [Stage A](STAGE_A.md) 的三句短语，逐次复制出转写结果到一个本地纯文本文件；再把文本与 `handoff/*.json` 一起带回。包含工作内容、姓名或隐私的录音和转写都不要传入 Git。

## 需带回本任务的最小包

```text
handoff/mac-b-inventory.json          # 必需：设备与环境
handoff/live-120s.json                # 必需：首次实时桥结果
handoff/live-1800s.json               # 完成 30 分钟后提供
doubao-transcripts.txt                # 仅非敏感测试句的逐字输出
```

如果实时桥无法启动，也带回终端错误文本、`mac-b-inventory.json` 和所用命令；不要传回模型目录或声纹录音。收到这些无音频资料后，就可以继续判断 AT-07 至 AT-10，并决定是否需要重新录制或调整 chunk。
