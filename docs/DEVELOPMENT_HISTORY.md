> 历史研发记录：下文保留旧版本背景；当前安装与暂停行为以仓库 README 为准。

# MicForYou

MicForYou keeps Doubao IME as the ASR/text layer and sends locally processed audio to it through BlackHole 2ch. Processing and enrollment remain local; MicForYou does not implement ASR or type text.

Mac A M5 has a validated FP32 ONNX runtime path: 30 minutes in `final_mode=tse`, bridge p95 about 260 ms, bounded queues, and a passing physical headset hot-unplug/replug test with no raw fallback. The user heard useful reduction of other speech/noise in a genuine workplace clip and accepted continued experimentation, but a target-absent clip still produced intelligible colleague text in Doubao. Treat the current checkpoint as partial filtering, never as strict privacy isolation. Enrollment should be refreshed when the physical microphone changes. Mac B M1 also remains unsupported for this REAL-TSE checkpoint because every measured backend missed its real-time gate.

## Daily Mac A commands

After the one-time configuration in [the Stage D guide](STAGE_D.md):

```bash
uv run micforyou status
uv run micforyou run
```

Stop with `Control-C`. The default `silence` policy remains private on terminal faults. The optional `passthrough` policy prints a repeating warning whenever filtering is unavailable and raw microphone audio is being forwarded.

## Stage A quick start

Install dependencies:

```bash
uv sync --extra dev
```

After BlackHole 2ch has been installed and the Mac restarted:

```bash
uv run micforyou devices
uv run micforyou prepare-audio
uv run micforyou probe-loopback /Users/deuce/claudeproject/codexworks/micforyou/test-data/route-test.wav
uv run micforyou play-file /Users/deuce/claudeproject/codexworks/micforyou/test-data/route-test.wav
uv run micforyou passthrough --input-device "YOUR PHYSICAL MICROPHONE"
```

Select `BlackHole 2ch` as Doubao's input if Doubao exposes a device selector. Otherwise, temporarily select it under System Settings → Sound → Input while running a test. Do not change the system output device.

Every actual run writes a JSON record under `/Users/deuce/claudeproject/codexworks/micforyou/runs/`. Real enrollment and test recordings must not be committed.

See `docs/STAGE_A.md` for routing acceptance and recovery, `docs/STAGE_B.md` for model evidence, `docs/STAGE_C.md` for the causal bridge and latency evidence, [docs/STAGE_D.md](STAGE_D.md) for daily operation, `docs/DOUBAO_AB.md` for the transcription A/B protocol, and `docs/HUMAN_RECORDING.md` for the single concentrated human recording step. For a physically isolated workstation, start with [the Mac B offline continuation package](MAC_B_CONTINUATION.md).

The accepted next phase has two separate tracks: keep the current Mac A build as an Experimental Alpha without weakening its warnings, and investigate quality improvements offline. The measured cost, data limits, consent boundary, and stop/go gates for adapting the current checkpoint are in [the fine-tuning feasibility note](FINE_TUNING_FEASIBILITY.md).

All future quality candidates must use the frozen, private [real-environment regression protocol](QUALITY_REGRESSION.md). The audio remains outside Git; only the protocol and evidence boundary are versioned.

The first bounded personalized fine-tuning experiment is documented in [the 2026-09-22 PoC report](FINE_TUNING_POC_20260922.md). Both candidates were rejected: 40 steps regressed controlled validation, while the 4-step model removed part of the user's voice without a meaningful target-absent improvement. The Experimental Alpha remains unchanged.

An independent [target-presence auxiliary-gate PoC](TARGET_PRESENCE_GATE_POC_20260922.md) was also rejected before integration: its public example and Mac A runtime passed, but it classified 90.24% of the held-out target-absent Q02 chunks as the target at threshold 0.5. No gate audio was generated and the live chain remains unchanged.

Before enabling the live bridge on any machine, run the pre-launch benchmark and paced latency check described in [the performance guide](PERFORMANCE_GUIDE.md); the live bridge has no default `--frames-per-chunk` by design.

The Stage-D product controller now supports privacy-first background `start`, lifecycle-aware `status`, safe `pause`/`resume`, `stop`, microphone-only `set-input`, and stopped-only `set-policy`. Background mode deliberately refuses raw-passthrough policy until a persistent degraded-warning UI exists; see [daily operation](STAGE_D.md).

A native SwiftUI [menu-bar controller](MENU_BAR_APP.md) wraps those commands with visible state, controls, microphone selection, and permanent quality warnings. It remains a local Experimental Alpha shell and does not bundle the model or change its quality claims.

Mac B's returned thread sweep and ONNX CPU results are recorded in [the 2026-09-18 runtime report](MAC_B_RUNTIME_RESULTS_20260918.md). INT8 correctness failed. The corrected CoreML auto/four-thread matrix also failed with best RTF 1.052, so `CURRENT REAL-TSE ON M1: STOP`; see [the final thread recheck](MAC_B_COREML_THREAD_RECHECK_RESULTS_20260918.md). The next-model source gate and screened candidates are recorded in [the lightweight TSE screening](LIGHTWEIGHT_TSE_SCREENING_20260918.md).

After BlackHole has been restored on Mac A, use [the Mac A live-acceptance handoff](MAC_A_LIVE_ACCEPTANCE_HANDOFF.md) for the physical bridge, stability, and manual-experience checks. The one-shot user procedure (enrollment, 120 s dictation, 30-minute Doubao check, restore) is [MAC_A_LIVE_SESSION.md](MAC_A_LIVE_SESSION.md).

Mac A now also has an auditable [runtime-envelope harness](MAC_A_RUNTIME_ENVELOPE.md). It validates queue, latency, jitter-prefill and fault-silence behavior under deterministic per-call service-time distributions; it does not claim to emulate Mac B's M1 performance.
