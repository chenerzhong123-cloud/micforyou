# Using MicForYou

[简体中文](USAGE.md) · [Back to README](../README.en.md)

This guide explains the real behavior of the menu-bar interface, performance requirements, data locations, troubleshooting, and known limitations. For installation and first-time registration see the [installation guide](INSTALL.en.md).

## Daily flow

After first-time setup, open the MicForYou menu, click "开始过滤" (Start filtering), wait for the "正在过滤" (Filtering) state, then dictate with Doubao IME.

The menu bar always shows: current status (e.g. "可以开始" Ready / "正在过滤" Filtering / "正在恢复" Recovering / "已安全静音" Safely muted), the current route (`physical microphone → BlackHole 2ch`), the currently recommended action, and the Settings entry. The `试用` (Trial) label is always visible.

## What each action really does

| Action | Audio sent to the input method | Microphone |
| --- | --- | --- |
| Start filtering | Filtered audio; silent until the model finishes loading | In use |
| Pause filtering | **Raw audio keeps flowing — yours, nearby speech, and background noise** | Still in use |
| Resume filtering | Rebuilds streaming state and resumes filtering without reopening devices | Still in use |
| End | Stops this route's audio output | Released |
| Quit interface | Background audio continues in the current mode | Still in use while running or paused |

**Pausing pauses filtering, not capture.** To turn the microphone off, click "结束" (End), then quit the interface. Changing the microphone or re-registering also requires "结束" first; while filtering is running, microphone selection and registration are locked in Settings. Pause and resume do not require re-selecting the Doubao input device.

MicForYou never changes the system default input. Full Doubao/BlackHole switching steps are in [“Setting up Doubao dictation”](#setting-up-doubao-dictation); the in-app Settings page also offers “查看设置步骤…” at any time, including while filtering is running.

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
- Prefer AC power. A failed performance check never requires reading aloud again: your voice is already saved — plug in power, close heavy apps, and choose “re-check performance”. The app automatically tries several candidate parameter sets, smallest chunk size first.

## Setting up Doubao dictation

1. **Confirm MicForYou's microphone**: in MicForYou Settings choose the MacBook microphone or your usual external microphone (a physical microphone, not BlackHole), and finish voice registration and the performance check.
2. **Let Doubao receive the processed audio**: open the Doubao IME settings and, if the current version offers a microphone/input-device option, choose **BlackHole 2ch** (Doubao's own device setting takes priority over the system input). If there is no such option: open System Settings → Sound → Input and select **BlackHole 2ch**; then return to Doubao, end the current dictation and start again. This affects other apps that follow the system input; after ending MicForYou, switch back to your physical microphone in the same place. System sound **output** keeps using your speakers/headphones — no aggregate or multi-output device needed.
3. **Start filtering, then dictate**: back in MicForYou click “开始过滤” (Start filtering), wait for the menu to show “正在过滤” (Filtering), then start Doubao dictation and say a short sentence to confirm text appears.

If no text appears or BlackHole is missing: first confirm MicForYou is filtering, then check the Doubao/system input device and microphone permission (System Settings → Privacy & Security → Microphone); after installing the driver, restart and refresh devices. “暂停过滤” (Pause) still forwards raw audio; only “结束” (End) stops capture.

## Where your data lives

Personal recordings, personalized models, configuration, and run reports are stored in `~/Library/Application Support/MicForYou/` and never uploaded:

- `config.json` — current configuration (devices, model paths, performance parameters); the `performance.json` next to it is the active registration's performance verdict, written only after a check passes or you explicitly approve a trial;
- `registrations/` — voice-registration audio and personal models. A failed performance check never removes the saved voice; each check's evidence (benchmark, per-candidate latency reports, structured attempt records) is kept in per-attempt directories under the candidate's `attempts/` folder and, like `performance-attempts/`, only the most recent 5 are kept — older ones are pruned automatically;
- `work/runs/` — run reports; logs contain no audio, embeddings, or IME text.

MicForYou's audio preprocessing and enrollment happen on your Mac; it implements no speech recognition and produces no text. Doubao's recognition and data handling follow Doubao's own policies — local preprocessing does not make the whole dictation flow offline.

## Troubleshooting

- **"需要完成设置" (Setup required):** check the driver, microphone, and registration progress in Settings; source users can also run `uv run micforyou status`.
- **Registration reports a recording problem** (too quiet, distorted, or not enough effective speech): follow the hint — keep a comfortable distance from the microphone, do not lower your voice, and read naturally and continuously for about 15 seconds before retrying. A failed check never affects the saved registration.
- **"Voice saved, but the performance check failed"**: not a recording problem, and you never need to read again. Plug in power, close heavy apps (video calls, downloads, builds), and choose "re-check performance"; your voice and personal model are kept, and an existing usable registration is unaffected.
- **"Dictation may lag a little"**: the link is stable but slower under the current machine load. Choose "still try it" (the menu keeps a "dictation may be slower" note while filtering) or re-check when the load drops.
- **"Re-check performance" prompt after an upgrade or microphone change**: verdicts are bound to the device, model, and app build; when those change, one re-check is required — no re-reading, your recording and model stay.
- **No text appears:** confirm the state is ready, Doubao selected `BlackHole 2ch`, and macOS microphone permission was granted to the actual recording process.
- **"Microphone still in use":** pause and quitting the interface both keep audio running; click "结束" (End) first, or run `uv run micforyou stop`.
- **Selected microphone disconnects:** the app shows "正在恢复" (Recovering) and stays silent until recovery; it never switches to another microphone automatically. Unrecoverable faults show "已安全静音" (Safely muted) with a retry option.
- **Faults while filtering:** default behavior is silence (privacy-first); an explicit pause is raw passthrough. The two states are distinct — a fault is never silently treated as a pause.

## Uninstalling

Choose "卸载 MicForYou…" at the bottom of Settings for a clean uninstall: the app and voice data are removed by default while the shared BlackHole driver is kept; you can also keep voice data for a reinstall. Details and manual steps are in the [installation guide](INSTALL.en.md#uninstalling).

## Known limitations

- Filtering reduces some nearby speech but **cannot guarantee complete isolation**; when you are not speaking, other people's voices may still be transcribed. This is not an authentication or privacy-isolation tool.
- Onboarding on a brand-new device, a 30-minute mixed real-microphone/Doubao run, and similar on-device acceptance are not complete yet. Pause passthrough has passed software checks and synthetic-input verification with the real ONNX model; that does not count as completed on-device acceptance.
- The app interface is currently Chinese-only; the combined installer is not Developer ID signed or notarized.
