# MicForYou

English · [简体中文](README.md)

## What is it?

https://github.com/user-attachments/assets/066f815d-fb09-4240-86b6-3538726c227a

The video above is a 55-second product demonstration (in Chinese). It is an animated illustration, not a measured before-and-after comparison.

**A shared space. Fewer voices in your sentence.**

MicForYou is a voice-filtering app for Mac. It uses your registered voice as a reference to reduce background noise and nearby speech, then sends the processed audio to Doubao IME for transcription. It is designed for open offices and shared workspaces where people are talking around you.

## Current status

**Experimental Alpha.** There is no publicly released installer yet; the [Releases page](https://github.com/chenerzhong123-cloud/micforyou/releases) will become the download entry once published. Current installers are available only to maintainers with repository access. The installer is not yet Developer ID signed or notarized by Apple.

- To install: [Installation guide](docs/INSTALL.en.md)
- Already installed — daily use and limitations: [Usage guide](docs/USAGE.en.md)
- To build from source or contribute: [Development guide](docs/DEVELOPMENT.en.md)

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
