# Doubao A/B transcription protocol

Purpose: compare recognizability, not subjective listening, for the most difficult controlled condition: the Mac B wired-headset quiet test mixed with louder non-target speech at -12 dB.

This protocol runs on the current Mac only. It verifies the existing BlackHole → Doubao route and must not be reported as a Mac B device/latency result.

## One-time setup

1. In Doubao IME Settings → Voice Input → Microphone Selection, choose `BlackHole 2ch`.
2. Keep macOS system output unchanged.
3. Start Doubao voice input using the normal shortcut. The playback command begins only after it is visibly recording.
4. After all tests, restore Doubao's microphone selection to the usual physical microphone.

## Test order

Run each item as a separate Doubao recording. Do not replay until its output has been copied verbatim into the result record.

| ID | Playback | Expected outcome |
| --- | --- | --- |
| DB-01 | quiet -12 dB raw mixture | negative control; competing speech should make this worse than DB-02 |
| DB-02 | quiet -12 dB extracted target | intended test text should be materially more complete than DB-01 |
| DB-03 | target-absent extracted output | no meaningful dictated phrase; any stable non-empty text is a false-positive signal |

The intended DB-02 text is:

`现在我会用比平时更轻的声音继续说话。即使旁边有人交谈，句子的开头、数字七十三和最后几个字也应该尽量保留。这里是轻声测试的结尾。`

## Interpretation

Count omitted content words, substitutions, insertions, and clipped beginning/end. Do not grade punctuation or Chinese numeral normalization as errors. DB-02 must improve materially over DB-01; a single lucky transcription is not enough. DB-03 does not prove presence detection by itself, because Doubao can emit text from tiny residual sound or its own decoder behavior.

Raw and extracted audio stay local and are excluded from Git. Store only exact transcriptions and non-audio timing notes in a local acceptance record.
