# MicForYou

MicForYou keeps Doubao IME as the ASR/text layer and sends locally processed audio to it through BlackHole 2ch. BlackHole → Doubao routing is verified. A free local REAL-TSE causal checkpoint passes offline effect and stateful-streaming checks, but Mac B M1 measurements now close its deployment path: PyTorch, ONNX Runtime CPU, Dynamic INT8 and corrected CoreML experiments all fail their required gate. The current REAL-TSE model is not a daily-use runtime on that machine. Lightweight TSE selection is blocked until a reproducibly downloadable causal waveform model satisfies the source gate.

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

See `docs/STAGE_A.md` for routing acceptance and recovery, `docs/STAGE_B.md` for model evidence, `docs/STAGE_C.md` for the causal bridge and latency evidence, `docs/DOUBAO_AB.md` for the transcription A/B protocol, and `docs/HUMAN_RECORDING.md` for the single concentrated human recording step. For a physically isolated workstation, start with [the Mac B offline continuation package](docs/MAC_B_CONTINUATION.md).

Before enabling the live bridge on any machine, run the pre-launch benchmark and paced latency check described in [the performance guide](docs/PERFORMANCE_GUIDE.md); the live bridge has no default `--frames-per-chunk` by design.

Mac B's returned thread sweep and ONNX CPU results are recorded in [the 2026-09-18 runtime report](docs/MAC_B_RUNTIME_RESULTS_20260918.md). INT8 correctness failed. The corrected CoreML auto/four-thread matrix also failed with best RTF 1.052, so `CURRENT REAL-TSE ON M1: STOP`; see [the final thread recheck](docs/MAC_B_COREML_THREAD_RECHECK_RESULTS_20260918.md). The next-model source gate and screened candidates are recorded in [the lightweight TSE screening](docs/LIGHTWEIGHT_TSE_SCREENING_20260918.md).

After BlackHole has been restored on Mac A, use [the Mac A live-acceptance handoff](docs/MAC_A_LIVE_ACCEPTANCE_HANDOFF.md) for the physical bridge, stability, and manual-experience checks. The one-shot user procedure (enrollment, 120 s dictation, 30-minute Doubao check, restore) is [MAC_A_LIVE_SESSION.md](docs/MAC_A_LIVE_SESSION.md).
