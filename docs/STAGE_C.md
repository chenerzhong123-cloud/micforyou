# Stage C — causal core and real-time bridge

Status: `PARTIAL PASS`. The causal/stateful core and fault-silence behavior pass engineering checks, and Mac A completed live bridge runs, but interactive 30-minute use exposed CoreAudio stalls and load-induced overflow. Mac B's second wired-headset set passes offline extraction, while its complete PyTorch thread sweep and ONNX Runtime CPU benchmark both fail the real-time gate. End-to-end p95, stable interactive 30-minute operation, and complete physical fault drills remain unresolved.

## Why the model is actually streamable

REAL-TSE `tfmap_context_causal_100` uses single-direction time LSTMs when `causal: true`. Its bidirectional `band_comm` runs across frequency bands independently inside each current frame; it does not read future time frames. The normalization is channel-wise within a frame. Enrollment TFMap/context is precomputed once.

The upstream `forward` drops recurrent state, so `experiments/probe_real_tse_stateful.py` explicitly retains the hidden/cell state of all six time LSTMs. A bounded streaming STFT and overlap-add wrapper reproduces upstream centered-STFT edge behavior.

## Measured CPU results

Machine: MacBook Air M5, 16 GB. Model 16 kHz, 32 ms window, 8 ms hop; STFT algorithmic wait is 24 ms.

Official dependency check uses `wespeaker` commit `8f53b6485d9f88a207bd17e7f8dba899495ec794`, matching the REAL-TSE README.

| Input / chunk | Waveform-stream RTF | Cached-feature call p95 | Whole vs stream aligned SNR | Interpretation |
| --- | ---: | ---: | ---: | --- |
| synthetic 4.815 s / 4 frames (32 ms) | 0.907 | 20.51 ms | 127.26 dB | real-time, narrow headroom |
| public AliMeeting 22.52 s / 4 frames | 0.885 | 19.62 ms | 123.17 dB | stable on longer input, narrow headroom |
| public AliMeeting 22.52 s / 8 frames (64 ms) | 0.545 | 25.64 ms | 119.98 dB | selected default; larger headroom |

The complete file-driven bridge path was also exercised with 10 ms / 480-sample input blocks and both HQ resamplers. It returned exactly 1,080,960 output samples for 1,080,960 input samples, contained no non-finite values, had peak 0.3245, RTF 0.560, and actual per-call p95 36.18 ms. Eight frames therefore imply an estimated core latency of roughly `24 + 64 + 36 = 124 ms` before CoreAudio/BlackHole/Doubao buffers. This is not the required end-to-end p95 measurement. Four frames reduces batch wait by 32 ms but leaves too little CPU margin for a reliable desktop service. MPS was slower and showed an unstable teardown path, so CPU is selected.

## Bridge prototype

`experiments/run_real_tse_bridge.py` implements:

- explicit physical input and BlackHole 2ch output checks;
- callbacks that only enqueue input and drain output;
- worker-thread 48 kHz → 16 kHz resampling, stateful TSE, and 16 kHz → 48 kHz resampling;
- bounded queues and continuous stereo output clock;
- fault-silence on overflow or inference error, never raw-mic fallback;
- local metrics for callback status, queue depth, underrun and model-call p50/p95/max.

It requires an explicit model-frame chunk value chosen from a local benchmark. It deliberately does not select a fallback microphone and has not been live-run without the everyday headset.

## Why there is no silent chunk default

The earlier 64 ms (8-frame) offline measurement was fast on a lightly loaded development host, but the same complete bridge simulation on 2026-09-15 with Mac B's quiet user audio reported RTF 1.42 and processing-call p95 92.50 ms under normal desktop activity. It is therefore unsafe to assume that 8 frames always sustain real time.

On that host, 16 frames (128 ms) reduced RTF to 0.92 with 119.97 ms p95; 24 frames (192 ms) reduced it to 0.70 with 141.18 ms p95. The latter's estimated model core wait is about 357 ms before CoreAudio, BlackHole and Doubao, so it might breach the 500 ms end-to-end criterion. These are development-host results, not Mac B compute results. The live command intentionally requires `--frames-per-chunk`; benchmark Mac B before selecting 16 or 24.

An offline 125-second soak of the hardest Mac B-derived condition (quiet target at -12 dB), with 24 frames and complete 48→16→48 kHz conversion, produced exactly matching input/output lengths, finite audio, RTF 0.670, processing-call p95 136.10 ms and max 226.34 ms. This covers repeated state and resampling behavior only; it does not replace a physical 30-minute device stream.

## Mac A performance grading, latency, and stability (2026-09-15)

The Mac A handoff deliverables are implemented and run on this host. Reports live under `/Users/deuce/claudeproject/codexworks/micforyou/runs/20260915-*.json`; nothing below extends to Mac B or unknown hardware.

### Tooling

- `experiments/benchmark_real_tse.py`: repeatable full-path benchmark (48 kHz → 16 kHz → TSE → 16 kHz → 48 kHz) over deterministic synthetic audio with no user voice, machine-readable JSON, per-candidate RTF/call percentiles/integrity checks.
- `src/micforyou/recommendation.py` + `micforyou recommend-frames`: explainable grading into `fast` / `balanced` / `conservative` / `unsupported` with per-candidate reasons and thresholds. It only advises; the live bridge still requires an explicit `--frames-per-chunk`.
- `experiments/measure_bridge_latency.py`: wall-clock-paced simulated duplex callback driving the exact live DSP chain through the shared `BridgeEngine`; `LatencyLedger` audits arrival→write timestamps by audio position. Synthetic pulses only. Doubao and CoreAudio externals are explicitly listed as not measured.
- `src/micforyou/bridging.py`: the queue/ring/fault core extracted from the live script; unit tests replay input overflow, output overflow, and inference exceptions and assert fault-silence with zero raw passthrough (30 tests total, previously 6).
- The refactor also fixed two live-bridge defects found by the simulated runs: `torch.inference_mode()` is thread-local so the worker thread must enter it itself (the old worker would have raised on the first chunk), and the latency ledger must map output by ring audio position, not the output slot that runs ahead after underruns.

### Benchmark (AC power, loadavg ≈ 3.5, `20260915-benchmark-frames.json`)

| frames | RTF | call p50/p95/max ms | calls | length | recommendation |
| ---: | ---: | ---: | ---: | --- | --- |
| 8 | 0.507 | 32.0/33.5/56.5 | 938 | exact | **fast (chosen), core est. 121.5 ms** |
| 16 | 0.372 | 45.8/51.9/151.4 | 469 | exact | fast tier |
| 24 | 0.317 | 59.9/61.4/74.2 | 313 | exact | fast tier |
| 32 | 0.293 | 73.3/79.0/108.9 | 235 | exact | conservative tier (core est. 359 ms > 350 budget) |

The same 8-frame configuration measured RTF 1.42 earlier the same day under heavier desktop activity — the spread is the reason a pre-launch benchmark is mandatory and no silent default exists.

### Paced bridge-internal latency (`20260915-latency-8f/16f/24f.json`)

| frames | duration | status | p50/p95/max ms | underrun ms | RTF | notes |
| ---: | ---: | --- | ---: | ---: | ---: | --- |
| 8 | 30 s | COMPLETED | 200/202/291 | 58.8 | 0.532 | length exact, no fault |
| 16 | 120 s | COMPLETED | 330/341/487 | 152.5 | 0.413 | length exact, no fault |
| 24 | 120 s | COMPLETED | 380/381/550 | 96.3 | 0.377 | length exact, no fault |

These latencies sit well above the compute-only core estimate (e.g. 16f: 341 ms p95 vs 198 ms estimate) because queue dwell and burst emission only exist under real-time pacing. 24 frames leaves ≤ 70 ms for all external stages and is expected to breach the 500 ms end-to-end AT-07 target; 8/16 frames leave more internal headroom on this host, but neither value proves AT-07 because CoreAudio, BlackHole → Doubao and Doubao time are unmeasured. In one earlier 12 s probe (16f) the output ring reached its 500 ms bound during end-of-stream drain and latched fault-silence — transient burst catch-up can overflow the ring even when average RTF < 1, which is why the paced check is required before live use.

### BlackHole auto-loopback regression

`measure_bridge_latency.py --blackhole-roundtrip` (and the Stage A probe itself) currently captures pure silence from BlackHole on Mac A, while Stage A measured a clean 256 ms loop with gain 0.9999 on 2026-09-13 and Doubao still received BlackHole audio on 2026-09-15. The tool now reports this explicitly instead of emitting a bogus lag. Per the handoff this is treated as an environmental item for manual re-verification (reboot / Audio MIDI Setup), not something to work around.

### 30-minute simulated soak (16 frames)

`20260915-soak-16f-30min.json`: wall-clock-paced over the complete path with the live bounded queues, clearly labeled `simulated: true` — it opens no audio devices and does not replace the physical 30-minute AT-09 run.

- Status `COMPLETED`, 1800.6 s wall for 1800.0 s audio; output length exactly matches input; zero non-finite samples; no fault and no errors.
- Bridge-internal latency p50/p95/max 379.8/382.2/596.5 ms over 180,006 blocks; per-5-minute segment p95 stable at 361→382 ms (settles after the first segment).
- Per-segment model RTF 0.415–0.424 across all six segments — no drift or degradation; input queue peaked at 17 blocks (170 ms transient) and the ring at 371.7 ms, both below their 500 ms bounds; total underruns 151.7 ms, concentrated in startup settling.
- RSS declined from an early warm-up peak with no upward trend (no leak); pacing woke a median 3.3 ms late (Python timer granularity, reported per run).
- All 900 synthetic pulses were captured; mean alignment offset 0.03 ms (per-pulse max 99.96 ms reflects TSE smearing of broadband clicks, not position drift).

### Stage status after this work

Stage C remains `PARTIAL PASS`. AT-07 (physical end-to-end latency), AT-08 (Doubao stop-capture tail), AT-09 (physical 30-minute live run), and AT-10 (physical fault drills with the real headset) are still `NOT RUN`; the simulated tools above provide engineering evidence only, and no performance claim is transferred to Mac B or other user hardware. See `docs/PERFORMANCE_GUIDE.md` for the per-device pre-launch procedure.

### Mac A live-device verification (2026-09-16)

First physical-device runs of the bridge (`runs/mac-a-device-120s-20260916.json`, `mac-a-device-30min-20260916.json`), using the built-in `MacBook Air Microphone`, the public enrollment sample, and the benchmarked 8-frame chunk. These runs contain no user speech (room audio only, never persisted) and do not complete the handoff's user-speech items; they validate the real CoreAudio device path.

- 120 s run: `STOPPED` cleanly, 12,116 callbacks, 1,888 model calls (p50/p95/max 33.6/37.4/72.8 ms), no fault, no stream errors, input queue peak 6 blocks, ring peak 142.6 ms, underruns 204 ms concentrated in startup settling.
- 30-minute run (`mac-a-device-30min-20260916.json` + `-ps.log`): `STOPPED`, 180,808 callbacks, 28,244 model calls (p50/p95/max 33.5/37.3/207.4 ms), no fault, engine errors empty, input queue peak 21/50 blocks, ring peak 296.7 ms, underruns 364 ms total (0.02%), CPU ≈ 55% and RSS ≈ 150 MB flat for the whole run. PortAudio reported **4 `input overflow` statuses** (~4 × 10 ms of input dropped by the driver over 30 min): reported discontinuities, not a fault, not continuous, and no raw passthrough. Steady-state bridge-internal latency settled at p50/p95/max 360.0/360.2/467.6 ms — higher than the 120 s run's 220 ms because the output-ring lead ratchets up in bursts toward an equilibrium below its 500 ms bound; long-run internal latency therefore uses the 30-minute figure, not the 120 s one.
- Real-callback bridge-internal latency p50/p95/max 200.1/220.0/220.3 ms — close to the simulated paced run at the same chunk size (200.1/201.4/294.9 ms), validating the simulator against real CoreAudio scheduling.
- BlackHole auto-loopback was re-probed after the user restored settings and **still captures silence** (`runs/mac-a-loopback-20260916.json`, gain 0.0, correlation 0.0) versus the clean 2026-09-13 baseline (256 ms, gain ≈ 1, SNR 99.68 dB). Recorded as environment-not-recovered; AT-07 automatic external measurement remains incomplete, and no system setting was altered to force it.
- The user-speech live session (private enrollment, 120 s dictation, 30-minute Doubao acceptance with the STAGE_A phrases, and manual "speech-end → text" timing recorded side-by-side, never subtracted) is scripted in `docs/MAC_A_LIVE_SESSION.md` and still pending user participation.

Stage C remains `PARTIAL PASS`; AT-07 through AT-10 stay `NOT RUN` until that session and the physical fault drills complete.

### Mac A live speech acceptance session (2026-09-16 evening)

User-participation session per `docs/MAC_A_LIVE_SESSION.md`: private enrollment recorded (45 s, peak 0.508, no clipping), Doubao pointed at BlackHole 2ch, built-in microphone as the physical input. Microphone access for the agent host app was unavailable (ZCode feeds pure zeros under TCC denial; `tccutil reset` did not restore the prompt), so all audio commands were driven through Terminal.app, which the user authorized once.

**Live 120-second dictation runs (`mac-a-live-120s-20260916.json`):**

- 8 frames: `FAULT` — under the user's normal desktop activity the per-call time doubles (~68 ms vs 33 ms benchmark; WindowServer alone holds ~38% CPU), RTF exceeds 1, both queues overflow, 114.6 s of the 120 s output is silence. Fault-silence held: no raw passthrough, no device switch. This is live confirmation of why 8 frames cannot be a default.
- 16 frames: `STOPPED` clean — 943 calls p50/p95 87.5/95.3 ms, bridge-internal latency p50/p95/max 340.0/340.2/340.5 ms, ring peak 220 ms, no stream errors. The user's dictated speech traversed mic → TSE → BlackHole → Doubao successfully.

**Two 30-minute attempts both wedged mid-run (`stuck-bridge-28193-sample.txt`, `mac-a-live-30min-20260916-stall2.txt`):** CoreAudio's HAL stopped scheduling the bridge's IO context (IO thread parked in `semaphore_wait_signal_trap`, callbacks stopped, worker idle, memory compressed) a few minutes in, each time shortly after several Doubao push-to-talk toggles on BlackHole. The user observed dictation working early and then going silent; the wedge was invisible to the bridge itself (no fault, no exit). A `coreaudiod` restart between attempts did not prevent recurrence, and did not repair the dead BlackHole loopback capture either (`mac-a-loopback-20260916-postrestart.json`, still gain 0.0).

**10-minute isolation probe (`mac-a-isolation-10min-20260916.json`):** with the user not touching Doubao at all, the stream stayed healthy for the full 603.8 s at ~70–75% CPU — no wedge, supporting the push-to-talk trigger hypothesis (not conclusive). However the run ended `FAULT` near/after the drain: model p95 rose to 103.0 ms under concurrent desktop load, the output ring reached its 491 ms bound, 2 input overflows were reported, and underruns totaled 13.7 s. Realistic-load margin at 16 frames is therefore thinner than the clean 120 s run suggests; 24 frames trades compute margin for higher latency.

**Doubao acceptance through the chain (four dictation rounds, exact transcripts recorded):** phrase 1 intact 4/4; phrase 2 intact 3/4 (one round lost the final 「尾。」 and merged with the next phrase); phrase 3 intact 1/4 (two rounds lost trailing characters — 「截断。」 and 「截断尾。」— and one early round changed 录音→录制). All successful dictations went through the full bridge (Doubao was on BlackHole the whole time), so the intermittent tail loss is through-chain; no physical-mic Doubao baseline was collected in this session to separate bridge-induced gaps from Doubao's own endpointing, and no stopwatch timings were systematically captured.

**Acceptance status after the session:** AT-07 `NOT RUN` as an end-to-end pass (bridge-internal p95 340 ms recorded; external path unmeasurable while BlackHole loopback capture is dead; user timings not collected). AT-08 has evidence of intermittent through-chain tail loss with no baseline comparison — inconclusive, needs a physical-mic baseline round. AT-09 `FAIL` for now: two environmental CoreAudio wedges plus a load-induced queue-overflow fault; a production bridge needs an IO-liveness watchdog with stream reopen before the 30-minute criterion can be retried. AT-10 partially evidenced: every fault (8-frame overload, queue overflow) produced silence with zero raw passthrough and no automatic device switch; physical unplug drills remain untested. Stage C stays `PARTIAL PASS`.

### Mac B M1 benchmark and second recording set (2026-09-17)

Mac B is a MacBook Pro M1 (`MacBookPro17,1`, 8 cores, macOS 15.7.3). Two 60-second complete-path CPU benchmarks reproduced an `unsupported` decision: RTF for 8/16/24/32 frames was 4.167/2.512/1.977/1.680 on the first run and 4.110/2.478/1.895/1.625 on the rerun. Every model-call p95 exceeded its chunk interval, and even the best average RTF remained well above 1. Both runs used the one thread selected by upstream `wesep`; the explicit multi-thread follow-up was still pending at this dated checkpoint and is recorded in the next section. Per the pre-launch gate, no paced or live bridge run was attempted; installing BlackHole would not change the measured single-thread compute result.

A second independent wired-headset recording set passed file integrity checks and offline target extraction. Normal-speech SI-SDRi was +10.87/+15.46/+18.78 dB and quiet-speech SI-SDRi was +6.91/+12.75/+17.22 dB at 0/-6/-12 dB TIR. Target-absent attenuation was 21.02 dB, weaker than the prior set's 33.47 dB, so no zero-leakage claim is warranted. Full details are in [Mac B results — 2026-09-17](MAC_B_20260917_RESULTS.md).

### Mac B thread sweep and ONNX Runtime (2026-09-18)

Mac B returned a full 1/2/4/8-thread × 8/16/24/32-frame PyTorch matrix. All 16 valid runs remained `unsupported`; best RTF was 1.603 at four threads / 32 frames. This closes the pending thread-count question: upstream's one-thread setting was not the reason the current REAL-TSE PyTorch path failed on M1. Paced, BlackHole, Doubao and live tests were correctly skipped by Gate A.

The same machine then exported the six-layer recurrent neural core to an opset-17 FP32 ONNX model with all 12 h/c state tensors exposed. The returned report records max absolute error 1.16e-06 for one chunk and 3.10e-06 across 100 stateful chunks, below the 1e-03 correctness limit and without reported drift. ORT CPU performance nevertheless failed: all 12 auto/1/2/4-thread × 8/16/24-frame combinations were slower than real time; best RTF was 1.551 at four threads / 24 frames.

At this report checkpoint the results were report evidence rather than an independent rerun: Mac B had not yet returned the ONNX scripts or raw artifacts. Because Mac B cannot commit or push Git changes, the following handoff preserved scripts and results in a sanitized offline return bundle for Mac A review and integration. The bounded Dynamic INT8 and CoreML EP branches described here are now complete in the sections below. Full tables and evidence limits are in [Mac B runtime results — 2026-09-18](MAC_B_RUNTIME_RESULTS_20260918.md).

### Mac B INT8/CoreML return audit (2026-09-18)

The sanitized return bundle passed manifest and privacy-boundary checks. Dynamic INT8 failed correctness decisively: first-chunk max absolute error 0.965, 100-chunk max 1.405, relative L2 error 1.25 and final c-state error up to 151.79. INT8 benchmarking was correctly not run.

CoreML static 8/16/24-frame graphs remained numerically aligned with the PyTorch reference, and the returned capability log showed 2,071/2,248 nodes accepted across 18 CoreML partitions. However, all 12 LSTM nodes were unsupported and fell back to CPU. Code review then found that the CoreML benchmark explicitly used one ORT intra-op thread but labeled its candidates `auto`. Because the recurrent CPU fallback is the dominant unaccelerated path and prior ORT results are thread-sensitive, the reported best RTF 1.459 is diagnostic rather than a valid final gate result.

The imported benchmark preserves the exact requested auto/explicit thread setting in both session construction and JSON, with regression tests. At this audit point the M1 runtime decision was reopened for one corrected CoreML auto/4-thread matrix; the following section records its completion. Details of the initial audit are in [the INT8/CoreML return audit](MAC_B_INT8_COREML_RESULTS_20260918.md).

### Mac B corrected CoreML thread recheck (2026-09-18)

The corrected rerun closed the final runtime question. All six static 8/16/24-frame × auto/four-thread candidates were valid and correctly labeled, but all exceeded the `RTF <= 0.8` continuation gate. Best RTF was 1.052 at 24 frames/four threads, while all 12 recurrent LSTM operators still fell back to CPU. Auto and four-thread results differed by no more than about 2%, so thread selection is no longer an unresolved variable.

Dynamic INT8 failed correctness and corrected CoreML failed performance. The final M1 decision is therefore `CURRENT REAL-TSE ON M1: STOP`; fidelity, paced and live testing of this backend remain `STOPPED BY GATE`. Stage C stays `PARTIAL PASS` because no replacement model has passed the quality/runtime/live sequence. Full evidence is in [the corrected CoreML thread recheck](MAC_B_COREML_THREAD_RECHECK_RESULTS_20260918.md); the replacement-model boundary is in [the lightweight TSE screening](LIGHTWEIGHT_TSE_SCREENING_20260918.md).

## Reproducible environment

The isolated environment is stored with the artifact checkout, not in the source tree. To rebuild it:

```bash
uv venv --python 3.12 /Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse/.venv-official
uv pip install --python /Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse/.venv-official/bin/python -r experiments/requirements-real-tse.txt
```

`openai-whisper` appears only because the pinned upstream `wespeaker` package eagerly imports all frontends. MicForYou never calls it; Doubao remains the only ASR layer.

## Remaining live command

After the headset is connected and enrollment is captured, substitute the detected exact input name:

```bash
/Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse/.venv-official/bin/python experiments/run_real_tse_bridge.py \
  --repo /Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse \
  --model-dir /Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse/pretrained/tfmap_context_causal_100 \
  --enrollment /Users/deuce/claudeproject/codexworks/micforyou/test-data/human/enrollment.wav \
  --input-device "DETECTED HEADSET MICROPHONE" \
  --frames-per-chunk 16 \
  --result /Users/deuce/claudeproject/codexworks/micforyou/runs/live-real-tse.json
```

`16` in this example is a starting probe only, not a final recommendation; change it only from a Mac B measurement.

Do not mark Stage C passed until the end-to-end tests in SPEC.md AT-07 through AT-10 are complete.

### Mac A reliability hardening (2026-09-19)

The live bridge now detects a stopped CoreAudio callback clock, latches fault-silence, and exits promptly instead of sleeping until the requested duration. A callback-stall recovery may reopen the same explicit input/output pair once; every attempt rebuilds resamplers, STFT/OLA, recurrent state, queues, and timestamp ledgers, so pre-stall audio cannot leak into the recovered stream. Other faults are not automatically retried. Graceful shutdown now applies bounded backpressure while callbacks drain the output ring, preventing a transient model/flush burst from immediately overflowing the ring.

Automated tests increased to 41 and cover the liveness monitor, external fault wake-up with silence, and bounded shutdown drain. A 10-second physical-device smoke test passed. Under the then-current desktop load, 16 frames/one thread faulted from input queue overflow at about 72 seconds, and 24 frames/one thread faulted at about 21 seconds with bridge p95 about 720 ms. A 30-second 2/4-thread check found no useful advantage from four threads. The selected Mac A probe, 16 frames/two threads, then completed 120 seconds with no fault, callback stall, or PortAudio status: model-call p95 93.89 ms, bridge-internal p95 360.07 ms, and input queue peak 12/50 blocks.

This is a real CoreAudio/BlackHole engineering regression with no user speech, not AT-07 through AT-10 acceptance. Stage C remains `PARTIAL PASS`; the next gate is the 30-minute interactive Doubao run, followed by direct-microphone versus TSE/BlackHole tail A/B and physical fault drills. Detailed commands and local artifact names are indexed in `docs/MAC_A_NEXT_STAGE.md`.

The live command now also exposes PyTorch inter-op thread count, explicit output prefill, and five-second queue-pressure samples. On this Mac, `16 frames / 2 intra-op / 1 inter-op / 100 ms prefill` completed a 180-second physical-device run with no fault or callback stall and bridge p95 `380.18 ms`; a 900-second run at 150 ms prefill stayed alive but had two input-overflow statuses and p95 `520.03 ms`. The 100 ms setting is therefore the next interactive candidate, not yet a final pass.

A 900-second run at the 100 ms prefill candidate reached approximately 883 seconds before an input-overflow-induced output burst exceeded the bounded ring. It entered fault-silence as designed; bridge p95 at the point of failure was 499.99 ms and two PortAudio input-overflow statuses were recorded. This closes the current CPU/PyTorch configuration as insufficient for the 30-minute acceptance gate under the observed desktop load. Doubao interaction is intentionally postponed until a runtime or scheduling optimization is measured.

### Recovery SLA (2026-09-19)

A single block/queue/callback fault no longer permanently poisons the session. The controller keeps output silent, closes the old stream, discards stale audio, rebuilds resamplers, STFT/OLA, recurrent state, queues and ledgers, and reopens only the same explicit device pair. It does not continue with possibly corrupt state and never passes raw microphone audio through. A rolling circuit breaker defaults to two recoveries per five minutes; further failure latches FAULT. Reports retain every failed attempt, recovery reason and a `degraded` flag.

A deliberate 50 ms-ring fault injection forced three consecutive input-queue overloads. Attempts one and two rebuilt the pipeline; attempt three was rejected by the circuit breaker and remained fault-silent (`faults_recovered=2`, `total_rejected=1`). A naturally transient fault followed by successful live continuation remains to be exercised before this counts as AT-10 evidence.

An explicit `--fault-policy passthrough` is now available as the continuity-first alternative; `silence` remains the default. After the same three-fault injection exhausted two recoveries, the bridge stopped TSE work, reopened the same MacBook Air Microphone/BlackHole pair, and completed the remaining 4.09 seconds in raw passthrough mode (384 callbacks, no status or liveness fault). The final report says `final_mode=passthrough` and `degraded=true`. This validates the engineering transition only; the future UI warning and a Doubao-visible transition remain untested.

### Mac A ONNX runtime and bounded enrollment (2026-09-19)

The 45-second private registration recording exposed two separate constraints. First, tracing `tfmap_context_causal_100` with a different enrollment and merely declaring the enrollment axes dynamic is not valid: internal multi-head-attention reshapes remain specialized to the trace length. Second, repeatedly attending over all 45 seconds made an otherwise-correct personalized ONNX graph take roughly 212–233 ms per 64 ms chunk and immediately overflow the input queue.

The runtime now retains the original registration recording but deterministically selects the highest-RMS 6-second window in a controlled quiet recording. The selected Mac A window was 4.5–10.5 seconds. Export, Torch/ONNX comparison and live execution use the same rule and report its metadata. Registration changes therefore require a local personalized ONNX re-export; they do not require model training or cloud ASR.

The personalized 6-second FP32 ONNX passed 100 consecutive stateful chunks against PyTorch (`waveform max_abs=1.729e-6`, final state h/c max `7.093e-6`/`8.392e-5`). A 120-second MacBook Air Microphone → ONNX REAL-TSE → BlackHole run then completed in `final_mode=tse`, with no fault, recovery, callback stall, PortAudio status or passthrough. ORT used one CPU thread; model-call p50/p95/max were `25.83/29.29/55.85 ms`, bridge p95 was `260.16 ms`, and the input queue peaked at 3 blocks.

The same configuration completed a 900-second soak in `final_mode=tse`: no fault, recovery, callback stall or passthrough; model-call p50/p95/max `25.80/29.24/157.33 ms`; bridge p50/p95/max `260.04/260.17/377.87 ms`; and input queue peak 6/50 blocks. The 5-second samples show no drift: input-queue averages were 0.422 blocks in the first half and 0.427 in the second, while output-ring averages were 6447 and 6436 frames. CoreAudio did report two `input overflow` statuses, so this is a stable engineering pass with two reported input discontinuities, not an error-free AT-09 pass. The user-visible 30-minute Doubao quality/endpointing gate remains separate.

Startup now validates the fixed enrollment-conditioning shapes against the personalized ONNX before opening audio devices. A stale ONNX from an earlier enrollment fails with an explicit re-export instruction and cannot consume the automatic-recovery budget or enter passthrough. The automated suite contains 49 passing tests.
