# Handoff：Mac B M1 Torch 线程扫描

将本文件原样交给 Mac B 上的 Agent。任务只验证一个问题：之前两次 benchmark 是否因为 upstream `wesep` 把 PyTorch 设为单线程而低估了 M1。不要安装 BlackHole，不要启动豆包，不要录音，不要运行 live bridge。

## 背景与边界

- Mac B：MacBook Pro M1（`MacBookPro17,1`，4 performance + 4 efficiency cores），macOS 15.7.3，AC 电源。
- 已有两次 60 秒完整路径 benchmark，`torch_threads: 1`，8/16/24/32-frame RTF 分别约为 `4.11/2.48/1.90/1.63`，均为 `unsupported`。
- 已验证模型权重 SHA-256：`97c01b79b0cf1a5b914a4a3bc1113c1864752ebdd320f528e77a53202447fef2`。
- 最新 MicForYou 代码加入显式 `--torch-threads`；要求至少包含提交 `d527d27`，推荐使用主分支最新提交 `52b5912` 或更新版本。
- 本任务只使用进程内合成信号，不读取或写入个人录音，不调用任何 ASR。
- 所有 JSON 留在 Mac B 的 `handoff/`；不要提交到 Git。

## 1. 确认代码版本

进入 Mac B 上的 MicForYou 仓库。如果能访问 GitHub，更新主分支；如果该仓库来自离线 bundle，则使用用户提供的最新版仓库/bundle，不要擅自覆盖私有音频或模型目录。

```bash
git status --short
git log -1 --oneline
local-models/wesep-real-tse/.venv-official/bin/python \
  experiments/benchmark_real_tse.py --help | grep torch-threads
uv run pytest -q
```

验收：help 中必须出现 `--torch-threads`，测试应为 `30 passed`。若没有该参数或测试失败，停止并保存终端输出；不要用旧脚本继续。

## 2. 运行短线程扫描

保持 AC 电源和日常后台负载，不要刻意关闭全部应用。确认模型路径存在后运行：

```bash
mkdir -p handoff

for n in 2 4; do
  local-models/wesep-real-tse/.venv-official/bin/python \
    experiments/benchmark_real_tse.py \
    --repo "$PWD/local-models/wesep-real-tse" \
    --model-dir "$PWD/local-models/wesep-real-tse/pretrained/tfmap_context_causal_100" \
    --audio-seconds 10 \
    --frames 8 16 24 32 \
    --torch-threads "$n" \
    --result "handoff/mac-b-benchmark-threads-${n}.json"
done
```

检查两份 JSON：

```bash
jq '{threads: .system.torch_threads, candidates: [.candidates[] | {frames: .frames_per_chunk, rtf: .processing_rtf, p95_ms: .model_call_ms_p95}], recommendation: .recommendation}' \
  handoff/mac-b-benchmark-threads-2.json \
  handoff/mac-b-benchmark-threads-4.json
```

每份 JSON 必须满足：权重 hash 正确、`system.torch_threads` 等于请求值、输出长度匹配、`nonfinite_samples` 为 0、`error` 为 null。否则该运行无效。

## 3. 分支判定

### A. 两份结果仍为 `unsupported`

立即停止。不要尝试更大 chunk、MPS、BlackHole、paced 或 live。更大 chunk 无法同时满足实时 RTF 与 500 ms 延迟预算。结论写成：

> Mac B M1 在 upstream 1 thread、显式 2 threads 和显式 4 threads 下均不支持当前 TFMap PyTorch CPU 实时链路；下一步应转向更轻模型或优化部署后端。

### B. 任一结果出现非 `unsupported` 推荐

选择等级最好、估计延迟最低的组合 `<THREADS>` 和 `<FRAMES>`，用相同设置做一次 60 秒确认：

```bash
local-models/wesep-real-tse/.venv-official/bin/python \
  experiments/benchmark_real_tse.py \
  --repo "$PWD/local-models/wesep-real-tse" \
  --model-dir "$PWD/local-models/wesep-real-tse/pretrained/tfmap_context_causal_100" \
  --audio-seconds 60 \
  --frames <FRAMES> \
  --torch-threads <THREADS> \
  --result handoff/mac-b-benchmark-thread-confirm-60s.json
```

只有 60 秒结果仍为非 `unsupported`，且长度、finite、error 全部通过，才把它报告为“可进入 paced 复核”。**本任务到此停止，不运行 paced/live。**

## 4. 带回文件与最终报告

必须带回：

```text
handoff/mac-b-benchmark-threads-2.json
handoff/mac-b-benchmark-threads-4.json
```

仅分支 B 需要：

```text
handoff/mac-b-benchmark-thread-confirm-60s.json
```

最终回复必须列出：仓库提交、测试结果、每个线程/frames 的 RTF 和 p95、recommendation、完整性检查，以及走了分支 A 还是 B。不要上传模型、音频或私有目录。
