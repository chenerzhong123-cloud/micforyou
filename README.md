# MicForYou

MicForYou keeps Doubao IME as the ASR/text layer and sends locally processed audio to it through BlackHole 2ch. BlackHole → Doubao routing is verified. A free local REAL-TSE causal checkpoint now passes synthetic effect and stateful-streaming checks. Real headset recordings, live-device latency, Doubao A/B, and the 30-minute run are still pending; this project does not yet claim daily usability.

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

See `docs/STAGE_A.md` for routing acceptance and recovery, `docs/STAGE_B.md` for model evidence, `docs/STAGE_C.md` for the causal bridge and latency evidence, and `docs/HUMAN_RECORDING.md` for the single concentrated human recording step.
