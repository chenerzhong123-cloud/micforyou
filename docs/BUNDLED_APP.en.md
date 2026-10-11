# Complete app: installation and first use

The complete 0.2.1 installer contains the app, arm64 Python, inference dependencies,
the general REAL-TSE checkpoint and the authorized official BlackHole 2ch 0.7.1.
No developer tools, separate model download or separate driver download are required.
It is a private GitHub Draft Release for acceptance testing, not a public release.
The 0.1.1 ZIP is controller-only; the complete 0.2.0 ZIP does not include the driver.

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

1. Maintainers with repository access can download the `.pkg` and `.sha256` from
   `v0.2.1-local-alpha` Draft Assets in
   [GitHub Releases](https://github.com/chenerzhong123-cloud/micforyou/releases).
   Public users can use the same process after publication. `Source code (zip)` is not
   an installer. In the download directory, run
   `shasum -a 256 -c MicForYou-0.2.1-local-alpha-macos-arm64.sha256`.
2. End audio, cancel enrollment and quit the old app. Double-click the `.pkg` and
   authorize administrator installation. The app goes to `/Applications/MicForYou.app`,
   the driver to `/Library/Audio/Plug-Ins/HAL`. Personal data is preserved; the installer
   does not launch the app. Restart when prompted after a driver installation/upgrade.
   An existing same/newer driver is skipped. If an old app remains in `~/Applications`,
   launch the new version from `/Applications`.
3. The combined installer is not Developer ID signed or notarized; the app is ad-hoc
   signed. The original BlackHole package's signature/notarization does not cover the
   combined installer. If blocked, follow [Apple's instructions](https://support.apple.com/en-us/102445)
   only for a package whose origin you trust. Open the new app's Settings. If the driver
   is unexpectedly missing, the audio-component button opens the included official
   offline repair installer. Restart and refresh; no separate download is needed.
4. Choose your everyday microphone, select voice registration and grant microphone
   access. Read naturally for 45 seconds in a quiet room. The app exports and validates
   the model, benchmarks your Mac, and shows progress. Cancel or retry if needed;
   a failed attempt does not replace an existing registration.
5. Select `BlackHole 2ch` as Doubao's input device. Start filtering and wait for readiness.

Pause continues forwarding raw microphone audio, including nearby speech and
environmental sounds. End releases the microphone. Quitting the interface leaves
background audio running. System default input is not switched automatically; restore
your physical microphone manually when needed. End audio before changing registration or upgrading.

## Data and licenses

Personal recordings, models, reports and settings remain in
`~/Library/Application Support/MicForYou`. They are not uploaded.
Moving/upgrading the app rebinds bundled resources while preserving personal data.
Failed candidate registrations are cleaned up; older successful registrations
remain available for rollback and can occupy additional disk space.
Upgrading from the 0.1.1 controller requires one new registration in the complete
app. Existing audio, models and settings are preserved until that passes. The
complete app does not launch the developer runtime referenced by legacy settings.

Original project code and documentation use [Apache-2.0](../LICENSE), with attribution in [NOTICE](../NOTICE). This does not replace the third-party terms below.

Ke Zhang's own inference code and trained parameters are authorized under
Apache-2.0. Third-party WeSpeaker ECAPA parameters retain upstream CC BY 4.0
attribution. See Credits in Settings and [model notices](../licenses/MODEL_NOTICES.md).
Identified LGPL/MPL sources, licenses and replacement instructions are supplied;
see [native runtime notices](../licenses/NATIVE_NOTICES.md).
The official BlackHole binary is redistributed under separate integration authorization;
its source and binary terms differ. See [BlackHole notices](../licenses/BLACKHOLE_NOTICES.md).

Before public release, clean-device first-use testing, a physical microphone/IME
30-minute test, final review of all actual native dependencies, and Developer
ID/notarization remain pending. No signing identity is available on the current
build machine. The local complete bundle is an acceptance-test build.
