# Lightweight TSE screening — 2026-09-18

## Decision

There is no reproducibly obtainable candidate ready for a Mac B benchmark at this cutoff. Do not send Mac B another runtime task until a pinned model artifact passes the source gate below. This is a model-supply block, not a Mac B hardware block.

The best paper fit is `penta2himajin/tse-conv-tasnet-48k` v3: causal 48 kHz waveform-to-waveform ONNX, 10 ms chunks, explicit state, 1.45 M parameters and CC BY 4.0. Its cached model card reports held-out-speaker SI-SDR of +8.55 dB. It is materially different from the earlier broken v1 export because v3 claims corrected EMA export and a speaker-disjoint split.

However, on 2026-09-18 both the browser page and direct model endpoints returned 404/401 without authentication. The public search index was several weeks stale. The model and external weight file therefore cannot currently be pinned, hashed or independently loaded. A vanished or private artifact does not meet the project's reproducibility requirement, regardless of its model-card claims.

## Source gate for the next candidate

A candidate may enter local testing only when all of these are true:

1. The exact graph and all external data files can be downloaded without paid service or expiring trial access.
2. The revision and SHA-256 of every required artifact are recorded.
3. The checkpoint license permits the intended local evaluation; redistribution is assessed separately.
4. The model produces a target waveform and accepts enrollment conditioning. A diarizer, ASR feature filter, ordinary denoiser or hard voice gate is not a TSE replacement.
5. The temporal path is causal or has bounded look-ahead compatible with the 500 ms end-to-end target.
6. Enrollment can be computed locally without adding an ASR system.

After the source gate, testing order is fixed:

```text
load/state correctness
  -> deterministic synthetic runtime (continue only if RTF <= 0.8)
  -> Mac B private normal/quiet 0/-6/-12 dB + target-absent quality
  -> paced latency
  -> physical BlackHole -> Doubao
  -> 30-minute stability and fault drills
```

No user recording, enrollment vector, model weight or transcript is committed to Git.

## Candidates screened out for now

| Candidate | Current disposition | Reason |
| --- | --- | --- |
| `penta2himajin/tse-conv-tasnet-48k` v3 | blocked at source gate | best architectural fit, but artifact currently returns 404/401 and cannot be pinned |
| REAL-TSE BSRNN CoreML | rejected for live path | fixed eight-second separator, non-causal BSRNN; minimum context already exceeds the latency budget |
| ESPnet TD-SpeakerBeam LibriMix | rejected for live path | published config is non-causal and 8 kHz; not a bounded streaming candidate |
| OpenSpeakerBeam-SS | previously rejected | full-sequence behavior, clipping and target-absent amplification in this project's earlier tests |
| VoiceFilter-Lite | incompatible output contract | filters ASR features and does not provide the waveform required by BlackHole -> Doubao |
| DENSE / WeSep alternatives without weights | source gate fail | no ready, pinned personalized checkpoint; from-scratch training is outside the spec |

Ordinary noise suppressors such as DeepFilterNet remain out of scope as substitutes: they remove noise but do not isolate an enrolled speaker during overlapping speech.

## Resume trigger

Resume model work when the v3 files reappear at a stable pinned revision, the owner publishes an equivalent permanent artifact, or another causal waveform TSE with usable weights satisfies the source gate. The first resumed action is a model-load/state/runtime probe on Mac A; Mac B is used only after that cheap gate passes.
