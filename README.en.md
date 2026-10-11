# MicForYou

English · [简体中文](README.md)

## What is it?

https://github.com/user-attachments/assets/066f815d-fb09-4240-86b6-3538726c227a

The video above is a 55-second product demonstration (in Chinese). It is an animated illustration, not a measured before-and-after comparison.

**A shared space. Fewer voices in your sentence.**

MicForYou is a voice-filtering app for Mac. It uses your registered voice as a reference to reduce background noise and nearby speech, then sends the processed audio to Doubao IME for transcription. It is designed for open offices and shared workspaces where people are talking around you.

## Download and install (trial version)

**[Download MicForYou 0.2.2 trial version (Mac installer)](https://github.com/chenerzhong123-cloud/micforyou/releases/download/v0.2.2-trial/MicForYou-0.2.2-trial-macos-arm64.pkg)** · [Release notes and checksum](https://github.com/chenerzhong123-cloud/micforyou/releases/tag/v0.2.2-trial)

The installer is about 443 MB and includes the app, model, and audio components. Install it, open MicForYou, choose your microphone, and follow the in-app prompt to read aloud for about 15 seconds to register your voice. Then select **BlackHole 2ch** in Doubao IME to start using it. Restart your Mac when prompted after the first audio-component installation.

macOS may block this trial version on first use; see the [installation guide](docs/INSTALL.en.md) for instructions. When you stop using it, Settings offers a built-in [clean uninstall](docs/INSTALL.en.md#uninstalling).

[Installation guide](docs/INSTALL.en.md) · [Usage guide](docs/USAGE.en.md) · [Development guide](docs/DEVELOPMENT.en.md)

## Voice registration: a reading passage

Use your everyday microphone in a quiet room. Speak at your usual volume and pace, with natural pauses. After choosing "注册我的声音" (Register my voice), a reading window appears; wait for the 3-second countdown to finish before speaking. **If you finish early, start again from the beginning and keep going until you see "录音完成" (recording finished).** There is no need to rush or change your voice. When recording ends the app checks the recording automatically; if it does not pass, the reason is shown and you can record again. After it passes, model preparation starts automatically.

> At nine fifteen this morning, we will discuss our plans. I will organize my notes and check what needs to be done. Please write down the time and place. Once we are ready, we can begin.

The app shows this passage in Chinese; the English text above is a reference translation. You can also read another ordinary text — keep reading naturally for about 15 seconds.

## Performance requirements

- **System:** macOS 14 or later on an Apple Silicon Mac. Intel Macs are unsupported.
- **Recommended device:** MacBook Air M5 is the only baseline validated over a longer run so far (internal audio-path latency p95 ≈ 260 ms; the measurement does not include Doubao recognition time). One tested M1 MacBook Pro did not meet the real-time threshold and cannot run live filtering.
- **Other devices:** The M5 result does not extend to other models. Every device must pass the built-in performance check during voice registration. Use AC power where possible.
- **Storage:** Reserve at least 3 GB. The installed app is about 1 GB; voice registration generates an additional personal model.

## Key limitations

- Filtering reduces interference but **cannot guarantee complete isolation of nearby speech**. When you are not speaking, others' voices may still get transcribed.
- **Pause ≠ microphone off.** While paused, raw audio — including nearby speech and background noise — keeps reaching the input method. Choose "结束" (End) to release the microphone. Quitting the interface also keeps background audio running.
- MicForYou filters and enrolls locally and stores data on your Mac. Doubao's speech recognition follows its own policies; local processing does not make the whole dictation flow offline.

See the [usage guide](docs/USAGE.en.md) for more limitations and troubleshooting.

## License

Original project code and documentation use [Apache-2.0](LICENSE); attribution is in [NOTICE](NOTICE). Models and third-party components retain their own licenses — see [licenses/](licenses/).
