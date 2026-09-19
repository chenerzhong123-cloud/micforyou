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

Mac A may complete the post-source correctness, private-recording quality and bridge stress work before Mac B is available. Cross-machine stress uses the [runtime-envelope harness](MAC_A_RUNTIME_ENVELOPE.md), not CPU throttling, and never replaces the final real M1 benchmark.

## One-shot Mac B handoff after the artifact becomes available

The source block does not require two separate Mac B assignments. Once the exact model files and the compatible enrollment encoder are locally available, give this whole section to the Mac B Agent. It must run the phases in order and continue automatically only when the preceding gate passes. A small file size is a reason to expect a cheaper runtime, not evidence that runtime or extraction quality passes.

### Fixed boundaries

- Use the latest `main` from `https://github.com/chenerzhong123-cloud/micforyou.git` and record the commit.
- Mac B does not commit or push. New reusable scripts and sanitized reports go into the return bundle for Mac A review.
- Keep Doubao as the only ASR. Do not install, implement or invoke another ASR.
- Do not upload or commit recordings, enrollment audio/vectors, model weights, extracted audio or transcripts.
- Reuse the existing private Mac B enrollment, normal and quiet recordings. Do not ask the user to record again during these offline phases.
- The 192-dimensional conditioner must be produced by the exact ECAPA implementation/revision expected by the TSE checkpoint. A vector with the right shape but unknown provenance is not valid conditioning.

### Phase 0 — source and environment gate

Record the revision, license text, byte count and SHA-256 for the ONNX graph, its external data file, and the exact ECAPA model/config needed for enrollment. Verify that all artifacts can be restored from a stable source without a paid service or expiring trial.

If any artifact is missing, its provenance is ambiguous, or the model/conditioner pairing cannot be established, stop with `SOURCE_BLOCKED`. Do not substitute random, zero or unrelated 192-dimensional conditioning for a quality test.

### Phase 1 — graph and state correctness

Verify the published contract rather than trusting filenames:

- input audio is mono float32 `[1, 480]` at 48 kHz;
- conditioning is float32 `[1, 192]`;
- every state input has one matching state output with identical shape and dtype;
- output is exactly 480 samples per call;
- state is passed forward across calls, never reset per chunk;
- at least 1,000 consecutive deterministic chunks produce exact total length, finite samples and bounded state values;
- two runs with identical input, conditioning and zero state are reproducible;
- changing conditioning changes the output on a non-silent mixture.

Also run a pure-silence probe. Any NaN/Inf is a correctness failure unless a deterministic, inaudible mitigation is explicitly implemented, measured and returned for review. Do not silently hide the failure.

If this phase fails, stop with `CORRECTNESS_FAIL`; do not benchmark or evaluate private speech.

### Phase 2 — complete-path runtime gate

Benchmark the actual streaming wrapper, including ONNX Runtime feed/state transfer and output scheduling. Enrollment encoding is a startup cost: report it separately, but do not include it in steady-state RTF. Use a 3-second warm-up followed by at least 60 seconds of deterministic synthetic 48 kHz input. Test ORT `auto`, 1, 2 and 4 intra-op threads unless a setting is unsupported.

For each candidate report:

- requested/effective threads and provider order;
- measured seconds, audio seconds and RTF;
- call p50/p95/max in milliseconds;
- cold session creation and enrollment-encoding time;
- input/output sample counts, non-finite count, output peak/RMS and maximum state magnitude;
- process RSS and machine/environment metadata.

Continue only if at least one valid candidate has both `RTF <= 0.8` and per-10-ms-call `p95 <= 10 ms`. Select the lowest-p95 passing candidate; use RTF as the tie-breaker. If none passes, stop with `RUNTIME_FAIL`; do not use batching that increases model cadence merely to improve RTF without charging that wait to latency.

### Phase 3 — private Mac B filtering-effect gate

Only after Phase 2 passes, compute a real ECAPA conditioner from the private enrollment and reuse the existing deterministic mixture protocol: independent normal and quiet test clips, the same public interferer, seed `20260913`, target/interferer ratios 0, -6 and -12 dB, plus target-absent. Enrollment and test speech must remain different clips.

For every target-present case report mixture SI-SDR, output SI-SDR, SI-SDRi, output RMS/peak, exact length and non-finite count. For target-absent report attenuation in dB, output RMS/peak and any speaker-similarity diagnostic, clearly labeled non-independent when it uses the same ECAPA family as conditioning.

Use this provisional continuation floor:

- all six target-present outputs have exact length, finite samples and no clipping;
- normal and quiet at 0 and -6 dB each achieve SI-SDRi >= +3 dB;
- none of the six target-present cases has negative SI-SDRi;
- target-absent attenuation is >= 20 dB.

The -12 dB cases remain a stress boundary, but a negative SI-SDRi is still a rejection signal. Passing these numeric floors yields only `OFFLINE_CANDIDATE`; it does not prove subjective intelligibility, Chinese generalization or daily usability. Preserve selected outputs locally on Mac B for a later human Doubao A/B, but do not include them in Git or the sanitized return bundle.

If the floor fails, stop with `QUALITY_FAIL`. If it passes, write `OFFLINE_CANDIDATE` and prepare the next paced/live handoff; do not start BlackHole, Doubao or a 30-minute run in this unattended task.

### Return bundle

Create a timestamped directory outside the Git repository containing only:

- `ENVIRONMENT.txt`;
- `LIGHTWEIGHT_TSE_RESULTS.md` with the exact terminal decision;
- source/correctness/runtime/quality JSON reports;
- any new generic scripts and tests needed to reproduce the probes;
- `MANIFEST.txt` with SHA-256 and byte count for every returned file.

Before packaging, scan for private absolute paths and for `.wav`, `.flac`, `.m4a`, `.npy`, `.onnx`, `.pt` and `.pth` files. The first scan must be sanitized; the second must find no private/model artifact. Return the directory by AirDrop, USB or task attachment. Mac A performs code review, tests, Git commit and push.

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

Resume model work when the v3 files reappear at a stable pinned revision, the owner publishes an equivalent permanent artifact, or another causal waveform TSE with usable weights satisfies the source gate. Prefer a cheap model-load probe on Mac A when the files are available there. If only the physically isolated Mac B has the complete artifacts and private recordings, its Agent may execute the one-shot gated handoff above; it must not cross a failed gate.
