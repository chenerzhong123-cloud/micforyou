# 从 GitHub 安装 MicForYou

[English](INSTALL.en.md) · [返回 README](../README.md)

当前版本需要 Terminal 与本地模型设置；适合有 Python / Git 使用经验的用户。本指南使用用户自己的目录，不依赖开发者机器上的 `/Users/deuce/...` 路径。菜单栏界面要求 macOS 14+；当前模型在 M5 上验证过，在 M1 上未达到实时门槛。源码和应用外壳均不带模型权重。

## 1．准备工具和源码

安装 Apple Command Line Tools；系统已有时无需重复：

```bash
xcode-select --install
```

按 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/) 安装 uv。如果已使用 Homebrew：

```bash
brew install uv
```

取得仓库访问权限后，克隆源码并安装控制环境：

```bash
git clone https://github.com/chenerzhong123-cloud/micforyou.git
cd micforyou
uv sync --extra dev
```

以下步骤都在这个项目目录执行。也可以使用 GitHub 的源码 ZIP；更新时重新下载源码，并将配置指向保留的项目目录。不要删掉项目 `.venv` 或移动配置引用的源码目录。

## 2．安装音频路由

从 [BlackHole 官方网站](https://existential.audio/blackhole/) 安装 **2ch** 版本，或使用 [Homebrew 官方 cask](https://formulae.brew.sh/cask/blackhole-2ch)：

```bash
brew install --cask blackhole-2ch
```

安装后重启 Mac，再运行 `uv run micforyou devices`，确认有 `BlackHole 2ch` 和日常实体麦克风。MicForYou 内部将音频送往 BlackHole，豆包输入选择它；系统输出继续保留日常扬声器 / 耳机。

## 3．准备独立模型环境

定义本机路径。后续重新打开 Terminal 时，需要在项目目录重设这些变量：

```bash
MFY_ROOT="$PWD"
MFY_DATA="$HOME/Library/Application Support/MicForYou/data"
MFY_REPO="$MFY_DATA/wesep-real-tse"
MFY_MODEL="$MFY_REPO/pretrained/tfmap_context_causal_100"
MFY_RUNTIME="$MFY_DATA/runtime"
MFY_VOICE="$MFY_DATA/voice/enrollment.wav"
MFY_ONNX="$MFY_DATA/voice/personalized.onnx"
mkdir -p "$MFY_DATA/voice" "$MFY_DATA/reports"
git clone https://github.com/REAL-TSE/wesep-real-tse.git "$MFY_REPO"
git -C "$MFY_REPO" checkout 2a540977a348fbaa92e623210505430e2cec608d
uv venv --python 3.12 "$MFY_RUNTIME"
uv pip install --python "$MFY_RUNTIME/bin/python" -r requirements-runtime.txt
```

控制环境与模型环境分开：不要把上游旧版 `requirements.txt` 直接装到项目 `.venv`。`requirements-runtime.txt` 固定本项目的模型依赖版本；安装需要网络。Python 包可能包含上游的其他模型依赖，MicForYou 不调用 ASR。

从 [REAL-TSE 上游 README 的 pretrained model 部分](https://github.com/REAL-TSE/wesep-real-tse#2-download-pretrained-model) 自行取得权重，并按其使用条件解压。选用 **`tfmap_context_causal_100`**，不要使用非因果版本。检查以下文件存在：

```bash
test -f "$MFY_MODEL/avg_model.pt"
test -f "$MFY_MODEL/config.yaml"
```

权重的统一再分发许可尚不明确，因此 MicForYou 不重新打包或自动下载权重。上游下载不可用时，模型准备无法继续；只有 App 外壳无法替代这一步。已验证 checkpoint 的 SHA-256 与来源见 [模型记录](STAGE_B.md#license-boundary)。

## 4．注册、导出与校验

先找出日常麦克风的准确名称，再录制自己的 45 秒声音。以下变量的值需替换成设备列表里的名称：

```bash
uv run micforyou devices
MFY_MIC="你的日常实体麦克风名称"
uv run micforyou record --input-device "$MFY_MIC" \
  --output-file "$MFY_VOICE" --duration 45 --countdown 3
```

使用安静环境、自然语速，不需要训练模型。按 macOS 提示允许实际录音进程使用麦克风。注册必须来自日常使用的麦克风；不要用他人的声音。音频只写入指定的本机路径。

```bash
"$MFY_RUNTIME/bin/python" experiments/export_real_tse_onnx.py \
  --repo "$MFY_REPO" --model-dir "$MFY_MODEL" \
  --enrollment "$MFY_VOICE" --enrollment-seconds 6 \
  --output "$MFY_ONNX" --report "$MFY_DATA/reports/onnx-export.json"

"$MFY_RUNTIME/bin/python" experiments/compare_torch_onnx.py \
  --repo "$MFY_REPO" --model-dir "$MFY_MODEL" \
  --enrollment "$MFY_VOICE" --enrollment-seconds 6 \
  --onnx "$MFY_ONNX" --frames-per-chunk 8 --chunks 100 \
  --result "$MFY_DATA/reports/onnx-correctness.json"
```

最后一份报告的 `gate.verdict` 必须是 `PASS`。若失败，不要启动实时过滤。

## 5．本机性能检查与配置

运行 ONNX 全路径 benchmark，输入为合成信号，不打开真实麦克风：

```bash
"$MFY_RUNTIME/bin/python" experiments/benchmark_onnx_tse.py \
  --repo "$MFY_REPO" --model-dir "$MFY_MODEL" \
  --enrollment "$MFY_VOICE" --onnx "$MFY_ONNX" \
  --audio-seconds 60 --frames 8 16 24 32 --threads 1 \
  --result "$MFY_DATA/reports/benchmark.json"
```

报告的 `gate` 应为 CPU SUCCESS（有效候选 RTF ≤0.80）；MARGINAL / FAIL 不作为当前推荐配置。依照 [性能指南](PERFORMANCE_GUIDE.md) 判断是否有足够实时余量，并用 `measure_bridge_latency.py` 做配速复核。`unsupported`、FAULT、持续 underrun 或过高延迟时，不要强行开始。下面的 `MFY_FRAMES=8` 只是已验证 M5 的示例；必须改为本机实际通过的候选。其他候选的 ONNX correctness 和配速检查也需按相同帧数重做。

```bash
MFY_FRAMES=8
uv run micforyou configure \
  --input-device "$MFY_MIC" --output-device "BlackHole 2ch" \
  --model-repo "$MFY_REPO" --model-dir "$MFY_MODEL" \
  --enrollment "$MFY_VOICE" --onnx "$MFY_ONNX" \
  --runtime-python "$MFY_RUNTIME/bin/python" --project-root "$MFY_ROOT" \
  --frames-per-chunk "$MFY_FRAMES" --onnx-threads 1 --fault-policy silence
uv run micforyou status
```

`ready: true` 仅说明路径和设备齐全，不等于性能或过滤质量已通过。首次使用和环境负载变化后都应参考本机性能结果。

## 6．安装应用、选择输入

```bash
./app/MicForYouMenuBar/install_app.sh
```

它构建并安装 `~/Applications/MicForYou.app`，保留配置与模型，不加开机启动项。构建需要 Swift 6+ 工具链；若 `swift --version` 低于 6，请更新 Apple 开发工具。菜单栏应用当前使用中文界面。

若日后下载预构建 `.app.zip`，解压后将 `.app` 放入 `~/Applications`，仍先完成步骤 1–5。预构建包不会替你创建 Python 环境或注册声音。当前构建为 ad-hoc 签名、未公证，首次打开被拦截时按 [Apple 的“仍要打开”说明](https://support.apple.com/en-us/102445) 操作。

在豆包输入法选择 `BlackHole 2ch`。若豆包没有独立设备选择器，手动在系统声音输入中选择它。点击“开始过滤”，等待“正在过滤”再口述。先用短句检查本人表达、暂停后的原音和继续后的过滤；需要结束收音时点击“结束”。

## 更新与恢复

先“结束”再退出界面。Git clone 用户执行 `git pull --ff-only`、`uv sync --extra dev`，然后重新运行 `install_app.sh`。模型依赖变化时，另外用保存的模型环境运行 `uv pip install --python "$MFY_RUNTIME/bin/python" -r requirements-runtime.txt`。通常不需要重新注册或重选豆包输入；更换实体麦克风后要重新注册并做基线。

如需回退，先停止音频，再回退源码与 App；新版 runtime-state/2 不能交给旧控制器直接读取。备份原配置后，移走停止后的 `state.json`，让旧版本重新建立状态。不要覆盖或删除注册音频来处理运行元数据问题。

更多排查与卸载步骤见 [README](../README.md)。

首次模型加载可能包含上游 JIT 编译，耗时比后续启动更长；等待实际状态就绪再口述。
