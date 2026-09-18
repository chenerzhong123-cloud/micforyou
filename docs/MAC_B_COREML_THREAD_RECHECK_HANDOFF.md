# Handoff：Mac B CoreML CPU-fallback 线程复核

将本文件交给 Mac B Agent。本轮只修正上一轮 CoreML benchmark 的线程标记错误，不重跑 INT8、不重新导出 ONNX、不启动 BlackHole/豆包/live，也不执行 Git commit/push。

## 为什么必须补跑

上一轮脚本创建 CoreML session 时实际设置了 `intra_op_num_threads=1`，但 JSON 写成 `auto`。同时 12 个 LSTM 全部由 CPUExecutionProvider 执行，所以这一错误会直接影响主路径性能。返回的 `RTF=1.459` 不能作为最终停止依据。

INT8 correctness 已经确定 FAIL，不重跑。

## 准备

1. 从 GitHub 下载包含本文件的最新源码，或由用户把最新版仓库复制到 Mac B。
2. 保留 Mac B 现有私有模型、enrollment、static ONNX 和 handoff JSON；不要用新仓库覆盖这些目录。
3. 使用此前运行 ONNX 实验的 Python 3.12 venv。

检查：

```bash
uv run pytest -q

local-models/wesep-real-tse/.venv-official/bin/python -m py_compile \
  experiments/benchmark_onnx_tse.py

local-models/wesep-real-tse/.venv-official/bin/python - <<'PY'
import platform
import sys
import onnxruntime as ort
print("executable:", sys.executable)
print("python:", platform.python_version())
print("onnxruntime:", ort.__version__)
print("providers:", ort.get_available_providers())
PY
```

项目测试应为 33 passed；provider 必须包含 `CoreMLExecutionProvider`。把上述环境输出保存到最终报告，以消除上一轮 3.9.6/3.12.14 的记录冲突。

## 找到三个 static 模型

确认此前生成的固定 shape 模型仍在 Mac B：

```text
T=8
T=16
T=24
```

通常文件名为：

```text
handoff/real_tse_core_8f.onnx
handoff/real_tse_core_16f.onnx
handoff/real_tse_core_24f.onnx
```

若实际名称不同，使用实际路径。若任一模型缺失，停止并报告缺失项；本轮不要重新导出，以免同时改变模型和 benchmark 两个变量。

## 正式矩阵

对每个 static 模型只测试与其 shape 相同的 frames，并测试 `auto` 与显式 `4` threads：

```bash
PYTHON=local-models/wesep-real-tse/.venv-official/bin/python
MODEL_DIR="$PWD/local-models/wesep-real-tse/pretrained/tfmap_context_causal_100"
REPO_DIR="$PWD/local-models/wesep-real-tse"
ENROLLMENT="/ABSOLUTE/PRIVATE/PATH/enrollment_b.wav"

for frames in 8 16 24; do
  "$PYTHON" experiments/benchmark_onnx_tse.py \
    --repo "$REPO_DIR" \
    --model-dir "$MODEL_DIR" \
    --enrollment "$ENROLLMENT" \
    --onnx "$PWD/handoff/real_tse_core_${frames}f.onnx" \
    --torch-baseline "$PWD/handoff/mac-b-thread-1-10s.json" \
    --provider coreml \
    --audio-seconds 10 \
    --frames "$frames" \
    --threads 0 4 \
    --session-log "$PWD/handoff/coreml-T${frames}.log" \
    --result "$PWD/handoff/mac-b-coreml-T${frames}-thread-recheck.json"
done
```

这里 `0` 表示不设置 ORT 线程数，即真正的 runtime default；`4` 表示显式设置四个 intra-op threads。每个结果 JSON 必须包含两个 candidate，且：

```text
candidate[auto].intra_op_threads == "auto"
candidate[4].intra_op_threads == "4"
session_info/candidate 的 requested_intra_op_threads 与之匹配
output_samples == input_samples
nonfinite_samples == 0
error == null
```

脚本会分别产生 `*-threads-auto.log` 和 `*-threads-4.log`。确认日志仍显示 12 个 LSTM `supported: [0]`；若 placement 改变，必须报告，不能与上一轮混用。

## Gate

汇总六个有效候选：

```text
3 static frame sizes × 2 CPU-fallback thread settings
```

- 任一候选 `RTF <= 0.8`：标记 `COREML PERFORMANCE CANDIDATE`，停止并返回结果；不要擅自进入 live。
- 全部候选 `RTF > 0.8`：标记 `CURRENT REAL-TSE ON M1: STOP`，下一阶段正式转入 lightweight TSE。
- 任何 candidate 标记与实际 requested threads 不一致：结果 `INVALID`，不要作决策。

## 离线回传

Mac B 不使用 Git 回传。创建新的目录：

```text
handoff/mac-b-coreml-thread-recheck-return-YYYYMMDD-HHMMSS/
```

只放入：

```text
mac-b-coreml-T8-thread-recheck.json
mac-b-coreml-T16-thread-recheck.json
mac-b-coreml-T24-thread-recheck.json
关键 partition/placement 摘录
环境输出
最终 Markdown 报告
MANIFEST.txt（SHA-256 + bytes + 相对路径）
```

不带回 ONNX、权重、音频、enrollment 或完整私有目录。压缩后通过 AirDrop、USB 或当前任务附件返回 Mac A。
