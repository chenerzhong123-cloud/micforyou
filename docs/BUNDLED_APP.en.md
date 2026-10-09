# Complete app: installation and first use

The local 0.2.0 alpha includes arm64 Python, inference dependencies and the general
REAL-TSE checkpoint. Users do not need Python, uv, Git or a separate model download.
It is not publicly released yet. GitHub Releases has no fully accepted 0.2.0
asset; the old 0.1.1 menu-bar ZIP contains only the controller.

## Devices and storage

- macOS 14+ on Apple Silicon. Intel Macs are not supported by this bundle.
- M5 MacBook Air is the previously tested baseline. The tested M1 did not pass
  the current model's real-time requirements.
- Other chips, memory configurations and workloads need local validation.
- The unpacked app is approximately 1 GB. Reserve at least 3 GB of free disk
  space for the app, personal model and reports. A minimum RAM requirement has
  not been established through independent-device testing.
- Use AC power and a normal working load. Setup requires RTF ≤ 0.80, simulated
  bridge p95 < 400 ms, and no faults or underruns. These metrics exclude IME
  decoding and do not replace a physical microphone/IME acceptance test.

## Download and setup

1. Once released, download the **complete** `.app.zip` and checksum from
   [GitHub Releases](https://github.com/chenerzhong123-cloud/micforyou/releases)
   Assets. GitHub's `Source code (zip)` is not an app installer. Verify the checksum,
   unpack, and move the app into `~/Applications` or `/Applications`.
2. The local alpha is ad-hoc signed, without Developer ID signing or notarization.
   If macOS blocks opening, follow [Apple's instructions](https://support.apple.com/en-us/102445)
   only for an app whose origin you trust.
3. Open Settings from the menu. If the audio route is missing, use the installation
   guide to install BlackHole 2ch from its official distributor, restart, then refresh.
   The driver is installed separately and is not bundled.
4. Choose your everyday microphone, select voice registration and grant microphone
   access. Read naturally for 45 seconds in a quiet room. The app exports and validates
   the model, benchmarks your Mac, and shows progress. Cancel or retry if needed;
   a failed attempt does not replace an existing registration.
5. Select `BlackHole 2ch` as Doubao's input device. Start filtering and wait for readiness.

Pause continues forwarding raw microphone audio, including nearby speech and
environmental sounds. End releases the microphone. Quitting the interface leaves
background audio running. End audio before changing registration or upgrading.

## Data and licenses

Personal recordings, models, reports and settings remain in
`~/Library/Application Support/MicForYou`. They are not uploaded.
Moving/upgrading the app rebinds bundled resources while preserving personal data.
Failed candidate registrations are cleaned up; older successful registrations
remain available for rollback and can occupy additional disk space.

Ke Zhang's own inference code and trained parameters are authorized under
Apache-2.0. Third-party WeSpeaker ECAPA parameters retain upstream CC BY 4.0
attribution. See Credits in Settings and [model notices](../licenses/MODEL_NOTICES.md).
Identified LGPL/MPL sources, licenses and replacement instructions are supplied;
see [native runtime notices](../licenses/NATIVE_NOTICES.md).

Before public release, clean-device first-use testing, a physical microphone/IME
30-minute test, final review of all actual native dependencies, and Developer
ID/notarization remain pending. No signing identity is available on the current
build machine. The local complete bundle is an acceptance-test build.
