# Handoff：Mac B INT8 + CoreML 有界验证

将本文件交给 Mac B 上的 Agent。目标不是继续无上限调参，而是回答一个问题：当前已正确导出的 REAL-TSE stateful core，能否通过 Dynamic INT8 或 CoreML EP 在 M1 上达到 `RTF <= 0.8`。

## 已确认状态

- 仓库主线至少包含提交 `716c469`。
- PyTorch 1/2/4/8 threads × 8/16/24/32 frames 共 16 组全部 `unsupported`；最佳 RTF 1.603。
- Mac B 本地已经存在一个通过 correctness gate 的 FP32 ONNX core：单 chunk max_abs 1.16e-06，连续 100 chunks max_abs 3.10e-06。
- ORT CPU 12 组全部失败；最佳 RTF 1.551（4 threads / 24 frames）。
- 上一轮生成的 ONNX、JSON 和三个实验脚本只在 Mac B 本地，尚未带回 Mac A。
- Mac B 不能进行 Git commit 或 push；所有 Git 集成由 Mac A 完成。
- 本任务不启动 BlackHole、豆包或 live bridge，不录音，不上传音频，不修改系统输入输出。

## Phase 0：先保全可复用源码

进入 Mac B 的现有 MicForYou 工作区，先执行：

```bash
git status --short
git log -1 --oneline
ls -lh \
  experiments/export_real_tse_onnx.py \
  experiments/compare_torch_onnx.py \
  experiments/benchmark_onnx_tse.py \
  handoff/real_tse_core_fp32.onnx \
  handoff/mac-b-onnx-export-report.json \
  handoff/mac-b-onnx-correctness.json \
  handoff/mac-b-onnx-cpu-benchmark.json
```

在拉取远端之前，把三个 Python 脚本和三个 JSON 复制到仓库外的本地备份目录；不要移动或删除原件。若三个脚本任一不存在，停止本轮，不要凭报告重写整个 exporter。

随后可从 GitHub 下载主线最新版，或使用用户提供的最新版离线仓库。若现有工作区含上述未提交脚本，必须先完成仓库外备份，不得用 checkout/reset 覆盖。Mac B 不执行 commit 或 push；以下通用源码在任务结束时放入 return bundle，由 Mac A 审查后集成：

```text
experiments/export_real_tse_onnx.py
experiments/compare_torch_onnx.py
experiments/benchmark_onnx_tse.py
```

不要提交：

```text
*.onnx
handoff/*.json
模型、权重、录音、enrollment、转写内容
```

带回源码前必须运行：

```bash
uv run pytest -q
python -m py_compile \
  experiments/export_real_tse_onnx.py \
  experiments/compare_torch_onnx.py \
  experiments/benchmark_onnx_tse.py
```

同时记录 `onnx`、`onnxruntime`、PyTorch 和 Python 的精确版本。官方 macOS `onnxruntime` wheel 通常包含 CoreML EP，但必须以本机 `ort.get_available_providers()` 为准。

## 统一边界与性能门槛

保持上一轮的确定性输入、完整 48k → 16k → TSE → 16k → 48k 路径、warmup、计时口径、checkpoint 和 enrollment conditioning。首次 session 创建/compile 时间单独记录，不计入 steady-state RTF。

```text
RTF <= 0.60            强候选
0.60 < RTF <= 0.80     可进入质量复验
0.80 < RTF <= 1.00     不进入质量/live；该分支不满足目标
RTF > 1.00             该分支 FAIL
```

INT8 和 CoreML **都**高于 0.8 时，停止当前 REAL-TSE 的 M1 部署优化。不要进入 QAT、自定义 kernel、Metal 重写或全量 Swift 重写。

## Branch A：Dynamic INT8

先输出 FP32 图的 operator histogram。不要预设图中一定是 `LSTM`、`MatMul` 或 `Gemm`；以实际导出图为准。

使用 ONNX Runtime 官方 `quantize_dynamic()` 做一次默认 dynamic quantization。官方对 RNN/Transformer 通常建议 dynamic quantization，但也明确指出量化/反量化开销可能使特定模型和硬件变慢，所以本分支只有一次受控尝试。除非 operator inventory 证明默认工具漏掉了占主导、且官方 registry 支持的算子，否则不要反复改 `op_types_to_quantize`。

必须生成并记录：

```text
handoff/real_tse_core_dynamic_int8.onnx
handoff/mac-b-onnx-int8-correctness.json
handoff/mac-b-onnx-int8-benchmark.json
```

Correctness gate：

- session 可创建；
- 100 chunks 连续传递全部 12 个 state；
- output length 和 state shape 不变；
- output/state 均无 non-finite；
- 记录 FP32 ORT vs INT8 ORT 的 max_abs、mean_abs、relative error；
- 报告量化前后模型大小、operator histogram，以及真正新增的量化算子。

Correctness 失败则 Branch A 立即停止。通过后只跑：

```text
frames = 8 / 16 / 24
ORT intra threads = auto / 4
duration = 10 seconds
```

输出 RTF、model-call p50/p95/max、完整性检查和 error。最佳 RTF 仍大于 0.8 时，不做质量复验。

## Branch B：CoreML Execution Provider

先记录：

```bash
python - <<'PY'
import onnxruntime as ort
print(ort.__version__)
print(ort.get_available_providers())
PY
```

若没有 `CoreMLExecutionProvider`，记录 wheel 来源和平台架构后停止 Branch B；不要把 CPUExecutionProvider fallback 结果标为 CoreML。

从已经通过 correctness gate 的 FP32 模型分别导出或固化 `T=8/16/24` 的 static-shape 模型，保持 12 个 recurrent state shape 不变。每个模型先运行 ONNX checker 和 100-chunk correctness，再 benchmark。

第一优先配置：

```python
providers = [
    ("CoreMLExecutionProvider", {
        "ModelFormat": "MLProgram",
        "MLComputeUnits": "ALL",
        "RequireStaticInputShapes": "1",
        "ProfileComputePlan": "1",
    }),
    "CPUExecutionProvider",
]
```

如果当前 ORT 版本不识别某个 provider option，记录完整错误并删除不支持的诊断 option；不得静默换成纯 CPU。最多再测一个 `ModelFormat=NeuralNetwork` 变体，不做大矩阵枚举。

必须启用 ORT profiling/logging，并从 profiling、CoreML compute-plan 日志或等价证据报告：

- CoreML 实际接管的节点/子图；
- 仍由 CPU EP 执行的关键节点；
- 6 层 recurrent 主路径是否进入 CoreML；
- session/compile 时间、first inference 和 warmed inference；
- static 8/16/24f 的 steady-state RTF 与 p50/p95/max。

`session.get_providers()` 只证明 provider 被注册，不能证明核心计算已被接管。若 recurrent 主路径主要 fallback 到 CPU 且 best RTF > 1.0，Branch B 立即停止，不进入 Native CoreML 重写。

## 分支汇合与停止线

先完成两个短分支的 correctness + 10 秒 benchmark，再统一判定：

```text
WINNER = INT8 / COREML / NONE
best_rtf = ?
frames = ?
runtime/provider = ?
```

### NONE

如果 INT8 与 CoreML 最佳结果都 `> 0.8`：

- 写明 `CURRENT REAL-TSE ON M1: STOP`；
- 不跑 fidelity、60 秒、paced、BlackHole、豆包或 live；
- 下一阶段转入 lightweight TSE 选型。

### INT8 或 COREML 达标

只有任一候选 `RTF <= 0.8` 才进入质量复验。复用 Mac B 私有数据，不上传音频：normal、quiet、0/-6/-12 dB 和 target-absent。与 FP32 PyTorch baseline 比较 SI-SDRi、target-absent attenuation、output/enrollment cosine、RMS、长度和 non-finite。

```text
SI-SDRi degradation <= 0.5 dB   PASS
0.5–1.0 dB                      REVIEW
> 1.0 dB                        FAIL
target-absent 明显退化           FAIL
```

Quality PASS 后才跑同配置 60 秒；仍 `RTF <= 0.8` 后才跑 120 秒 paced。paced 必须 `COMPLETED`、无 fault，且 bridge-internal p95 < 350 ms。任务到 paced 结果为止，不启动真实设备链路。

## 必须带回：离线 return bundle

Mac B 不执行任何 Git commit/push。完成任务后创建一个独立目录：

```text
handoff/mac-b-runtime-return-YYYYMMDD-HHMMSS/
```

目录包含：

- 三个上一轮 ONNX 通用脚本；
- 本轮新增的量化、static-shape/CoreML benchmark 通用脚本；
- 不包含机器绝对路径和私有数据的测试源码；
- 下列 JSON 与最终 Markdown 报告；
- `MANIFEST.txt`，列出相对路径、字节数和 SHA-256；
- `ENVIRONMENT.txt`，列出 macOS、芯片、Python/PyTorch/ONNX/ORT 版本、所依据的仓库 commit SHA 和实际 provider 列表。

必须包含的结果文件：

```text
mac-b-onnx-export-report.json
mac-b-onnx-correctness.json
mac-b-onnx-cpu-benchmark.json
mac-b-onnx-int8-correctness.json
mac-b-onnx-int8-benchmark.json
mac-b-coreml-ep-correctness.json
mac-b-coreml-ep-benchmark.json
最终 Markdown 报告
```

不要把 ONNX 模型、权重、录音、enrollment、生成音频或转写复制进 return bundle。创建 zip 前检查：

```bash
find "handoff/mac-b-runtime-return-YYYYMMDD-HHMMSS" -type f -print | sort
find "handoff/mac-b-runtime-return-YYYYMMDD-HHMMSS" -type f \
  \( -name '*.wav' -o -name '*.flac' -o -name '*.m4a' -o -name '*.onnx' -o -name '*.pt' \) -print
```

第二条命令必须无输出。然后生成 `MANIFEST.txt` 和 zip；用 AirDrop、USB 或当前任务附件把整个 zip 带回 Mac A。不要使用 Git 作为回传渠道。Mac A Agent 收到后负责审查脚本、复核 JSON 与 manifest、运行无模型测试、commit 和 push。

可用以下命令生成 manifest 与 zip；把目录名替换为实际时间戳：

```bash
RETURN_DIR="$PWD/handoff/mac-b-runtime-return-YYYYMMDD-HHMMSS"

while IFS= read -r file; do
  relative="${file#"$RETURN_DIR"/}"
  bytes="$(stat -f '%z' "$file")"
  hash="$(shasum -a 256 "$file" | awk '{print $1}')"
  printf '%s  %s  %s\n' "$hash" "$bytes" "$relative"
done < <(find "$RETURN_DIR" -type f ! -name MANIFEST.txt -print | sort) \
  > "$RETURN_DIR/MANIFEST.txt"

ditto -c -k --sequesterRsrc --keepParent "$RETURN_DIR" "${RETURN_DIR}.zip"
shasum -a 256 "${RETURN_DIR}.zip" > "${RETURN_DIR}.zip.sha256"
```

最终报告必须区分 `NOT RUN`、`FAIL` 和 `STOPPED BY GATE`，并包含依赖版本、operator/partition 证据和决策分支。

## Runtime 参考

- ONNX Runtime quantization：<https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html>
- ONNX Runtime CoreML EP：<https://onnxruntime.ai/docs/execution-providers/CoreML-ExecutionProvider.html>

这些页面只定义 runtime 能力，不替代本项目的 correctness、质量和性能 gate。
