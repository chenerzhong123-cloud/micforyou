# Installing MicForYou (complete installer)

[简体中文](INSTALL.md) · [Back to README](../README.en.md)

The complete installer (`.pkg`) bundles the menu-bar app, an arm64 Python runtime, inference dependencies, the general REAL-TSE weights, and the officially licensed BlackHole 2ch 0.7.1 driver. No Python, uv, Git, audio driver, or manual model download is required.

**Trial version 0.2.2.** [Download the installer](https://github.com/chenerzhong123-cloud/micforyou/releases/download/v0.2.2-trial/MicForYou-0.2.2-trial-macos-arm64.pkg). The installer is not Developer ID signed or notarized; the app is ad-hoc signed. If macOS blocks it, follow the installation steps below.

## Recommended hardware

- macOS 14 or later, Apple Silicon. Intel Macs are unsupported.
- MacBook Air M5 is the only baseline validated over a longer run so far. One tested M1 MacBook Pro did not meet the real-time threshold and cannot run live filtering.
- Other chips, memory configurations, and system loads must pass the built-in performance check during voice registration; a chip name alone is not sufficient.
- The installed app is about 1 GB; voice registration generates an additional personal model and reports. Reserve at least 3 GB of free disk space. The minimum memory requirement has not been determined by independent device testing.
- Use AC power and complete registration under your normal workload.

## Download and install

1. Download the `.pkg` and `.sha256` from Assets on the [trial release page](https://github.com/chenerzhong123-cloud/micforyou/releases/tag/v0.2.2-trial). Do not treat `Source code (zip)` as an installer.
   Verify integrity in your download directory with `shasum -a 256 -c <installer-file-name>.sha256`.
2. Before installing, choose "结束" (End) in the old app, cancel any running registration, and quit the app. Double-click the `.pkg` and enter your administrator password when prompted. The app installs to `/Applications/MicForYou.app` and the audio driver to `/Library/Audio/Plug-Ins/HAL`. The installer deletes no personal data and never launches the app.
3. Restart your Mac if prompted after a first-time or upgraded driver install; an equal or newer driver version is skipped automatically. If an old copy remains in `~/Applications`, launch the new version from `/Applications`.
4. The combined installer is not Developer ID signed or notarized, and the original BlackHole package's signing does not cover the combined package. If macOS blocks it, follow [Apple's instructions](https://support.apple.com/en-us/102445) and choose "Open Anyway" only for packages from a confirmed source.
5. If the audio driver is unexpectedly missing, open the new app's Settings and click "安装音频组件…" (Install audio components) to run the bundled official offline repair installer; restart, then click "刷新" (Refresh). No separate download is needed.

## First-time setup (voice registration)

1. Open MicForYou from Applications and go to Settings.
2. Select the microphone you use daily.
3. Click "注册我的声音" (Register my voice) and allow MicForYou to use the microphone when macOS asks.
4. The reading window shows a passage of about 15 seconds: read it in a quiet room at your usual volume and pace (a 3-second countdown precedes recording; if you finish early, start again from the beginning). When recording ends the app checks the recording automatically, shows the reason and lets you retry if it fails, then automatically exports your personal model, verifies numerical consistency, and benchmarks this Mac; progress is shown in the registration window.
5. Registration can be cancelled; failed attempts can be retried and never replace an existing registration. Performance gates: an eligible candidate with RTF ≤ 0.80, simulated internal audio-path latency p95 < 400 ms, and no faults or audio underruns. The check does not include Doubao recognition time. Outcomes fall into three classes: **pass** — ready to filter; **stable but slower** — the app notes that dictation may lag, and you choose "still try it" or recheck later; **unstable or too slow** — filtering stays blocked. Your voice is saved as soon as the recording and model checks pass: a performance failure never asks you to read again; close heavy apps and choose "re-check performance".
6. After registration succeeds, select **BlackHole 2ch** as the input device in Doubao IME, click "开始过滤" (Start filtering) in MicForYou, and wait for the "正在过滤" (Filtering) state before dictating.

See the [usage guide](USAGE.en.md) for the semantics and limitations of daily operations (pause, resume, end).

## Updating

1. First choose "结束" (End) and quit the old app — a running app, audio session, or registration task stops the installer's preflight check.
2. Download and install the new complete `.pkg`, then open `/Applications/MicForYou.app`.
3. Voice registrations and settings in `~/Library/Application Support/MicForYou` are preserved. After updating, confirm the app reports ready before starting to filter.
4. When upgrading from the legacy controller versions (0.1.x ZIP), register your voice once in the complete app; the configuration switches only after the new registration passes.

## Uninstalling

The preferred path is the in-app entry: open MicForYou's Settings and choose **"卸载 MicForYou…"** (Uninstall MicForYou) at the bottom. The confirmation window lists what will be deleted and kept:

- By default the app itself, configuration, registration recordings, personal models, and reports are removed; you can keep the voice data for a later reinstall.
- The shared BlackHole 2ch driver is **kept** by default (other audio software may use it); removing it requires administrator authorization and a Mac restart.
- Restore your everyday microphone as the input method's input device before uninstalling; the app is moved to the Trash, and the space is freed only after the Trash is emptied.

Uninstall first verifies targets and prepares the executor and permission to clear installation receipts, then freezes new tasks, confirms background tasks have exited, and waits for the app to quit. Canceled authorization, an unready executor, or unverifiable task shutdown leaves the app and voice data intact. The coordination lease is released even when voice data is retained; a later launch checks and recovers a crashed executor lease. Partial deletion failures are listed individually; recordings already deleted cannot be restored automatically.

Manual uninstall when the app cannot launch:

1. Choose "结束" (End) and quit the menu-bar app.
2. Move `/Applications/MicForYou.app` (and any legacy ZIP copy in `~/Applications`) to the Trash.
3. Restore your everyday microphone as the input device in Doubao IME (or system sound settings).
4. Delete user data: `~/Library/Application Support/MicForYou` (configuration, registrations, personal models, reports) and `~/Library/Preferences/com.micforyou.menubar.plist`.
5. The BlackHole driver lives at `/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver`; to remove it follow the [official uninstall instructions](https://github.com/ExistentialAudio/BlackHole/wiki/Uninstallation) and restart your Mac. That folder may contain other software's drivers — never delete the whole folder.

## Licensing

Original project code and documentation use [Apache-2.0](../LICENSE); attribution is in [NOTICE](../NOTICE). This license does not replace the terms of the model, native libraries, and the official driver:

- The model is not under a single license: the REAL-TSE author-owned source and trained parameters are Apache-2.0 licensed; the WeSpeaker ECAPA pretrained parameters retain upstream CC BY 4.0 attribution. Full statement in the [model notices](../licenses/MODEL_NOTICES.md).
- Source code and licenses of identified LGPL/MPL native components ship with the package; see the [native runtime notices](../licenses/NATIVE_NOTICES.md).
- The official BlackHole binaries are distributed under a separate integration authorization; see the [BlackHole notices](../licenses/BLACKHOLE_NOTICES.md).
