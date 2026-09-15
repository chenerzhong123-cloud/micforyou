# Mac B + wired headset evaluation

Date: 2026-09-15. Scope: offline evaluation of recordings captured on the intended workstation/microphone combination, Mac B with the user's wired headset.

## Input validity

The capture manifest reports macOS 15.7.3 on arm64 and an external mono 48 kHz microphone. The recordings are independent 60 s enrollment, 25 s normal test, and 25 s quiet test WAV files at 48 kHz/24-bit. Their checksums matched the capture manifest; no clipping or non-finite samples were found. The quiet test's median 20 ms RMS is -46.53 dBFS compared with -40.08 dBFS for normal speech, so it is a genuinely lower-level condition.

Raw recordings and generated audio are deliberately excluded from this repository.

## Controlled user-voice separation

- Enrollment is distinct from both test clips.
- A fixed public non-target speech sample was deterministically cropped and mixed at 0, -6, and -12 dB target/interferer ratios using full-waveform RMS and seed `20260913`.
- Model: REAL-TSE causal TFMap+context, checkpoint SHA-256 `97c01b79b0cf1a5b914a4a3bc1113c1864752ebdd320f528e77a53202447fef2`.
- No ASR was used. Speaker cosine is a diagnostic only and uses an explicit 48 kHz to 16 kHz resample before the pinned ECAPA encoder.

| Input condition | 0 dB SI-SDRi | -6 dB SI-SDRi | -12 dB SI-SDRi | Mean CPU RTF |
| --- | ---: | ---: | ---: | ---: |
| normal user speech | +10.58 dB | +15.61 dB | +19.32 dB | 0.481 |
| quiet user speech | +10.50 dB | +16.23 dB | +20.82 dB | 0.483 |

The target/enrollment speaker cosine is 0.837–0.844 for normal speech and 0.722–0.724 for quiet speech. Extracted normal speech is 0.722–0.765; extracted quiet speech is 0.374–0.519. Quiet -12 dB therefore still requires listening evaluation even though SI-SDRi is strong.

For a 25-second non-target-only input, output RMS is 33.47 dB below mixture RMS and enrollment cosine is 0.125. This is controlled-case suppression, not a calibrated real-world presence threshold.

## Stateful and runtime boundary

For the quiet -12 dB mixture, the explicit-state 8-frame path was numerically equivalent to whole-utterance inference (131.49 dB aligned SNR), proving the causal adaptation preserves output quality for this user audio.

It does not prove Mac B's live performance. Evaluation ran on the development Mac after the recordings were transferred. Under current desktop load on that host, complete 48→16→48 kHz simulation measured RTF 1.42 for 8 frames, 0.92 for 16 frames, and 0.70 for 24 frames. Mac B must benchmark locally before selecting the real-time chunk size. The bridge has no silent chunk default.

## Status

Mac B + wired headset offline effect: `PASS`.

Real noisy-workplace audio, Mac B compute performance, physical headset → BlackHole → Doubao, end-to-end p95 latency, fault handling, and 30-minute stability: `NOT RUN`.
