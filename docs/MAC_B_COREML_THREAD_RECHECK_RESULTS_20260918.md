# Mac B CoreML thread recheck — 2026-09-18

Scope: audit of the sanitized return bundle `mac-b-coreml-thread-recheck-return-20260918-220907`. The manifest matched every returned file's SHA-256 and byte count. The bundle contained no audio, enrollment, checkpoint, transcription or ONNX artifact, and no private absolute path.

## Environment

- MacBook Pro M1 (`MacBookPro17,1`), macOS 15.7.3
- benchmark interpreter: Python 3.12.14
- PyTorch 2.7.1, ONNX 1.22.0, ONNX Runtime 1.30.0
- providers: CoreML, Azure and CPU Execution Providers
- repository commit: `3600fa8`
- project tests: 33 passed

This resolves the earlier Python 3.9.6/3.12.14 metadata discrepancy: the actual benchmark venv used Python 3.12.14.

## Corrected matrix

The rerun created separate CoreML sessions for `auto` and four ORT intra-op threads. All six candidates recorded matching requested and effective thread labels, exact output length, finite samples and no runtime error.

| Static frames | ORT threads | RTF | p50 | p95 | Result |
| ---: | ---: | ---: | ---: | ---: | --- |
| 8 | auto | 2.443 | 143 ms | 169 ms | valid, fails gate |
| 8 | 4 | 2.428 | 142 ms | 166 ms | valid, fails gate |
| 16 | auto | 1.471 | 190 ms | 197 ms | valid, fails gate |
| 16 | 4 | 1.495 | 193 ms | 208 ms | valid, fails gate |
| 24 | auto | 1.055 | 204 ms | 213 ms | valid, fails gate |
| 24 | 4 | **1.052** | 203 ms | 211 ms | best, fails gate |

Auto and four-thread results differ by at most about 2%; the thread setting is no longer an unresolved benchmark variable.

## Placement evidence

Each of the six session logs reported 18 CoreML partitions and 2,071 of 2,248 graph nodes supported. All 12 `LSTM` probes reported `supported: [0]`, so the recurrent main path remained on CPUExecutionProvider. The placement did not change from the earlier diagnostic run.

## Decision

The best valid result is RTF 1.052. It misses both the physical real-time boundary (`RTF < 1`) and the project's continuation gate (`RTF <= 0.8`). Dynamic INT8 had already failed correctness. Therefore:

```text
CURRENT REAL-TSE ON M1: STOP
```

Fidelity, paced, BlackHole, Doubao and live testing were correctly not run. This closes optimization of the current REAL-TSE TFMap model on the tested M1; the next model work must use a materially lighter causal TSE candidate and restart the quality, target-absent and runtime gates.
