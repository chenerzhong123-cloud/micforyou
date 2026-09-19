# Lightweight TSE screening — 2026-09-18

## Decision

As of the 2026-09-19 follow-up, there is no candidate ready for a Mac B
benchmark. The original cutoff was a model-supply block; the resumed search found
and ran one additional causal checkpoint, which then failed the fixed quality
gate. Do not send Mac B another runtime task until a new pinned candidate passes
the source, correctness, Mac A runtime and private-recording quality gates. This
is not a Mac B hardware block.

### 2026-09-19 follow-up: source found, candidate stopped at quality gate

The search was resumed instead of treating the missing `tse-conv-tasnet-48k`
artifact as the end of the candidate space. One additional causal candidate passed
the source and preliminary Mac A runtime gates:

- source: `xu-shitong/TSE-through-Positive-Negative-Enroll` commit
  `c8fb49bdd2a25f0753563b2884fd49c2a35ee8e6`;
- checkpoint: Hugging Face revision
  `86f664b56ca0e315475d3579f54e407e0470ee32`, file
  `proposed-monaural.pt`, 7,871,086 bytes, SHA-256
  `3bc59b34334db782e8070486883b9433cd373d5d730001032d80efe96ae833b4`;
- model: 16 kHz monaural causal TF-GridNet, 1,875,883 parameters, with
  explicit recurrent/attention/ISTFT state;
- weight license: CC BY-NC-ND 4.0 according to the Hugging Face repository
  metadata. The GitHub code repository has no root license, so this remains a
  local research probe and is not cleared for distribution.

This model uses a different registration contract: a positive enrollment where
the target is speaking and a negative enrollment from the same environment where
the target is silent. It is not a drop-in persistent voiceprint model.

The recovery priority for the missing v3 artifact is also lower than previously
recorded. AmphionRuntime's independent
[causal TSE landscape and evaluation](https://github.com/amphionspace/AmphionRuntime/blob/main/docs/speaker/CAUSAL_TSE_MODEL_LANDSCAPE_20260806.md)
reports that the v3 checkpoint leaked the complete interferer in its
target-absent case, produced non-finite output on silence, and had 83.33% CER on
its controlled target-present case. Those results are not a substitute for our
own artifact verification, but they are sufficient evidence not to spend more
time trying to recover a now-private checkpoint before testing an accessible
alternative.

The deterministic Mac A CPU probe found:

| Check | Result |
| --- | --- |
| 60 s, 256 samples / 16 ms, 2 threads | RTF 0.555; call p50/p95/max 8.69/9.68/31.20 ms |
| length/state/repeatability | 960,000 samples in/out; finite state; identical rerun |
| exact-zero input | failed: all 256 output samples were non-finite |
| whole vs 256-sample chunks | failed exact parity; max/mean absolute delta 0.0229/0.00545 |
| official four examples, whole input | SI-SDR 7.26–9.23 dB, close to the supplied outputs |
| official four examples, 4096-sample chunks | SI-SDR 5.92–8.53 dB |

The official examples establish that the checkpoint and invocation are correct.
The remaining chunk discrepancy is real: the upstream input STFT does not expose
its waveform overlap as session state, and normalization is applied independently
to each call. A deterministic zero-input bypass could prevent NaNs, but it would
not repair extraction quality or make the missing front-end state disappear.

The private Mac B recording gate used the independent 60-second enrollment and
the existing normal/quiet 0/-6/-12 dB mixtures. To honor this model's contract,
the positive enrollment combined a high-energy three-second target segment with
the same public interferer, while the negative enrollment contained that
interferer without the target. No private audio, embedding, output or transcript
was added to Git. With 4096-sample / 256 ms causal chunks:

| Voice | 0 dB SI-SDRi | -6 dB SI-SDRi | -12 dB SI-SDRi | target-absent attenuation |
| --- | ---: | ---: | ---: | ---: |
| normal | **-3.42 dB** | +5.23 dB | +11.14 dB | 31.27 dB |
| quiet | **-3.19 dB** | +3.40 dB | +9.48 dB | 31.27 dB |

The alternative, simpler enrollment construction (clean target positive;
interferer-only negative) also failed, including -8.32 dB and -3.68 dB SI-SDRi
for the two 0 dB cases. The model therefore stops at `QUALITY_FAIL`: both 0 dB
cases regress, violating the fixed rule that no target-present case may have
negative SI-SDRi. Its good target-absent attenuation and low RTF are useful
signals, but cannot override that failure. BlackHole, Doubao, paced live use and
Mac B benchmarking are not run for this checkpoint.

Reproducible synthetic probing is implemented in
`experiments/probe_posneg_tse.py`; its isolated environment is pinned in
`experiments/requirements-posneg-tse.txt`. Sanitized JSON results remain outside
Git under `codexworks/micforyou/runs/posneg-tse-20260919/`.

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
| `penta2himajin/tse-conv-tasnet-48k` v3 | blocked at source gate; do not prioritize recovery | artifact currently returns 404/401; an independent 2026-08 AmphionRuntime evaluation also reports target-present, target-absent and silence failures for v3 |
| Positive/Negative Enrollment TSE, causal monaural | rejected at quality gate | source and Mac A runtime pass; normal/quiet 0 dB cases regress, exact silence is non-finite, and small-chunk parity fails |
| REAL-TSE causal TFMap BSRNN | rejected for M1 live path | selected on controlled quality tests, but Dynamic INT8 failed correctness and corrected CoreML still had best RTF 1.052 on Mac B M1 |
| ESPnet TD-SpeakerBeam LibriMix | rejected for live path | published config is non-causal and 8 kHz; not a bounded streaming candidate |
| OpenSpeakerBeam-SS | previously rejected | full-sequence behavior, clipping and target-absent amplification in this project's earlier tests |
| VoiceFilter-Lite | incompatible output contract | filters ASR features and does not provide the waveform required by BlackHole -> Doubao |
| DENSE / WeSep alternatives without weights | source gate fail | no ready, pinned personalized checkpoint; from-scratch training is outside the spec |

Ordinary noise suppressors such as DeepFilterNet remain out of scope as substitutes: they remove noise but do not isolate an enrolled speaker during overlapping speech.

## Resume trigger

Resume model integration when a new causal waveform TSE with usable pinned
weights satisfies the source gate. Reappearance of the old v3 files alone is no
longer sufficient because independent quality evidence is negative; it would
need a materially revised checkpoint and fresh provenance. Prefer a cheap model
load and synthetic probe on Mac A, then run the private-recording quality gate on
Mac A before involving Mac B. If only the physically isolated Mac B has the
complete artifacts and private recordings, its Agent may execute the one-shot
gated handoff above; it must not cross a failed gate.
