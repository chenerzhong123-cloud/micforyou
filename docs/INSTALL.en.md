# Install MicForYou from GitHub

> For the complete local 0.2.0 alpha, use [the bundled-app guide](BUNDLED_APP.en.md). This page covers the developer/source installation path.
English · [简体中文](INSTALL.md) · [Back to README](../README.en.md)

This release requires Terminal and local model setup. It is intended for users familiar with Python/Git. All paths below belong to your own machine. The menu-bar UI requires macOS 14+; the model has been tested on M5 and fails the measured real-time gate on M1. Neither the source nor the app shell includes weights.

## 1. Tools and source

Install Apple Command Line Tools if needed:

```bash
xcode-select --install
```

Install uv using its [official instructions](https://docs.astral.sh/uv/getting-started/installation/). If you already use Homebrew:

```bash
brew install uv
```

With repository access, clone and prepare the controller:

```bash
git clone https://github.com/chenerzhong123-cloud/micforyou.git
cd micforyou
uv sync --extra dev
```

Run the remaining commands from this project directory. GitHub's source ZIP is also usable; for updates, download fresh source and point the configuration to the retained project directory. Keep the configured source location and its `.venv` after installing the app.

## 2. Audio routing

Install **BlackHole 2ch** from the [official site](https://existential.audio/blackhole/) or its [Homebrew cask](https://formulae.brew.sh/cask/blackhole-2ch):

```bash
brew install --cask blackhole-2ch
```

Restart your Mac, run `uv run micforyou devices`, and confirm that BlackHole 2ch and your everyday physical microphone appear. MicForYou outputs to BlackHole; select it as Doubao's input. Keep your system output on your usual speakers/headphones.

## 3. Separate model environment

Define local paths. If you reopen Terminal, reset these variables from the project directory:

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

Keep the controller and model environments separate. Do not install upstream's old `requirements.txt` directly into the project `.venv`. Our runtime requirements pin model dependencies; installation needs network access. Upstream dependencies may include other models; MicForYou does not invoke ASR.

Obtain the checkpoint yourself from the [upstream pretrained-model instructions](https://github.com/REAL-TSE/wesep-real-tse#2-download-pretrained-model) and follow their usage conditions. Use **`tfmap_context_causal_100`**, not its noncausal variant. Check these files:

```bash
test -f "$MFY_MODEL/avg_model.pt"
test -f "$MFY_MODEL/config.yaml"
```

The 2026-10-09 author reply grants Apache-2.0 for his own code and trained parameters, excluding WeSpeaker pretrained ECAPA parameters. The latter retain upstream CC BY 4.0 attribution. Complete app bundles can include the general checkpoint under these scoped terms; see the [licensing review](MODEL_DISTRIBUTION_AUDIT.md) and [notices](../licenses/MODEL_NOTICES.md).

## 4. Enroll, export, and validate

Find your everyday microphone's exact name, set the variable accordingly, and record 45 seconds of your own voice:

```bash
uv run micforyou devices
MFY_MIC="YOUR EVERYDAY PHYSICAL MICROPHONE"
uv run micforyou record --input-device "$MFY_MIC" \
  --output-file "$MFY_VOICE" --duration 45 --countdown 3
```

Use a quiet environment and natural speech. Training is not required. Grant macOS microphone permission to the process actually recording. Enroll with the same microphone you will use daily, and use only your own voice. Audio is written to the selected local path.

```bash
"$MFY_RUNTIME/bin/python" experiments/export_real_tse_onnx.py \
  --repo "$MFY_REPO" --model-dir "$MFY_MODEL" \
  --enrollment "$MFY_VOICE" --enrollment-seconds 6 \
  --output "$MFY_ONNX" --report "$MFY_DATA/reports/onnx-export.json"

"$MFY_RUNTIME/bin/python" experiments/compare_torch_onnx.py \
  --repo "$MFY_REPO" --model-dir "$MFY_MODEL" \
  --enrollment "$MFY_VOICE" --enrollment-seconds 6 \
  --onnx "$MFY_ONNX" --frames-per-chunk 8 --chunks 100 \
  --result "$MFY_DATA/reports/onnx-correctness.json"
```

The last report must have `gate.verdict: PASS`. Do not start live filtering if it fails.

## 5. Benchmark and configure

Benchmark the ONNX path using synthetic input, without opening a microphone:

```bash
"$MFY_RUNTIME/bin/python" experiments/benchmark_onnx_tse.py \
  --repo "$MFY_REPO" --model-dir "$MFY_MODEL" \
  --enrollment "$MFY_VOICE" --onnx "$MFY_ONNX" \
  --audio-seconds 60 --frames 8 16 24 32 --threads 1 \
  --result "$MFY_DATA/reports/benchmark.json"
```

The report’s `gate` should be CPU SUCCESS (a valid candidate with RTF ≤0.80); MARGINAL/FAIL is not a recommended configuration. Apply the [performance guide](PERFORMANCE_GUIDE.md) and verify paced latency with `measure_bridge_latency.py`. Do not force a run after an unsupported result, FAULT, sustained underrun, or excessive latency. `MFY_FRAMES=8` below is only an example from the tested M5. Use the candidate that actually passes on your machine; repeat correctness and paced checks at that frame size for other candidates.

```bash
MFY_FRAMES=8
uv run micforyou configure \
  --input-device "$MFY_MIC" --output-device "BlackHole 2ch" \
  --model-repo "$MFY_REPO" --model-dir "$MFY_MODEL" \
  --enrollment "$MFY_VOICE" --onnx "$MFY_ONNX" \
  --runtime-python "$MFY_RUNTIME/bin/python" --project-root "$MFY_ROOT" \
  --frames-per-chunk "$MFY_FRAMES" --onnx-threads 1 --fault-policy silence
uv run micforyou status
```

`ready: true` means required paths and devices exist. It does not establish performance or filtering quality. Check local performance before first use and when system load changes.

## 6. Install the app and select input

```bash
./app/MicForYouMenuBar/install_app.sh
```

This builds and installs `~/Applications/MicForYou.app`, preserves configuration/models, and adds no login item. Building requires Swift 6+; update Apple developer tools if `swift --version` is older. The current UI uses Chinese labels.

For a future prebuilt `.app.zip`, extract and place the `.app` in `~/Applications`; still complete steps 1–5 first. A prebuilt shell does not create Python environments or enroll your voice. Current builds are ad-hoc signed and not notarized; follow [Apple's Open Anyway instructions](https://support.apple.com/en-us/102445) if first launch is blocked.

Select `BlackHole 2ch` in Doubao. If it lacks its own device selector, choose it manually in system sound input. Click “开始过滤” (Start filtering), wait for “正在过滤” (Filtering), and dictate. Check a short phrase while filtering, during raw passthrough on pause, and after resuming. Click “结束” (End) when you want capture to stop.

## Update and recover

End audio and quit the interface. Git-clone users run `git pull --ff-only`, `uv sync --extra dev`, and `install_app.sh` again. If model dependencies change, also run `uv pip install --python "$MFY_RUNTIME/bin/python" -r requirements-runtime.txt` using your saved runtime path. Re-enrollment and input reselection are usually unnecessary; changing the physical microphone requires new enrollment and a short baseline test.

For rollback, stop audio before reverting source/App. Older controllers cannot read runtime-state/2 directly. Back up configuration, then move aside the stopped `state.json` so the old version can recreate its state. Do not overwrite or delete enrollment to fix runtime metadata.

See [README](../README.en.md) for troubleshooting and uninstalling.

First model loading may include upstream JIT compilation and take longer than later starts. Wait for the actual ready/filtering state before dictating.
