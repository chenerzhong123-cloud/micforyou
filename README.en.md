# MicForYou

English · [简体中文](README.md)

## What is it?

https://github.com/user-attachments/assets/066f815d-fb09-4240-86b6-3538726c227a

[Watch / download the video (55 seconds, in Chinese)](docs/media/micforyou-promo-v5.mp4). This is an animated product demonstration, not a measured before-and-after comparison.

**A shared space. Fewer voices in your sentence.**

MicForYou is a voice-filtering app for Mac. It uses your registered voice as a reference to reduce background noise and nearby speech, then sends the audio to Doubao IME for transcription. It is designed for open offices and shared workspaces where people are talking around you.

## How to install

This is a test version. Downloads currently require access to the private repository.

1. Download the `.pkg` installer (about 443 MB) from the [download page](https://github.com/chenerzhong123-cloud/micforyou/releases). The app, model and audio components are included. No developer tools are needed.
2. Double-click to install and enter your administrator password when prompted. Restart your Mac if requested. Before upgrading, choose “结束” (End) and quit the old app.
3. Open MicForYou from Applications. In Settings, select your microphone, allow recording, and read naturally for 45 seconds in a quiet room to register your voice. Wait for preparation and performance checks to finish.
4. Select **BlackHole 2ch** as Doubao's input device. Choose “开始过滤” (Start filtering) in MicForYou and wait until it is ready before dictating.

The test installer is not yet Apple Developer ID signed or notarized. If macOS blocks it, see the [detailed installation guide](docs/BUNDLED_APP.en.md). The app interface currently uses Chinese labels.

## Performance requirements

- **System:** macOS 14 or later on an Apple Silicon Mac. Intel Macs are unsupported.
- **Recommended device:** MacBook Air M5, the currently validated baseline. The tested M1 did not meet real-time requirements and is not recommended.
- **Other devices:** Must pass the app's performance check. A chip name alone cannot guarantee suitable performance. Use AC power where possible.
- **Storage:** Reserve at least 3 GB. The installed app is about 1 GB; voice registration generates an additional personal model.

## Additional notes

- **Pause keeps the microphone open:** Raw audio continues to the input method. Choose “结束” (End) to release the microphone. Quitting the interface also leaves background audio running.
- **Data and results:** MicForYou processes audio and stores voice registration locally. Doubao's recognition follows its own policies. Filtering reduces interference but cannot guarantee complete isolation of nearby speech.
- **License:** Original project code and documentation use [Apache-2.0](LICENSE). Models and third-party components retain their own licenses.

See the [technical reference](docs/TECHNICAL_GUIDE.en.md) for performance evidence, updates, removal, troubleshooting and development details.
