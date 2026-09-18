# Mac B Runtime results — 2026-09-18

Scope: the returned Mac B reports for the complete PyTorch thread sweep and the first stateful ONNX Runtime experiment. At this report's initial cutoff, the reusable scripts and raw artifacts were still on Mac B. The scripts were later returned, reviewed and integrated at commit `3600fa8`; model weights and private audio remain outside Git.

## Evidence boundary

The numbers below are transcribed from the returned reports `MAC_B_THREAD_SWEEP_RESULTS(1).md` and `MAC_B_ONNX_RUNTIME_RESULTS(2).md`. They are accepted as Mac B run evidence, but the project does not yet contain the reported JSON or the three ONNX experiment scripts. In particular, the ONNX result is not a code review: the report explicitly says the scripts were not committed.

No user recording was uploaded or added to Git. The performance inputs were deterministic synthetic signals; the existing private enrollment was only used locally where required.

## PyTorch thread sweep

Environment: MacBook Pro M1 (`MacBookPro17,1`, 4 performance + 4 efficiency cores), macOS 15.7.3, AC power, Python 3.12.14, PyTorch 2.7.1, repository commit `716c469`. `uv run pytest -q` reported 30 passing tests.

All 16 combinations passed the report's integrity checks: requested/actual thread counts matched, checkpoint hash matched `97c01b…fef2`, output length matched input, samples were finite and no run returned an error.

| Torch threads | 8f RTF | 16f RTF | 24f RTF | 32f RTF |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 4.454 | 2.740 | 1.906 | 1.722 |
| 2 | 5.522 | 3.188 | 2.365 | 1.857 |
| 4 | 4.418 | 2.678 | 2.263 | **1.603** |
| 8 | 4.229 | 2.441 | 2.229 | 1.956 |

Every combination was classified `unsupported`. Best RTF was 1.603 at four threads / 32 frames. Gate A therefore correctly stopped paced latency, BlackHole, Doubao, live bridge and soak runs. This closes the earlier question about whether upstream's one-thread setting alone caused the M1 failure: explicit 2/4/8-thread runs did not make the current PyTorch path real time.

## Stateful ONNX correctness

Mac B exported only the neural-network core, retaining the Python streaming STFT/OLA and resampling path. The reported ONNX boundary was:

```text
spec_ri (1, 2, 257, T)
+ enrollment TFMap/context
+ 12 explicit LSTM state tensors (6 layers × h/c, each (1, 32, 256))
    -> est_ri (1, 2, 1, 257, T)
    -> 12 updated state tensors
```

The FP32 artifact was reported as opset 17, 85.3 MB and 7,445 nodes. State was passed between chunks rather than reset.

| Check | Returned result |
| --- | ---: |
| `onnx.checker` | PASS |
| Single-chunk ONNX vs PyTorch max absolute error | 1.16e-06 |
| 100-chunk streaming max absolute error | 3.10e-06 |
| Final h-state error | 3.4e-06 |
| Final c-state error | 1.56e-04 |
| Correctness limit | 1e-03 |

The report marks the correctness gate PASS and reports no accumulating drift over 100 chunks. The wrapper/export approach is therefore a valid basis for the next runtime experiment, subject to recovering the source scripts in an offline return bundle for review and later Git integration on Mac A.

## ONNX Runtime CPU benchmark

Reported conditions: same deterministic input and complete 48 kHz → 16 kHz → TSE → 16 kHz → 48 kHz path as the PyTorch benchmark, 10 seconds, sequential execution and all graph optimizations enabled.

| ORT intra threads | 8f RTF / p95 | 16f RTF / p95 | 24f RTF / p95 |
| ---: | ---: | ---: | ---: |
| auto | 3.353 / 255 ms | 1.956 / 291 ms | 1.756 / 567 ms |
| 1 | 8.189 / 614 ms | 4.598 / 659 ms | 3.484 / 777 ms |
| 2 | 5.100 / 364 ms | 2.833 / 415 ms | 4.191 / 1812 ms |
| 4 | 3.750 / 304 ms | 2.179 / 393 ms | **1.551 / 460 ms** |

Best RTF was 1.551 at four threads / 24 frames. The largest reported speedup relative to the matching PyTorch one-thread case was about 1.40× (auto threads / 16 frames). This is an R2-C failure because every combination remains slower than real time and above the project's `RTF <= 0.8` continuation gate.

The measurements prove that this exported graph on ORT CPU is insufficient on the tested M1. Statements about the precise kernel-level cause are hypotheses until profiling or operator-placement evidence is returned; they are not treated as measured facts.

## Decision

```text
PyTorch CPU thread sweep: UNSUPPORTED
Stateful FP32 ONNX correctness: PASS (reported; source later integrated)
ONNX Runtime CPU performance: FAIL
Mac B live path: NOT RUN by gate
```

The bounded INT8/CoreML experiment has now completed. INT8 failed correctness. The first CoreML report mislabeled an explicit one-thread session as `auto`; the corrected auto/four-thread rerun then produced six valid but failing candidates, with best RTF 1.052 at 24 frames/four threads. All 12 LSTMs still fell back to CPU. The final decision is `CURRENT REAL-TSE ON M1: STOP`. See `MAC_B_INT8_COREML_RESULTS_20260918.md` and `MAC_B_COREML_THREAD_RECHECK_RESULTS_20260918.md`.
