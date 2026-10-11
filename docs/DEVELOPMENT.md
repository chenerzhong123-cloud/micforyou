# 开发指南

[English](DEVELOPMENT.en.md) · [返回 README](../README.md)

本文面向从源码构建 MicForYou 的开发者：环境与模型准备、推理工具、测试、Swift 菜单栏应用，以及完整安装包的构建与验证。日常使用请阅读[使用指南](USAGE.md)。

## 架构概览

MicForYou 由三层组成，仓库目录与之对应：

```text
src/micforyou/            # Python 控制器：配置、设备管理、进程生命周期、CLI、首次设置
tools/inference/          # 实时推理脚本：桥接、流式实现、ONNX 导出/校验/基准/延迟测量
app/MicForYouMenuBar/     # SwiftUI 菜单栏外壳：调用控制器 CLI，不含模型逻辑
tools/verification/       # 合成输入集成验证（不打开真实麦克风）
tools/bundle/             # 完整包构建、原生依赖准备、安装包与只读验证
tools/installer/          # pkg 安装器资源与预检查脚本
tests/                    # 控制器与产品契约回归测试
licenses/                 # 第三方许可声明与全文
```

音频链路：实体麦克风 → MicForYou 实时过滤（48 kHz 采集、16 kHz 模型、48 kHz 输出）→ BlackHole 2ch 虚拟设备 → 豆包输入法。MicForYou 不实现语音识别、不输出文字，也不修改系统默认输入。运行期故障默认静音（隐私优先），主动暂停为原音直通；`tools/inference/run_real_tse_bridge.py` 是后台音频进程，`src/micforyou/product.py` 按配置中的 `project_root` 定位它——脚本目录自本仓库起固定为 `tools/inference/`，仓库与打包后的 App 内布局一致。

## 1．准备工具和源码

安装 Apple Command Line Tools（系统已有时无需重复）与 [uv](https://docs.astral.sh/uv/getting-started/installation/)：

```bash
xcode-select --install
brew install uv   # 或按 uv 官方说明安装
```

克隆源码并安装控制环境：

```bash
git clone https://github.com/chenerzhong123-cloud/micforyou.git
cd micforyou
uv sync --extra dev
```

以下步骤都在项目目录执行。重新打开 Terminal 时需重设下文的 `MFY_*` 变量；不要删掉项目 `.venv` 或移动配置引用的源码目录。

## 2．安装音频路由

安装 BlackHole **2ch**（[官方网站](https://existential.audio/blackhole/) 或 [Homebrew cask](https://formulae.brew.sh/cask/blackhole-2ch)）：

```bash
brew install --cask blackhole-2ch
```

安装后重启 Mac，运行 `uv run micforyou devices`，确认列表中有 `BlackHole 2ch` 和日常实体麦克风。

## 3．准备独立模型环境

控制器环境与模型环境分开；模型依赖固定在仓库根的 `requirements-runtime.txt`：

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

不要把上游旧版 `requirements.txt` 装进项目 `.venv`。安装需要网络；Python 包可能包含上游其他模型依赖，MicForYou 不调用 ASR。

从 [REAL-TSE 上游 README 的 pretrained model 部分](https://github.com/REAL-TSE/wesep-real-tse#2-download-pretrained-model) 自行取得权重并按其使用条件解压。选用 **`tfmap_context_causal_100`**（因果版本，不要用非因果版本），确认：

```bash
test -f "$MFY_MODEL/avg_model.pt"
test -f "$MFY_MODEL/config.yaml"
```

模型许可分两部分：REAL-TSE 作者自有源码与训练参数为 Apache-2.0；上游 WeSpeaker ECAPA 预训练参数为 CC BY 4.0。完整声明见 [../licenses/MODEL_NOTICES.md](../licenses/MODEL_NOTICES.md)。仓库不提交权重或个人录音。

## 4．注册、导出与校验

先找出日常麦克风的准确名称并录制约 15 秒声音（安静环境、自然语速、日常麦克风、持续自然朗读；不要用他人的声音）。录音会先经过质量门槛（音量、削波与有效语音检查），不合格不会进入导出：

```bash
uv run micforyou devices
MFY_MIC="你的日常实体麦克风名称"
uv run micforyou record --input-device "$MFY_MIC" \
  --output-file "$MFY_VOICE" --duration 15 --countdown 3
```

按 macOS 提示允许录音进程使用麦克风。先运行与 App 内相同的录音质量门槛（不合格不会进入导出）：

```bash
uv run micforyou check-recording --file "$MFY_VOICE" --window-seconds 6
```

然后导出个人 ONNX 并校验数值一致性：

```bash
"$MFY_RUNTIME/bin/python" tools/inference/export_real_tse_onnx.py \
  --repo "$MFY_REPO" --model-dir "$MFY_MODEL" \
  --enrollment "$MFY_VOICE" --enrollment-seconds 6 \
  --output "$MFY_ONNX" --report "$MFY_DATA/reports/onnx-export.json"

"$MFY_RUNTIME/bin/python" tools/inference/compare_torch_onnx.py \
  --repo "$MFY_REPO" --model-dir "$MFY_MODEL" \
  --enrollment "$MFY_VOICE" --enrollment-seconds 6 \
  --onnx "$MFY_ONNX" --frames-per-chunk 8 --chunks 100 \
  --result "$MFY_DATA/reports/onnx-correctness.json"
```

correctness 报告的 `gate.verdict` 必须是 `PASS`；失败时不要启动实时过滤。

## 5．性能检查与配置

运行 ONNX 全路径 benchmark（合成输入，不打开真实麦克风）：

```bash
"$MFY_RUNTIME/bin/python" tools/inference/benchmark_onnx_tse.py \
  --repo "$MFY_REPO" --model-dir "$MFY_MODEL" \
  --enrollment "$MFY_VOICE" --onnx "$MFY_ONNX" \
  --audio-seconds 60 --frames 8 16 24 32 --threads 1 \
  --result "$MFY_DATA/reports/benchmark.json"
```

`gate` 应为 SUCCESS（有效候选 RTF ≤ 0.80）；MARGINAL／FAIL 不作为推荐配置。可从已有 benchmark JSON 重算建议：`uv run micforyou recommend-frames --benchmark .../benchmark.json`。

**先确定帧数候选，再复核与配置。** 从 benchmark 结果中选定一个通过候选（示例 `MFY_FRAMES=8` 来自已验证机型，不是通用门槛），后续 correctness、延迟复核和 configure 必须使用同一帧数。correctness 也须按该帧数重跑（见第 4 节）。

用配速工具复核实时队列动态（benchmark 不能替代）。注意 `--backend` 默认是 `torch`，必须显式传 `onnx` 才测的是 configure 实际运行的路径；`--prefill-ms` 须与 configure 一致（默认 100 ms）：

```bash
MFY_FRAMES=8   # 改为本机 benchmark 实际通过的候选
"$MFY_RUNTIME/bin/python" tools/inference/measure_bridge_latency.py \
  --repo "$MFY_REPO" --model-dir "$MFY_MODEL" --enrollment "$MFY_VOICE" \
  --backend onnx --onnx "$MFY_ONNX" --onnx-threads 1 \
  --frames-per-chunk "$MFY_FRAMES" --prefill-ms 100 --duration 30 \
  --result "$MFY_DATA/reports/latency.json"
```

判定读取结果 JSON 的 `bridge_internal` 段（终端摘要只是缩略）：`bridge_internal.bridge_latency.latency_ms_p95` ≥ 400 ms、`bridge_internal.status` 为 FAULT、`length_match` 不为 true、`nonfinite_samples` 非 0 或持续 underrun（`bridge_internal.underrun_ms`）的候选不可用。这些指标只覆盖 MicForYou 内部音频路径，不含 CoreAudio、BlackHole 传递和豆包识别耗时。

最后写入配置并确认就绪（帧数与上面复核一致）：

```bash
uv run micforyou configure \
  --input-device "$MFY_MIC" --output-device "BlackHole 2ch" \
  --model-repo "$MFY_REPO" --model-dir "$MFY_MODEL" \
  --enrollment "$MFY_VOICE" --onnx "$MFY_ONNX" \
  --runtime-python "$MFY_RUNTIME/bin/python" --project-root "$MFY_ROOT" \
  --frames-per-chunk "$MFY_FRAMES" --onnx-threads 1 --fault-policy silence
uv run micforyou status
```

`ready: true` 仅说明路径与设备齐全，不等于性能或过滤质量已通过。

## 6．构建菜单栏应用

需要 Swift 6+ 工具链（`swift --version` 低于 6 时请更新）：

```bash
swift build -c release --package-path app/MicForYouMenuBar
./app/MicForYouMenuBar/install_app.sh   # 构建并安装到 ~/Applications/MicForYou.app
```

应用读取 `~/Library/Application Support/MicForYou/config.json` 并调用其中的运行环境；不会下载模型，也不会更改系统默认输入。

## 7．测试与验证

```bash
# Python 控制器与产品契约回归测试
PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest -q

# 模型相关独立自检（不依赖 Xcode 工程）
cd app/MicForYouMenuBar
swiftc Sources/MicForYouMenuBar/Models.swift Checks/ModelCheck.swift -o .build/model-check
.build/model-check
cd ../..

# 暂停直通合成输入集成验证（真实 ONNX 模型 + 合成双工回调；
# 不打开真实麦克风，不使用输入法；报告写入 outputs/，该目录不入 Git）
uv run python tools/verification/verify_pause_passthrough.py --config "$HOME/Library/Application Support/MicForYou/config.json"
```

首次模型加载可能包含上游 JIT 编译，耗时比后续启动更长；等实际状态就绪再口述。

## 8．构建完整安装包

完整包在全新输出目录构建，固定校验源码版本与 checkpoint hash。当前原生依赖源码与声明固定 CPython 3.12.13，构建 Python 必须使用同一版本：

```bash
# 安装到专用目录，再用 uv 发现实际解释器本体（install-dir 只是容器目录，
# 不是安装本体，不能直接当 PYTHON_ROOT 用）
uv python install 3.12.13 --install-dir outputs/bundle-build/python
PYTHON_BIN=$(UV_PYTHON_INSTALL_DIR="$PWD/outputs/bundle-build/python" \
  uv python find --managed-python --no-project --resolve-links 3.12.13)
PYTHON_ROOT="$(dirname "$(dirname "$PYTHON_BIN")")"   # 解释器路径上提两级 = 安装本体
test -x "$PYTHON_ROOT/bin/python3.12"   # 确认推导结果可用
```

后续所有构建步骤都使用同一个推导出的 `PYTHON_ROOT`。用 requirements-bundle.lock 初始化该 Python（仅对构建专用 Python 使用 `--break-system-packages`，不得修改系统 Python），并准备原生依赖：

```bash
uv pip install --break-system-packages --python "$PYTHON_ROOT/bin/python3.12" \
  -r requirements-bundle.lock
uv pip install --target outputs/bundle-build/cmake cmake==4.4.4
"$PYTHON_ROOT/bin/python3.12" -B tools/bundle/prepare_native.py \
  --sources outputs/bundle-build/sources \
  --cmake outputs/bundle-build/cmake/cmake/data/bin/cmake \
  --output outputs/bundle-build/native
```

`<wespeaker-package-dir>` 指向模型环境 site-packages 中安装的 WeSpeaker **包目录**（不是 Git 仓库根），例如 `$MFY_RUNTIME/lib/python3.12/site-packages/wespeaker`；构建器通过其旁的 `wespeaker-*.dist-info/direct_url.json` 核对固定 revision，因此必须来自按第 3 节固定版本安装的模型环境。

构建完整 App ZIP：

```bash
./app/MicForYouMenuBar/package_complete.sh "$PYTHON_ROOT" "$MFY_REPO" <wespeaker-package-dir>
```

构建一体安装 pkg（需官方 BlackHole 安装包，构建器校验其 hash 与签名身份）：

```bash
curl -fL https://existential.audio/downloads/BlackHole2ch-0.7.1.pkg -o BlackHole2ch-0.7.1.pkg
./app/MicForYouMenuBar/package_installer.sh "$PYTHON_ROOT" "$MFY_REPO" \
  <wespeaker-package-dir> BlackHole2ch-0.7.1.pkg <全新输出目录>
```

构建器将完整 App 与官方驱动组成 `.pkg`，附 checksum、manifest 和双语安装与使用说明（由 `docs/INSTALL.md`／`INSTALL.en.md`／`USAGE.md`／`USAGE.en.md` 转换生成，导航与许可链接按交付布局重写）。输出目录必须全新。普通 venv 不能作为 `PYTHON_ROOT`；完整包不包含个人声音和个性化模型。

`package_release.sh` 只生成控制器外壳 ZIP（不含 Python、权重、注册），其说明指向本指南的源码设置部分；不要把它当作完整包。

## 9．只读验证安装包

`verify_installer.py` 只做只读检查（展开、校验 hash 与签名、查询安装选项），不执行管理员安装：

```bash
# 先构建检查工具（从仓库根执行；产物目录放仓库外或 ignored 路径）
MFY_CHECKS="$PWD/outputs/installer-build"
mkdir -p "$MFY_CHECKS"
swiftc -parse-as-library \
  app/MicForYouMenuBar/Checks/BundleCheck.swift \
  -o "$MFY_CHECKS/bundle-check"
swiftc -parse-as-library \
  app/MicForYouMenuBar/Sources/MicForYouMenuBar/CLIClient.swift \
  app/MicForYouMenuBar/Sources/MicForYouMenuBar/Models.swift \
  app/MicForYouMenuBar/Checks/StandaloneCheck.swift \
  -o "$MFY_CHECKS/standalone-check"

"$PYTHON_ROOT/bin/python3.12" -B tools/bundle/verify_installer.py \
  --pkg <path/to/MicForYou.pkg> --work <全新检验目录> \
  --checks-dir "$MFY_CHECKS"
```

说明：`@main` 源文件需要 `-parse-as-library`；`StandaloneCheck` 依赖控制器外壳的 `CLIClient`／`Models` 定义，须一起编译。`--checks-dir` 指向上一步构建的 `bundle-check`／`standalone-check`（默认 `outputs/installer-build`）。报告写入 `<work>/verification.json`；未执行的项目（管理员安装、重启、真机注册验收等）在 `not_run` 中列明。

## 10．许可与分发注意

- 自有代码与文档为 Apache-2.0（[../LICENSE](../LICENSE)、[../NOTICE](../NOTICE)）；第三方组件保留各自条款（[../licenses/](../licenses/)），构建器会在打包时复制许可并校验模型与驱动 hash。
- 已识别 LGPL／MPL 原生组件的源码与许可随包分发；全部实际原生依赖的最终分发复核尚未完成。
- 面向普通用户分发前需要 Developer ID 签名与 Apple 公证；当前构建为 ad-hoc 签名。
- 源码仓库不提交权重、个人录音与运行报告；`outputs/`、`runs/` 等已在 `.gitignore` 中忽略。
