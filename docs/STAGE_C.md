# Stage C — causal core and real-time bridge

Status: `PARTIAL PASS`. The causal/stateful processing core passes equivalence and CPU timing checks. Physical-headset → model → BlackHole, end-to-end p95, Doubao boundaries, fault injection, and 30-minute stability remain `NOT RUN`.

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
