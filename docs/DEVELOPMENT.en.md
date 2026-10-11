# Development Guide

[简体中文](DEVELOPMENT.md) · [Back to README](../README.en.md)

This guide is for building MicForYou from source: environment and model preparation, inference tooling, tests, the Swift menu-bar app, and building/verifying the complete installer. For daily use see the [usage guide](USAGE.en.md).

## Architecture overview

MicForYou consists of three layers, mirrored by the repository layout:

```text
src/micforyou/            # Python controller: config, devices, process lifecycle, CLI, first-run setup
tools/inference/          # Live inference scripts: bridge, streaming core, ONNX export/compare/benchmark/latency
app/MicForYouMenuBar/     # SwiftUI menu-bar shell: drives the controller CLI, contains no model logic
tools/verification/       # Synthetic-input integration checks (never opens a real microphone)
tools/bundle/             # Complete-bundle build, native dependency prep, installer and read-only verification
tools/installer/          # pkg installer resources and preflight scripts
tests/                    # Controller and product-contract regression tests
licenses/                 # Third-party license notices and full texts
```

Audio route: physical microphone → MicForYou live filtering (48 kHz capture, 16 kHz model, 48 kHz output) → BlackHole 2ch virtual device → Doubao IME. MicForYou implements no speech recognition, produces no text, and never changes the system default input. Runtime faults default to silence (privacy-first); an explicit pause is raw passthrough. `tools/inference/run_real_tse_bridge.py` is the background audio process; `src/micforyou/product.py` locates it via the configured `project_root` — the script directory is fixed at `tools/inference/`, identical in the repository and inside the packaged app.

## 1. Tools and source

Install Apple Command Line Tools (skip if present) and [uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
xcode-select --install
brew install uv   # or follow the official uv instructions
```

Clone and install the controller environment:

```bash
git clone https://github.com/chenerzhong123-cloud/micforyou.git
cd micforyou
uv sync --extra dev
```

All following steps run from the project directory. Reset the `MFY_*` variables below when reopening a terminal; do not delete the project `.venv` or move the source directory referenced by your configuration.

## 2. Audio routing

Install BlackHole **2ch** ([official site](https://existential.audio/blackhole/) or the [Homebrew cask](https://formulae.brew.sh/cask/blackhole-2ch)):

```bash
brew install --cask blackhole-2ch
```

Restart your Mac afterwards, then run `uv run micforyou devices` and confirm both `BlackHole 2ch` and your everyday microphone appear.

## 3. Separate model environment

Keep the controller and model environments separate; model dependencies are pinned in `requirements-runtime.txt` at the repository root:

```bash
MFY_ROOT="$PWD"
MFY_DATA="$HOME/Library/Application Support/MicForYou/data"
MFY_REPO="$MFY_DATA/wesep-real-tse"
MFY_MODEL="$MFY_REPO/pretrained/tfmap_context_causal_100"
MFY_RUNTIME="$MFY_DATA/runtime"
MFY_VOICE="$MFY_DATA/voice/enrollment.wav"
MFY_ONNX="$MFY_DATA/voice/personalized.onnx"
mkdir -p "$MFY_DATA/voice" "$MFY_DATA/reports"
git clone https://github.com/REAL-TSE/wesep-real-tse.git "$MFY_REPO"
git -C "$MFY_REPO" checkout 2a540977a348fbaa92e623210505430e2cec608d
uv venv --python 3.12 "$MFY_RUNTIME"
uv pip install --python "$MFY_RUNTIME/bin/python" -r requirements-runtime.txt
```

Never install the upstream legacy `requirements.txt` into the project `.venv`. Installation needs network access; the Python packages may pull in other upstream model dependencies that MicForYou does not use — MicForYou performs no ASR.

Download the weights yourself from the [pretrained-model section of the upstream README](https://github.com/REAL-TSE/wesep-real-tse#2-download-pretrained-model) under their terms of use. Choose **`tfmap_context_causal_100`** (the causal version — not the non-causal one) and verify:

```bash
test -f "$MFY_MODEL/avg_model.pt"
test -f "$MFY_MODEL/config.yaml"
```

The model licensing is split: the REAL-TSE author-owned source and trained parameters are Apache-2.0; the upstream WeSpeaker ECAPA pretrained parameters are CC BY 4.0. Full statement in [../licenses/MODEL_NOTICES.md](../licenses/MODEL_NOTICES.md). The repository never commits weights or personal recordings.

## 4. Enrollment, export, and correctness

Find the exact name of your everyday microphone and record 45 seconds of your own voice (quiet room, natural pace, everyday microphone; never someone else's voice):

```bash
uv run micforyou devices
MFY_MIC="your-everyday-microphone-name"
uv run micforyou record --input-device "$MFY_MIC" \
  --output-file "$MFY_VOICE" --duration 45 --countdown 3
```

Allow microphone access when macOS asks. Then export your personal ONNX and verify numerical consistency:

```bash
"$MFY_RUNTIME/bin/python" tools/inference/export_real_tse_onnx.py \
  --repo "$MFY_REPO" --model-dir "$MFY_MODEL" \
  --enrollment "$MFY_VOICE" --enrollment-seconds 6 \
  --output "$MFY_ONNX" --report "$MFY_DATA/reports/onnx-export.json"

"$MFY_RUNTIME/bin/python" tools/inference/compare_torch_onnx.py \
  --repo "$MFY_REPO" --model-dir "$MFY_MODEL" \
  --enrollment "$MFY_VOICE" --enrollment-seconds 6 \
  --onnx "$MFY_ONNX" --frames-per-chunk 8 --chunks 100 \
  --result "$MFY_DATA/reports/onnx-correctness.json"
```

The correctness report's `gate.verdict` must be `PASS`; do not start live filtering after a failure.

## 5. Performance checks and configuration

Run the full-path ONNX benchmark (synthetic input; a real microphone is never opened):

```bash
"$MFY_RUNTIME/bin/python" tools/inference/benchmark_onnx_tse.py \
  --repo "$MFY_REPO" --model-dir "$MFY_MODEL" \
  --enrollment "$MFY_VOICE" --onnx "$MFY_ONNX" \
  --audio-seconds 60 --frames 8 16 24 32 --threads 1 \
  --result "$MFY_DATA/reports/benchmark.json"
```

`gate` should report SUCCESS (eligible candidates RTF ≤ 0.80); MARGINAL/FAIL is not a recommended configuration. You can recompute a recommendation from an existing benchmark JSON with `uv run micforyou recommend-frames --benchmark .../benchmark.json`.

**Pick the frame candidate first, then re-check and configure.** Select a passing candidate from the benchmark report (the example `MFY_FRAMES=8` comes from a validated machine and is not a universal threshold); the subsequent correctness check, latency re-check, and configure must all use that same frame count. Redo correctness for it as well (see section 4).

Re-check pacing with the latency tool (the benchmark cannot replace it). Note that `--backend` defaults to `torch`; pass `onnx` explicitly so you measure the path configure will actually run, and keep `--prefill-ms` consistent with configure (default 100 ms):

```bash
MFY_FRAMES=8   # replace with the candidate that actually passed the benchmark on this Mac
"$MFY_RUNTIME/bin/python" tools/inference/measure_bridge_latency.py \
  --repo "$MFY_REPO" --model-dir "$MFY_MODEL" --enrollment "$MFY_VOICE" \
  --backend onnx --onnx "$MFY_ONNX" --onnx-threads 1 \
  --frames-per-chunk "$MFY_FRAMES" --prefill-ms 100 --duration 30 \
  --result "$MFY_DATA/reports/latency.json"
```

Read the verdict from the `bridge_internal` section of the result JSON (the terminal summary is abbreviated): a candidate with `bridge_internal.bridge_latency.latency_ms_p95` ≥ 400 ms, `bridge_internal.status` FAULT, `length_match` not true, `nonfinite_samples` non-zero, or sustained underruns (`bridge_internal.underrun_ms`) is unusable. These metrics cover only MicForYou's internal audio path — not CoreAudio, the BlackHole transfer, or Doubao recognition time.

Finally write the configuration and confirm readiness (same frame count as re-checked above):

```bash
uv run micforyou configure \
  --input-device "$MFY_MIC" --output-device "BlackHole 2ch" \
  --model-repo "$MFY_REPO" --model-dir "$MFY_MODEL" \
  --enrollment "$MFY_VOICE" --onnx "$MFY_ONNX" \
  --runtime-python "$MFY_RUNTIME/bin/python" --project-root "$MFY_ROOT" \
  --frames-per-chunk "$MFY_FRAMES" --onnx-threads 1 --fault-policy silence
uv run micforyou status
```

`ready: true` only means paths and devices are present; it is not a performance or quality verdict.

## 6. Build the menu-bar app

Requires a Swift 6+ toolchain (update Apple's developer tools if `swift --version` is below 6):

```bash
swift build -c release --package-path app/MicForYouMenuBar
./app/MicForYouMenuBar/install_app.sh   # builds and installs to ~/Applications/MicForYou.app
```

The app reads `~/Library/Application Support/MicForYou/config.json` and uses the runtime recorded there; it downloads no models and never changes the system default input.

## 7. Tests and verification

```bash
# Python controller and product-contract regression tests
PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest -q

# Standalone model-related self-check (no Xcode project needed)
cd app/MicForYouMenuBar
swiftc Sources/MicForYouMenuBar/Models.swift Checks/ModelCheck.swift -o .build/model-check
.build/model-check
cd ../..

# Pause-passthrough synthetic-input integration check (real ONNX model +
# synthetic duplex callbacks; no real microphone, no IME; reports go to
# outputs/, which is not tracked by Git)
uv run python tools/verification/verify_pause_passthrough.py --config "$HOME/Library/Application Support/MicForYou/config.json"
```

The first model load may include upstream JIT compilation and take longer than later starts; wait for an actually-ready state before dictating.

## 8. Build the complete installer

Complete bundles are built into fresh output directories with pinned source revisions and checkpoint hashes verified at build time. The current native dependency sources and metadata pin CPython 3.12.13; the build Python must be that exact version:

```bash
# Install into a dedicated directory, then let uv locate the actual
# interpreter (the install-dir is only a container directory, not the install
# itself, and cannot be used as PYTHON_ROOT directly)
uv python install 3.12.13 --install-dir outputs/bundle-build/python
PYTHON_BIN=$(UV_PYTHON_INSTALL_DIR="$PWD/outputs/bundle-build/python" \
  uv python find --managed-python --no-project --resolve-links 3.12.13)
PYTHON_ROOT="$(dirname "$(dirname "$PYTHON_BIN")")"   # up two levels from the interpreter = the install root
test -x "$PYTHON_ROOT/bin/python3.12"   # confirm the resolved root works
```

All following build steps use this same resolved `PYTHON_ROOT`. Initialize it with requirements-bundle.lock (use `--break-system-packages` only for this dedicated build Python; never modify the system Python) and prepare the native dependencies:

```bash
uv pip install --break-system-packages --python "$PYTHON_ROOT/bin/python3.12" \
  -r requirements-bundle.lock
uv pip install --target outputs/bundle-build/cmake cmake==4.4.4
"$PYTHON_ROOT/bin/python3.12" -B tools/bundle/prepare_native.py \
  --sources outputs/bundle-build/sources \
  --cmake outputs/bundle-build/cmake/cmake/data/bin/cmake \
  --output outputs/bundle-build/native
```

`<wespeaker-package-dir>` points at the WeSpeaker **package directory** installed in the model environment's site-packages (not the Git repository root), e.g. `$MFY_RUNTIME/lib/python3.12/site-packages/wespeaker`; the builder verifies the pinned revision via the adjacent `wespeaker-*.dist-info/direct_url.json`, so it must come from a model environment installed at the pinned revision per section 3.

Build the complete app ZIP:

```bash
./app/MicForYouMenuBar/package_complete.sh "$PYTHON_ROOT" "$MFY_REPO" <wespeaker-package-dir>
```

Build the all-in-one installer pkg (requires the official BlackHole installer; the builder verifies its hash and signing identity):

```bash
curl -fL https://existential.audio/downloads/BlackHole2ch-0.7.1.pkg -o BlackHole2ch-0.7.1.pkg
./app/MicForYouMenuBar/package_installer.sh "$PYTHON_ROOT" "$MFY_REPO" \
  <wespeaker-package-dir> BlackHole2ch-0.7.1.pkg <fresh-output-dir>
```

The builder combines the complete app and the official driver into a `.pkg` with a checksum, manifest, and bilingual install and usage guides (generated from `docs/INSTALL.md`/`INSTALL.en.md`/`USAGE.md`/`USAGE.en.md` with navigation and license links rewritten for the delivered layout). The output directory must be fresh. A normal venv cannot serve as `PYTHON_ROOT`; the complete bundle includes no personal voice or personalized model.

`package_release.sh` only produces the controller-shell ZIP (no Python, weights, or enrollment); its notes point to the source setup in this guide. Do not present it as a complete bundle.

## 9. Read-only installer verification

`verify_installer.py` performs read-only checks only (extraction, hash and signature verification, installer-choices query); it never runs an administrator installation:

```bash
# Build the check tools first (run from the repository root; place outputs
# outside the repository or in an ignored path)
MFY_CHECKS="$PWD/outputs/installer-build"
mkdir -p "$MFY_CHECKS"
swiftc -parse-as-library \
  app/MicForYouMenuBar/Checks/BundleCheck.swift \
  -o "$MFY_CHECKS/bundle-check"
swiftc -parse-as-library \
  app/MicForYouMenuBar/Sources/MicForYouMenuBar/CLIClient.swift \
  app/MicForYouMenuBar/Sources/MicForYouMenuBar/Models.swift \
  app/MicForYouMenuBar/Checks/StandaloneCheck.swift \
  -o "$MFY_CHECKS/standalone-check"

"$PYTHON_ROOT/bin/python3.12" -B tools/bundle/verify_installer.py \
  --pkg <path/to/MicForYou.pkg> --work <fresh-inspection-dir> \
  --checks-dir "$MFY_CHECKS"
```

Notes: `@main` sources need `-parse-as-library`, and `StandaloneCheck` depends on the controller shell's `CLIClient`/`Models` definitions, which must be compiled together. `--checks-dir` points at the `bundle-check`/`standalone-check` binaries from the previous step (default: `outputs/installer-build`). The report is written to `<work>/verification.json`; items not executed (administrator installation, restart, on-device enrollment acceptance, …) are listed under `not_run`.

## 10. Licensing and distribution notes

- Original code and documentation are Apache-2.0 ([../LICENSE](../LICENSE), [../NOTICE](../NOTICE)); third-party components retain their own terms ([../licenses/](../licenses/)). The bundle builder copies licenses and verifies model and driver hashes.
- Identified LGPL/MPL native components ship with source and licenses; a final distribution review of all actual native dependencies is still pending.
- Public distribution to regular users requires Developer ID signing and Apple notarization; current builds are ad-hoc signed.
- The repository commits no weights, personal recordings, or run reports; `outputs/`, `runs/`, and similar paths are ignored via `.gitignore`.
