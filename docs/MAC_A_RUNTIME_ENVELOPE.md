# Mac A runtime-envelope validation

Date: 2026-09-19. Host: MacBook Air `Mac17,3`, Apple M5, 10 CPU cores, 16 GB RAM.

## Decision

Mac A can complete model correctness, Mac B-recording quality evaluation, BlackHole/Doubao functional checks, and bridge behavior under a controlled inference-time envelope. It cannot be CPU-throttled into a credible M1 performance measurement. A final real-model benchmark and physical audio-chain acceptance remain mandatory on Mac B.

The envelope harness is implemented in `experiments/simulate_runtime_envelope.py`. It opens no model, audio device, recording or ASR. `micforyou.envelope.DelayEnvelope` can later wrap the real lightweight-model transform, preserving the same report contract.

## Why delay injection instead of CPU throttling

`taskpolicy`, Low Power Mode and background load can perturb scheduling, but they do not reproduce M1 ONNX/CoreML kernel selection, memory bandwidth, thread behavior, thermal state or CoreAudio scheduling. Delay injection makes a narrower, auditable claim: it validates the bridge's queue, latency, underrun and fault-silence behavior when DSP calls exhibit the recorded service-time distribution.

The report keeps requested and observed durations separate. Short `time.sleep` calls are not treated as exact; the wrapper uses coarse sleep plus a short final wait, then reports the actual observed p50/p95/max. The observed distribution, never the profile label, is the evidence.

## Profiles

All profiles use 480-sample blocks at 48 kHz: one model call every 10 ms.

| Profile | Target min/p50/p95/max | Purpose |
| --- | --- | --- |
| `nominal` | 2/4/7/10 ms | expected safe service time |
| `boundary` | 4/7/10/20 ms | average below cadence with occasional tail spikes |
| `overload` | 9/12/16/25 ms | sustained service slower than cadence; must fault silently |

The default explicit output prefill is 50 ms. This is a jitter buffer, not hidden latency: it appears in the bridge latency distribution and consumes the 500 ms end-to-end budget. `BridgeEngine` keeps its production-compatible default at zero; callers must opt in deliberately.

## 2026-09-19 validation

Short runs first exposed that `time.sleep` overshoot distorted the requested distribution; the wrapper was corrected to record and enforce observed duration. They also exposed that an input-overflow fault let the worker continue processing queued blocks. The worker now stops as soon as fault is latched and produces no post-fault output.

The formal 120-second boundary run with 50 ms prefill produced:

| Metric | Result |
| --- | ---: |
| Status | `COMPLETED` |
| Blocks | 12,000 |
| Input/output length | exact match |
| Input queue peak | 3 blocks |
| Output ring peak | 2,880 frames / 60 ms |
| Underrun | 0 ms |
| Bridge latency p50/p95/max | 60.0 / 62.9 / 92.3 ms |
| Non-finite output | 0 |

The overload profile retained the same 50 ms prefill but faulted after about 1.6 seconds when the 500 ms input bound was reached. It reported only `input queue exceeded its bound`; after the fault, `written_frames=0`, the returned block was all zero and the output ring was empty. This validates the intended failure policy, not an M1 speed claim.

Local JSON evidence remains outside Git:

```text
/Users/deuce/claudeproject/codexworks/micforyou/runs/runtime-envelope-boundary-prefill-120s-20260919.json
/Users/deuce/claudeproject/codexworks/micforyou/runs/runtime-envelope-overload-prefill-20260919.json
```

## Commands

Run all short profiles:

```bash
uv run python experiments/simulate_runtime_envelope.py \
  --profiles nominal boundary overload \
  --duration 120 --prefill-ms 50 \
  --result /Users/deuce/claudeproject/codexworks/micforyou/runs/runtime-envelope-120s.json
```

Run a 30-minute boundary soak only after the real lightweight transform has passed correctness and native Mac A runtime checks:

```bash
uv run python experiments/simulate_runtime_envelope.py \
  --profiles boundary --duration 1800 --prefill-ms 50 \
  --result /Users/deuce/claudeproject/codexworks/micforyou/runs/runtime-envelope-boundary-30m.json
```

For the real-model run, wrap the model's one-chunk transform with `DelayEnvelope` rather than replacing it with the synthetic identity transform. If the underlying call already exceeds a selected target, the wrapper adds no delay and reports `underlying_over_target_calls`; it never accelerates or hides the real inference cost.

## Remaining boundary

The lightweight model files and their exact ECAPA conditioner currently return 404/401, so real-model integration cannot begin. Once restored, Mac A performs source verification, correctness, private Mac B-recording quality, native performance, delay-envelope bridge tests, BlackHole/Doubao A/B and the 30-minute simulated soak.

Mac B is then limited to:

1. matching model and conditioner hashes;
2. a real 60-second M1 benchmark (`RTF <= 0.8`, 10 ms-call p95 <= 10 ms);
3. physical headset -> model -> BlackHole -> Doubao acceptance;
4. the final physical 30-minute stability run required before a daily-use claim.
