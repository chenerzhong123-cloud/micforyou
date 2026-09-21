# Stage B — offline TSE baseline and selection

Status: `USER-ACCEPTED PARTIAL EFFECT / HARD TARGET-ABSENT MISS`. Synthetic, public-real-data, and Mac B+wired-headset controlled user-voice comparisons selected REAL-TSE `tfmap_context_causal_100`. In a genuine workplace sample the user heard useful reduction of background speech/noise and accepted the current effect as worth continuing, but a target-absent region still preserved intelligible non-target speech. The checkpoint remains experimental and cannot be described as strict privacy isolation.

## Controlled synthetic protocol

- Enrollment and target test utterances are different clips from one speaker; the interferer is independent.
- Mixtures use full-file RMS, seed `20260913`, deterministic repeat/crop, and peak-safe scaling.
- Cases are target/interferer ratios 0, -6, and -12 dB plus target absent.
- Inputs, metadata, outputs, hashes, and score JSON live under `/Users/deuce/claudeproject/codexworks/micforyou/`.

| Model | 0 dB SI-SDRi | -6 dB | -12 dB | Target-absent attenuation | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| old WeSep BSRNN + ECAPA | +17.54 | +20.10 | +22.90 | 39.49 dB | offline noncausal reference |
| REAL-TSE spk-embedding causal | +13.43 | +15.65 | +18.05 | 26.64 dB | viable causal baseline |
| REAL-TSE TFMap + context causal | +14.96 | +17.35 | +20.06 | 27.72 dB | selected |
| OpenSpeakerBeam-SS | +8.46 | +4.43 | -0.07 | **gain 26.28 dB** | rejected |

The selected TFMap model is consistently stronger than the causal speaker-embedding variant on these four controlled cases. The older noncausal model remains stronger offline but collapses under stateless chopping and cannot serve Stage C.

## Public Chinese meeting diagnostic

Six deterministic high-overlap DEV records were selected from REAL-T (three AISHELL-4 and three AliMeeting, unique mixture/speaker, overlap 0.79–0.88). REAL-T does not supply isolated clean targets, so SI-SDR cannot be computed. No ASR was run. A frozen ECAPA embedding is used only as a directional diagnostic, and outputs are preserved for later listening.

| Causal model | Mean mixture→enrollment cosine | Mean output→enrollment cosine | Improved records | Whole-utterance CPU RTF |
| --- | ---: | ---: | ---: | ---: |
| speaker embedding | 0.5154 | 0.5398 | 2/6 clearly improved | 0.230 |
| TFMap + context | 0.5154 | 0.5721 | 5/6 improved | 0.259 |

This supports selecting TFMap, but it is not a user-acceptance pass: the metric uses a related speaker encoder, one record regresses, and clean references are unavailable.

## Rejected alternatives

- OpenSpeakerBeam-SS uses a full-sequence FFT, returns no real state, clips badly, amplifies target-absent speech, and fails the -12 dB case.
- `penta2himajin/tse-conv-tasnet-48k` files return HTTP 401, and its associated source records catastrophic cross-corpus behavior.
- `ad3ldev/Realtime-Targeted-Speech-Enhancement` has GPL research code but no clearly identified trained personalized release.
- DPDFNet/DeepFilterNet are ordinary enhancement, not reference-conditioned TSE.

## Mac B + wired-headset user recording

The intended workstation/microphone combination supplied independent 60 s enrollment, 25 s normal, and 25 s quiet recordings: 48 kHz, mono, 24-bit; their checksums match the capture manifest and no clipping was detected. With the same deterministic interference protocol, normal speech achieves +10.58/+15.61/+19.32 dB SI-SDRi at 0/-6/-12 dB and quiet speech achieves +10.50/+16.23/+20.82 dB. Target-absent output energy is 33.47 dB below the input.

This confirms a real user voice and the intended headset can work with the model. It does not replace a real noisy-room sample or subjective listening, particularly because quiet-speech speaker similarity falls at -12 dB. Full evidence is in [Mac B evaluation](MAC_B_EVALUATION.md).

## Mac A genuine workplace recording

On 2026-09-21 the user identified diarization cluster `S03` as their own voice in a private 85-minute workplace recording. A 75-second local slice was processed with the current headset enrollment and FP32 ONNX runtime. Input and output were sample-exact in length, all samples were finite, processing RTF was 0.344, and model-call p95 was 21.76 ms.

Two shorter regions were then played through BlackHole to Doubao for human semantic acceptance:

- A 27-second `S03` region retained the expected target meaning with only minor repetition/word substitutions. Its RMS attenuation was about 1.8 dB.
- A 13-second target-absent `S01` region retained complete, intelligible non-target sentences in Doubao. Its RMS attenuation was only about 2.4 dB.

The private audio and verbatim workplace transcript are not committed. The target-absent result violates the MVP requirement that no recognizable colleague sentence reach Doubao. Good runtime, sample continuity, and target preservation cannot override this failure.

The user subsequently compared the private original and processed clips by ear and judged that processing did remove part of the other speech and noise. This is recorded as a subjective partial-effect acceptance and authorization to continue the project, not as a reversal of the target-absent evidence.

The frozen 25-second alternating-speaker Q03 comparison was also human-reviewed on 2026-09-22: the processed version was judged better, the user's voice remained complete, and the other voice was reduced. This is a positive alternating-speech result. It is not labeled simultaneous overlap, and it does not override the target-absent failure. See [real-environment quality regression](QUALITY_REGRESSION.md).

### Enrollment-window and presence-gate follow-up

The automatic 34–40 second enrollment window was compared with 20–26, 30–36 and 38–44 second windows on the same fixed regions. None repaired selectivity: the current and 38-second windows attenuated target/non-target by about `-1.82/-2.43 dB` and `-1.90/-2.62 dB`; the 20- and 30-second windows attenuated the target more than the non-target. The failure is therefore not explained by one unlucky 6-second selection.

The existing 16 kHz ECAPA branch was also evaluated as a possible target-presence diagnostic. Whole-region cosine was 0.642 for target and 0.541 for non-target, but 2-second sliding windows overlapped heavily: target median was 0.492 while non-target maximum was 0.532. A threshold would either leak some non-target windows or remove substantial target speech, and a 2-second decision window would exceed the real-time latency budget. No live presence gate is enabled from these uncalibrated scores.

## License boundary

REAL-TSE source commit `2a540977a348fbaa92e623210505430e2cec608d`; causal TFMap weight SHA-256 `97c01b79b0cf1a5b914a4a3bc1113c1864752ebdd320f528e77a53202447fef2`. New source files carry Apache-2.0 SPDX headers, but the repository has no root license and the checkpoint license is not stated. It is acceptable for the current local experiment, not cleared for redistribution or a commercial product.

## Remaining gate

Enrollment-window selection and the cheap presence-gate hypothesis are now closed. Further improvement requires either a stronger causal waveform TSE candidate or a fine-tuning experiment with independent clean target speech, representative consented interference, held-out target/non-target evaluation, and a new runtime gate. Fine-tuning the current checkpoint on the evaluation clip itself is not valid. A live Mac B stream remains untested, but it is not the current blocker: Mac A already demonstrates both the partial benefit and the hard target-absent miss. See [Doubao A/B](DOUBAO_AB.md).
