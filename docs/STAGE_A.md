# Stage A — BlackHole → Doubao validation

Status: `PARTIAL PASS` — BlackHole loopback and BlackHole → Doubao route are verified. The everyday-headset passthrough, three-repeat Doubao check, and final restore check still require the headset and human speech.

The first Doubao result was `今天是星期日，编号2026。` for the fixed route-test sentence. Its missing prefix is recorded as an un-attributed local anomaly. It is not being used to change buffering or permission behavior without a controlled reproduction.

## Safety properties

- The bridge explicitly opens one physical input and `BlackHole 2ch` as output.
- It rejects BlackHole as input, rejects a same-device route, and does not touch system output.
- It does not record or persist microphone audio. Run metadata contains device names, rates, timings, and stream errors only.
- On exit, the stream closes. If system default input was changed manually, restore it manually; this prototype does not change defaults itself.

## Acceptance procedure

1. Close audio applications, install BlackHole 2ch, and restart macOS when prompted.
2. Connect the everyday headset. Run `uv run micforyou devices` and copy its exact input device name.
3. Open Doubao IME Settings → Voice Input → Microphone Selection and choose `BlackHole 2ch`. This selector was verified in Doubao IME 1.0.0, so do not change the macOS default input. Keep system output on the existing headphones/display.
4. Start Doubao recording, then run the known-file command from README. Expected text: `这是麦克风链路测试，今天是星期日，编号二零二六。`
5. Repeat step 4 three times. Record exact output, whether the beginning/end was clipped, and whether each attempt was usable.
6. Start Doubao recording, run passthrough with the physical headset name, and speak the short test sentences below. Stop the bridge with Ctrl-C after the test.
7. In Doubao, restore the physical microphone. Confirm ordinary microphone input works.

## Short test sentences

1. `现在测试第一句话。`
2. `轻声说话也需要保留开头和结尾。`
3. `最后一句用于检查停止录音会不会截断尾音。`

Record results in `/Users/deuce/claudeproject/codexworks/micforyou/phase-a-acceptance.md`. Do not include sensitive dictated content.
