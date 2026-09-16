# Stage C — causal core and real-time bridge

Status: `PARTIAL PASS`. The causal/stateful processing core passes equivalence and CPU timing checks. Offline Mac B-derived audio can traverse BlackHole → Doubao with material target recovery and no observed target-absent text; this is not a physical-headset live run. Physical-headset → model → BlackHole, end-to-end p95, fault injection, and 30-minute stability remain `NOT RUN`.

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
