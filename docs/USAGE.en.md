# Using MicForYou

[简体中文](USAGE.md) · [Back to README](../README.en.md)

This guide explains the real behavior of the menu-bar interface, performance requirements, data locations, troubleshooting, and known limitations. For installation and first-time registration see the [installation guide](INSTALL.en.md).

## Daily flow

After first-time setup, open the MicForYou menu, click "开始过滤" (Start filtering), wait for the "正在过滤" (Filtering) state, then dictate with Doubao IME.

The menu bar always shows: current status (e.g. "可以开始" Ready / "正在过滤" Filtering / "正在恢复" Recovering / "已安全静音" Safely muted), the current route (`physical microphone → BlackHole 2ch`), the currently recommended action, and the Settings entry. The `Alpha` label is always visible.

## What each action really does

| Action | Audio sent to the input method | Microphone |
| --- | --- | --- |
| Start filtering | Filtered audio; silent until the model finishes loading | In use |
| Pause filtering | **Raw audio keeps flowing — yours, nearby speech, and background noise** | Still in use |
| Resume filtering | Rebuilds streaming state and resumes filtering without reopening devices | Still in use |
| End | Stops this route's audio output | Released |
| Quit interface | Background audio continues in the current mode | Still in use while running or paused |

**Pausing pauses filtering, not capture.** To turn the microphone off, click "结束" (End), then quit the interface. Changing the microphone or re-registering also requires "结束" first; while filtering is running, microphone selection and registration are locked in Settings. Pause and resume do not require re-selecting the Doubao input device.

MicForYou never changes the system default input. If Doubao has no independent input-device selector, manually select BlackHole 2ch under System Settings → Sound → Input, and switch back to your physical microphone after ending. System output keeps using your regular speakers/headphones.

Source users who prefer Terminal can also use:

```bash
uv run micforyou status
uv run micforyou start
uv run micforyou pause   # raw passthrough; microphone keeps running
uv run micforyou resume  # resume filtering
uv run micforyou stop    # end and release the microphone
```

## Performance requirements

- **System:** macOS 14 or later, Apple Silicon. Intel Macs are unsupported.
- **Recommended device:** MacBook Air M5 is the only baseline validated over a longer run so far, with internal audio-path latency p95 ≈ 260 ms. That figure covers only MicForYou's internal audio path — not CoreAudio capture buffering, the BlackHole-to-IME transfer, or Doubao recognition time — and is not a latency promise for dictation as a whole.
- One tested M1 MacBook Pro achieved a best effective RTF of 1.052, below the real-time requirement; live filtering is unsupported on it.
- Other devices cannot be assumed supported by chip model alone; load and power state can move the same machine between passing and failing (the built-in check measures at registration time).
- Prefer AC power. If the performance check fails, retry registration.

## Where your data lives

Personal recordings, personalized models, configuration, and run reports are stored in `~/Library/Application Support/MicForYou/` and never uploaded:

- `config.json` — current configuration (devices, model paths, performance parameters);
- `registrations/` — voice-registration audio and personal models; successful old registrations are kept for rollback and may use extra space; failed candidates are cleaned up;
- `work/runs/` — run reports; logs contain no audio, embeddings, or IME text.

MicForYou's audio preprocessing and enrollment happen on your Mac; it implements no speech recognition and produces no text. Doubao's recognition and data handling follow Doubao's own policies — local preprocessing does not make the whole dictation flow offline.

## Troubleshooting

- **"需要完成设置" (Setup required):** check the driver, microphone, and registration progress in Settings; source users can also run `uv run micforyou status`.
- **No text appears:** confirm the state is ready, Doubao selected `BlackHole 2ch`, and macOS microphone permission was granted to the actual recording process.
- **"Microphone still in use":** pause and quitting the interface both keep audio running; click "结束" (End) first, or run `uv run micforyou stop`.
- **Selected microphone disconnects:** the app shows "正在恢复" (Recovering) and stays silent until recovery; it never switches to another microphone automatically. Unrecoverable faults show "已安全静音" (Safely muted) with a retry option.
- **Faults while filtering:** default behavior is silence (privacy-first); an explicit pause is raw passthrough. The two states are distinct — a fault is never silently treated as a pause.

## Known limitations

- Filtering reduces some nearby speech but **cannot guarantee complete isolation**; when you are not speaking, other people's voices may still be transcribed. This is not an authentication or privacy-isolation tool.
- Onboarding on a brand-new device, a 30-minute mixed real-microphone/Doubao run, and similar on-device acceptance are not complete yet. Pause passthrough has passed software checks and synthetic-input verification with the real ONNX model; that does not count as completed on-device acceptance.
- The app interface is currently Chinese-only; the combined installer is not Developer ID signed or notarized.
