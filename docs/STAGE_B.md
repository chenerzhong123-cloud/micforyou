# Stage B — offline TSE baseline and selection

Status: `PARTIAL PASS`. Synthetic, public-real-data, and Mac B+wired-headset controlled user-voice comparisons select REAL-TSE `tfmap_context_causal_100`. A genuine noisy-workplace recording remains `NOT RUN`.

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

## License boundary

REAL-TSE source commit `2a540977a348fbaa92e623210505430e2cec608d`; causal TFMap weight SHA-256 `97c01b79b0cf1a5b914a4a3bc1113c1864752ebdd320f528e77a53202447fef2`. New source files carry Apache-2.0 SPDX headers, but the repository has no root license and the checkpoint license is not stated. It is acceptable for the current local experiment, not cleared for redistribution or a commercial product.

## Remaining gate

Capture separate 45–60 s enrollment, normal test, and quiet test recordings with the everyday headset. Then run the same model on Chinese speech and do audio plus Doubao A/B acceptance. Until then Stage B is not fully passed and no claim of daily usability is allowed.
