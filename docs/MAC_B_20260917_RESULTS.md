# Mac B results — 2026-09-17

Scope: Mac B local performance benchmark plus a second independent wired-headset recording set. Raw audio, generated mixtures, outputs, benchmark JSON and device inventory remain outside Git under `/Users/deuce/claudeproject/codexworks/micforyou/`.

## Machine and performance decision

Mac B reports a MacBook Pro M1 (`MacBookPro17,1`, 8 CPU cores, 4 performance + 4 efficiency), macOS 15.7.3, AC power, Python 3.12.14, PyTorch 2.7.1 and one Torch inference thread. The repository commit was `19b1d5b`; the model source and checkpoint hashes match the pinned project values.

Two independent 60-second full-path benchmarks used deterministic synthetic audio and the complete 48 kHz → 16 kHz → TSE → 16 kHz → 48 kHz path. Both returned exact output lengths, finite samples and no evaluation errors, but every candidate was slower than real time:

| frames | first RTF | rerun RTF | rerun model-call p95 | decision |
| ---: | ---: | ---: | ---: | --- |
| 8 | 4.167 | 4.110 | 313.8 ms | unsupported |
| 16 | 2.512 | 2.478 | 360.4 ms | unsupported |
| 24 | 1.977 | 1.895 | 415.6 ms | unsupported |
| 32 | 1.680 | 1.625 | 487.2 ms | unsupported |

The second run reproduced the first after installation activity subsided. The current REAL-TSE TFMap checkpoint and CPU implementation therefore cannot sustain real time on this M1 host. Per the safety gate, paced, live, BlackHole and 30-minute bridge runs were correctly not attempted. Increasing the chunk again would reduce call overhead but would not repair both the RTF and the 500 ms latency budget.

The inventory was captured before the wired headset was connected and therefore listed only the built-in microphone/speaker and no BlackHole. The later recording manifest independently confirms that the wired headset appeared as a 48 kHz mono `外置麦克风`. This timing difference is not a data inconsistency.

## Second wired-headset recording set

The new manifest and WAV SHA-256 hashes match. Enrollment is 60 seconds; normal and quiet tests are 25 seconds each; all are mono 48 kHz/24-bit, finite and unclipped. Median 20 ms RMS is -30.44 dBFS for normal speech and -33.62 dBFS for quiet speech, so the quiet condition is about 3.2 dB lower in this take (the previous take differed by about 6.5 dB).

Using the same public interferer, seed `20260913`, 0/-6/-12 dB TIR protocol and pinned checkpoint:

| Input condition | 0 dB SI-SDRi | -6 dB SI-SDRi | -12 dB SI-SDRi | Mean Mac A evaluation RTF |
| --- | ---: | ---: | ---: | ---: |
| normal user speech | +10.87 dB | +15.46 dB | +18.78 dB | 0.433 |
| quiet user speech | +6.91 dB | +12.75 dB | +17.22 dB | 0.435 |

Target/enrollment cosine is 0.755–0.783 for normal speech and about 0.720 for quiet speech. Extracted/enrollment cosine falls from 0.666/0.688/0.604 for normal speech to 0.616/0.554/0.425 for quiet speech as interference increases. The second recording therefore confirms target extraction, but the quiet case is weaker than the 2026-09-15 set and still needs transcription/listening acceptance before any fidelity claim.

For target-absent public interference, output attenuation is 21.02 dB and output/enrollment cosine is 0.136. This is weaker suppression than the previous enrollment's 33.47 dB result. It remains a controlled diagnostic, not a calibrated presence detector; it is specifically a reason not to claim zero leakage.

## Result

- Mac B wired-headset offline target extraction: `PASS` on a second independent recording set.
- Current model's real-time performance on Mac B M1: `UNSUPPORTED`.
- Mac B live bridge, paced latency, BlackHole → Doubao and 30-minute stability: intentionally `NOT RUN` after the performance gate failed.
- The only useful immediate Mac B user test that does not depend on the bridge is the Doubao physical-microphone sentence-tail baseline described in `MAC_B_CONTINUATION.md` stage 2.

This result does not end the project. It establishes a product requirement: support for M1-class devices needs a materially cheaper model/backend (for example model compression, optimized deployment, or a smaller architecture), followed by the same effect and safety gates. Changing only the chunk size is not sufficient.
