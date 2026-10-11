# MicForYou technical reference

[简体中文](TECHNICAL_GUIDE.md) · [User guide](../README.en.md)

This document covers the current 0.2.1 test build: performance evidence, audio behavior, local data, source installation and distribution details. Start with the user guide for everyday setup.

## Hardware and performance requirements

**Use the validated MacBook Air M5 as the current recommended baseline. The tested M1 did not meet this model's real-time requirements and is not recommended for filtering.** Other devices must pass local performance checks, even with newer chips or higher specifications. A chip name alone does not guarantee acceptable latency.

| Requirement / device | Current requirements and results |
| --- | --- |
| OS and architecture | The menu-bar UI requires **macOS 14+**. The complete bundle supports **Apple Silicon (arm64)** only; Intel is unsupported. |
| MacBook Air M5 | Previously passed a [30-minute run](MAC_A_NEXT_STAGE.md), with internal bridge audio latency p95 around **260 ms**. This is the validated baseline; workload and power conditions still affect results. |
| MacBook Pro M1 (tested device) | The current REAL-TSE checkpoint's best valid RTF was **1.052**: processing was slower than real time and could not keep up with continuous audio input. Real-time filtering is currently unsupported on this tested device. |
| Other Macs | Insufficient validation, including other generations and Pro / Max / Ultra variants. Devices with comparable or greater sustained processing capacity are candidates, but must still pass performance checks. |
| Disk and memory | The unpacked app is about 1 GB. Reserve at least 3 GB for registration models and reports. Minimum RAM has not been established through independent device tests. |

The complete app automatically checks local performance during voice registration. Recommended candidates need **RTF ≤ 0.80** (processing time / audio duration, leaving at least 20% throughput headroom), **internal bridge latency p95 < 400 ms** in paced verification, and no FAULT or audio underruns. Use AC power and verify under your usual workload: heavy background work can turn a passing configuration into a failing one. Source users can run [installation step 5](INSTALL.en.md) manually. See the [performance guide](PERFORMANCE_GUIDE.md) and [M1 test results](MAC_B_COREML_THREAD_RECHECK_RESULTS_20260918.md).

**These latency figures measure MicForYou's audio path, excluding Doubao recognition and text display. They are not a promise of end-to-end dictation latency.** The earlier M5 validation is also not a hardware acceptance test for the new pause behavior.

## Download and installation

**The complete 0.2.1 installer has been built**, including the app, arm64 Python, inference dependencies, general REAL-TSE checkpoint and authorized official BlackHole 2ch. No developer tools or separate model/driver downloads are needed. It remains a Draft acceptance build in a private repository. Clean-device testing, final native distribution review and Developer ID/notarization are pending.

Read the [installation guide](BUNDLED_APP.en.md). Maintainers with access can download the `.pkg` and `.sha256` from `v0.2.1-local-alpha` Draft Assets in [GitHub Releases](https://github.com/chenerzhong123-cloud/micforyou/releases); public users can follow the same process after publication. Verify the checksum, end audio and quit the old app, then double-click to install into `/Applications`. Restart when prompted after driver installation. Register your voice; after export, validation and performance checks pass, select `BlackHole 2ch` in Doubao. Personal data is preserved.

The repository is currently private, so access requires permission. No public complete release asset is available. GitHub's `Source code (zip)` is source, not an app installer. Developers can still use the [source installation guide](INSTALL.en.md).

The model's licenses are scoped: Ke Zhang's own portions are authorized under Apache-2.0; WeSpeaker ECAPA parameters retain upstream CC BY 4.0 attribution. See [model notices](../licenses/MODEL_NOTICES.md) and the [licensing review](MODEL_DISTRIBUTION_AUDIT.md).

## Everyday use

After setup, open the MicForYou menu, choose “开始过滤” (Start filtering), wait for “正在过滤” (Filtering), then dictate using Doubao. The app interface currently uses Chinese labels.

| Action | Audio sent to the IME | Microphone |
| --- | --- | --- |
| Start filtering | Processed audio; silence until loading completes | In use |
| Pause filtering | **Raw audio continues, including your voice, nearby people, and surroundings** | Still in use |
| Resume filtering | Fresh streaming state restores filtering without reopening devices | Still in use |
| End | No audio from this route | Released |
| Quit interface | Background audio continues in its current mode | Still in use while running or paused |

Pause stops filtering, not capture. Choose “结束” (End) to release the microphone before quitting, changing microphones, or enrolling again. Pause/resume does not require reselecting Doubao's input device.

Terminal users can run these commands from the project directory:

```bash
uv run micforyou status
uv run micforyou start
uv run micforyou pause   # raw audio continues; microphone stays open
uv run micforyou resume  # restore filtering
uv run micforyou stop    # end and release the microphone
```

MicForYou never changes the system's default input automatically. If Doubao lacks its own input selector, manually choose BlackHole in **System Settings → Sound → Input**, and restore your physical microphone afterward if needed. Keep the system output on your usual speakers/headphones.

## Support and limitations

- Filtering reduces some other speech but **cannot guarantee isolation**. Other people may still be transcribed while you are silent. This is not an identity-verification or privacy-isolation tool.
- Raw passthrough on pause has automated and real-ONNX/synthetic-input checks. Physical-device transitions, Doubao experience, and a new 30-minute stability test remain pending. See the [validation record](PAUSE_PASSTHROUGH_VALIDATION.md).
- Source control excludes weights and personal audio. Complete app bundles include the general checkpoint under scoped Apache-2.0 / CC BY 4.0 terms; see the [licensing review](MODEL_DISTRIBUTION_AUDIT.md).

## Local data and faults

MicForYou processes and enrolls audio locally. It does not perform ASR or type text. Doubao's recognition and data handling follow its own policies; local preprocessing does not make the complete dictation flow offline.

The default runtime-fault policy is silence. An explicit pause enables raw passthrough, with a different visible state. A fault is never silently treated as a user pause. If the selected microphone disappears, the app does not automatically choose another microphone.

Configuration and runtime metadata live in `~/Library/Application Support/MicForYou/`; new reports use its `work/runs/` directory. Logs contain no audio, embeddings, or IME text. App enrollment audio and personal models are stored under `~/Library/Application Support/MicForYou/registrations/`. Source installations may use directories specified in their own configuration. Do not commit personal data to GitHub.

## Update, troubleshoot, and uninstall

Complete-bundle updates: choose End and quit the interface, download and run the new complete `.pkg`, then reopen `/Applications/MicForYou.app`. Voice data and settings in Application Support are preserved. Confirm readiness before starting filtering again.
Upgrading from the 0.1.1 controller requires one new registration; settings are replaced only after it passes.

Source-install users can update with the following commands. These build the controller shell, not the complete runtime bundle:

```bash
git pull --ff-only
uv sync --extra dev
./app/MicForYouMenuBar/install_app.sh
```

This preserves configuration, models, and enrollment. Older versions released capture on pause. Upgrading does not automatically reopen the microphone; explicitly start filtering again. Do not replace runtime files while raw output is active.

- Setup incomplete: check the driver, microphone and registration progress in Settings. Source users can also run `uv run micforyou status`.
- No text: check readiness, Doubao's `BlackHole 2ch` selection, and macOS microphone permission for the process actually capturing audio.
- Microphone still active: pause and quitting the interface preserve audio. Choose End or run `uv run micforyou stop`.
- Uninstall: end audio, quit, move `/Applications/MicForYou.app` (and any old ZIP copy in `~/Applications`) to Trash, and restore Doubao's input. Configuration, enrollment, and BlackHole are separate resources; back up or remove them as needed.

[Complete-bundle installation](BUNDLED_APP.en.md) · [Source installation](INSTALL.en.md) · [Menu-bar guide](MENU_BAR_APP.md) · [Performance checks](PERFORMANCE_GUIDE.md) · [Development history](DEVELOPMENT_HISTORY.md) · [Video source](../video/README.md)

## Project license and third-party terms

Original project code and documentation use [Apache-2.0](../LICENSE), with attribution in [NOTICE](../NOTICE). The project license does not replace licenses for models, runtime libraries or the official driver. See [model notices](../licenses/MODEL_NOTICES.md), [BlackHole notices](../licenses/BLACKHOLE_NOTICES.md) and [native library notices](../licenses/NATIVE_NOTICES.md).

The existing 0.2.1 installer was built on October 9. LICENSE and NOTICE are supplied as additional Draft Release assets with this documentation update; the package itself has not been rebuilt. Future complete builds include both notices inside the App and display the project license in the installer.
