#!/usr/bin/env python3
"""Write a privacy-preserving Mac B handoff record; it never records audio."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess

import sounddevice as sd


def command_output(command: list[str]) -> str | None:
    try:
        return subprocess.run(
            command, check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def device_record(index: int, device: dict) -> dict:
    return {
        "index": index,
        "name": str(device["name"]),
        "max_input_channels": int(device["max_input_channels"]),
        "max_output_channels": int(device["max_output_channels"]),
        "default_samplerate": float(device["default_samplerate"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(f"mac-b-handoff-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"),
        help="JSON handoff path; no audio is included",
    )
    args = parser.parse_args()

    devices = [device_record(index, dict(device)) for index, device in enumerate(sd.query_devices())]
    default_input, default_output = sd.default.device
    payload = {
        "format_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "privacy": "device inventory only; this tool never opens an audio stream or saves audio",
        "system": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "macos_version": command_output(["/usr/bin/sw_vers"]),
        },
        "repository": {
            "commit": command_output(["/usr/bin/git", "rev-parse", "HEAD"]),
            "remote": command_output(["/usr/bin/git", "remote", "get-url", "origin"]),
        },
        "portaudio": {
            "default_input_index": int(default_input),
            "default_output_index": int(default_output),
            "host_apis": [dict(api) for api in sd.query_hostapis()],
            "devices": devices,
        },
        "blackhole_2ch_matches": [
            device for device in devices if "blackhole 2ch" in device["name"].casefold()
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
