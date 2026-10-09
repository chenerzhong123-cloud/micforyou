"""Exercise a complete bundle's real setup pipeline with an existing local WAV.

Only device discovery and recording are substituted. No audio devices are
opened; this does not validate microphone permission, UI or an input method.
Use an ignored, private work directory. Never package its outputs.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--enrollment", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--mode", choices=["setup-worker"], required=True)
    args = parser.parse_args()
    root = args.app.resolve() / "Contents/Resources/Runtime"
    config = args.work.resolve() / "config.json"
    if config.exists():
        raise SystemExit("Use a new work directory; never replace an existing registration")
    if Path(sys.executable).resolve() != (root / "python/bin/python3.12").resolve():
        raise SystemExit("Run this check with the selected App's Python")
    os.environ["MICFORYOU_BUNDLE_ROOT"] = str(root)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root / "src"))
    from micforyou import setup
    from micforyou.audio import Device
    from micforyou.product import load_config
    devices = [Device(0, "Offline fixture", 0, 1, 0, 48000),
               Device(1, "BlackHole 2ch", 0, 2, 2, 48000)]
    setup.list_devices = lambda: devices
    setup.record_input = lambda device, destination, *a: shutil.copy2(args.enrollment, destination)
    setup.save_job(config, {"status": "RUNNING", "stage": "Offline validation",
                          "progress": 0, "pid": os.getpid(), "token": args.token})
    setup.run_worker(config, "Offline fixture", args.token)
    job = setup.read_job(config)
    assert job["status"] == "READY", job
    result = load_config(config)
    assert result.bundle_managed and result.onnx_model.is_file()
    assert result.project_root == root
    print(json.dumps({"offline_setup": "PASS", "frames_per_chunk": result.frames_per_chunk,
                      "prefill_ms": result.prefill_ms, "recording_substituted": True}))


if __name__ == "__main__":
    main()
