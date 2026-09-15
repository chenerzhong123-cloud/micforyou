# One-time human recording and live-test gate

Do this only after the everyday headset is connected. Reserve about 25 minutes so recording, permissions, live routing and Doubao A/B can be completed in one session. The three files stay local under `/Users/deuce/claudeproject/codexworks/micforyou/test-data/human/` and are excluded from version control.

## Before recording

1. Connect the headset normally and leave macOS output on the headset.
2. Reply `耳机已连接，可以录音和测试`. The agent will detect the exact microphone name; do not copy device identifiers manually and do not change Doubao yet.
3. If macOS displays a microphone permission dialog for Terminal/Python/Codex, allow it once. No Accessibility, Screen Recording, or administrator permission is required for recording.
4. Sit in a quiet position and keep the microphone where it is used day to day. Use normal speech and genuinely quiet speech, not whispering.

## Three recordings

The agent starts each capture with a five-second countdown and announces which text to read.

### 1. Enrollment — 50 seconds

Speak naturally about familiar work or daily topics. Include several short pauses, numbers, English product names, and two or three quieter sentences. Do not read either test passage below.

### 2. Independent normal test — 20 seconds

`我正在测试一套只保留本人声音的麦克风工具。今天的会议改到下午三点，文档编号是二零二六。Please review the final version before Friday. 这段话只用于测试，不属于注册语音。`

### 3. Independent quiet test — 20 seconds

`现在我会用比平时更轻的声音继续说话。即使旁边有人交谈，句子的开头、数字七十三和最后几个字也应该尽量保留。这里是轻声测试的结尾。`

## Privacy and use

- Audio is used only for local TSE evaluation; it is not sent to an ASR service by MicForYou.
- Doubao remains the ASR layer only during later routing acceptance.
- Daily audio is not saved. These explicit enrollment/test files may be removed after evaluation if requested.
- Enrollment and test passages remain separate so the model is not scored on the same speech it enrolled from.

## What happens immediately afterward

The agent will perform the remaining work in this order without asking for device identifiers:

1. verify the three files and build controlled 0/-6/-12 dB plus target-absent mixtures locally;
2. compare raw and REAL-TSE output, then present only the ambiguous listening decisions;
3. start the causal bridge with the headset as input and BlackHole 2ch as output;
4. ask you once to select BlackHole 2ch in Doubao and run the prepared short/long/quiet phrases;
5. run a controlled overlap check using public licensed interference; if audible speaker playback is needed, it will be stated before playback and the original system output will be restored;
6. measure live latency/fault behavior, then start the unattended 30-minute stability run;
7. restore Doubao to the headset microphone and verify it visibly.

No Accessibility or Screen Recording permission is part of this plan. If macOS shows a microphone dialog, approve only the named local process currently being used; a delayed or missed dialog is recorded and retried rather than guessed about.
