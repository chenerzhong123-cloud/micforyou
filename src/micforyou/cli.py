from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from .audio import (
    BLACKHOLE_NAME,
    list_devices,
    passthrough,
    play_file,
    probe_loopback,
    record_input,
    resolve_device,
)
from .evaluation import create_mixtures, score_output
from .recommendation import BenchmarkCandidate, recommend


DEFAULT_WORK_DIR = Path("/Users/deuce/claudeproject/codexworks/micforyou")


def write_json(value: Any, destination: Path | None) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2)
    print(rendered)
    if destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered + "\n", encoding="utf-8")


def timestamped_result(name: str) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return DEFAULT_WORK_DIR / "runs" / f"{stamp}-{name}.json"


def command_devices(args: argparse.Namespace) -> None:
    write_json([item.to_dict() for item in list_devices()], args.output)


def command_prepare_audio(args: argparse.Namespace) -> None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    intermediate = args.output.with_suffix(".aiff")
    try:
        subprocess.run(
            ["say", "-v", args.voice, "-r", str(args.rate), "-o", str(intermediate), args.text],
            check=True,
        )
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
                str(intermediate), "-ar", "48000", "-ac", "1", str(args.output),
            ],
            check=True,
        )
    finally:
        intermediate.unlink(missing_ok=True)
    write_json({"audio": str(args.output.resolve()), "expected_text": args.text}, None)


def command_play(args: argparse.Namespace) -> None:
    device = resolve_device(list_devices(), args.output_device, "output")
    if BLACKHOLE_NAME.casefold() not in device.name.casefold() and not args.allow_non_blackhole:
        raise ValueError(f"refusing non-BlackHole output {device.name!r}")
    write_json(play_file(args.file, device), args.result or timestamped_result("file-play"))


def command_passthrough(args: argparse.Namespace) -> None:
    devices = list_devices()
    source = resolve_device(devices, args.input_device, "input")
    destination = resolve_device(devices, args.output_device, "output")
    write_json(
        passthrough(source, destination, args.duration, args.blocksize),
        args.result or timestamped_result("passthrough"),
    )


def command_probe_loopback(args: argparse.Namespace) -> None:
    device = resolve_device(list_devices(), args.device, "output")
    write_json(
        probe_loopback(args.file, device),
        args.result or timestamped_result("blackhole-loopback"),
    )


def command_build_mixtures(args: argparse.Namespace) -> None:
    write_json(
        create_mixtures(
            args.target,
            args.interferer,
            args.output_dir,
            args.tir_db or [0.0, -6.0, -12.0],
            args.sample_rate,
            args.seed,
        ),
        args.metadata or args.output_dir / "metadata.json",
    )


def command_score_output(args: argparse.Namespace) -> None:
    write_json(
        score_output(args.output_file, args.mixture, args.target),
        args.result,
    )


def command_record(args: argparse.Namespace) -> None:
    source = resolve_device(list_devices(), args.input_device, "input")
    print(
        f"Recording starts in {args.countdown:g}s and lasts {args.duration:g}s...",
        flush=True,
    )
    write_json(
        record_input(source, args.output_file, args.duration, args.countdown),
        args.result or args.output_file.with_suffix(".json"),
    )


def command_recommend_frames(args: argparse.Namespace) -> None:
    payload = json.loads(args.benchmark.read_text(encoding="utf-8"))
    if payload.get("schema") != "micforyou-benchmark-1":
        raise ValueError(f"{args.benchmark} is not a micforyou-benchmark-1 result")
    candidates = [
        BenchmarkCandidate(
            frames_per_chunk=item["frames_per_chunk"],
            rtf=item["processing_rtf"],
            model_call_ms_p95=item["model_call_ms_p95"] or 0.0,
            model_call_ms_p50=item["model_call_ms_p50"],
            model_call_ms_max=item["model_call_ms_max"],
            model_calls=item["model_calls"],
            input_samples=item["input_samples"],
            output_samples=item["output_samples"],
            nonfinite_samples=max(item["nonfinite_samples"], 0),
            error=item["error"],
        )
        for item in payload["candidates"]
    ]
    write_json(recommend(candidates).to_dict(), args.result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="micforyou")
    subparsers = parser.add_subparsers(dest="command", required=True)

    devices = subparsers.add_parser("devices", help="list PortAudio devices")
    devices.add_argument("--output", type=Path)
    devices.set_defaults(func=command_devices)

    prepare = subparsers.add_parser("prepare-audio", help="create a fixed Mandarin route-test WAV")
    prepare.add_argument(
        "--text", default="这是麦克风链路测试，今天是星期日，编号二零二六。"
    )
    prepare.add_argument("--voice", default="Tingting")
    prepare.add_argument("--rate", type=int, default=180)
    prepare.add_argument(
        "--output", type=Path,
        default=DEFAULT_WORK_DIR / "test-data" / "route-test.wav",
    )
    prepare.set_defaults(func=command_prepare_audio)

    play = subparsers.add_parser("play-file", help="play a WAV into BlackHole")
    play.add_argument("file", type=Path)
    play.add_argument("--output-device", default=BLACKHOLE_NAME)
    play.add_argument("--allow-non-blackhole", action="store_true", help=argparse.SUPPRESS)
    play.add_argument("--result", type=Path)
    play.set_defaults(func=command_play)

    probe = subparsers.add_parser(
        "probe-loopback", help="measure BlackHole driver loopback fidelity"
    )
    probe.add_argument("file", type=Path)
    probe.add_argument("--device", default=BLACKHOLE_NAME)
    probe.add_argument("--result", type=Path)
    probe.set_defaults(func=command_probe_loopback)

    mixtures = subparsers.add_parser("build-mixtures", help="create deterministic TSE mixtures")
    mixtures.add_argument("--target", type=Path, required=True)
    mixtures.add_argument("--interferer", type=Path, required=True)
    mixtures.add_argument("--output-dir", type=Path, required=True)
    mixtures.add_argument("--tir-db", type=float, action="append")
    mixtures.add_argument("--sample-rate", type=int, default=16_000)
    mixtures.add_argument("--seed", type=int, default=20_260_913)
    mixtures.add_argument("--metadata", type=Path)
    mixtures.set_defaults(func=command_build_mixtures)

    score = subparsers.add_parser("score-output", help="score an extracted waveform")
    score.add_argument("--output-file", type=Path, required=True)
    score.add_argument("--mixture", type=Path, required=True)
    score.add_argument("--target", type=Path)
    score.add_argument("--result", type=Path)
    score.set_defaults(func=command_score_output)

    record = subparsers.add_parser("record", help="record a local enrollment/test sample")
    record.add_argument("--input-device", required=True)
    record.add_argument("--output-file", type=Path, required=True)
    record.add_argument("--duration", type=float, required=True)
    record.add_argument("--countdown", type=float, default=3.0)
    record.add_argument("--result", type=Path)
    record.set_defaults(func=command_record)

    recommend_parser = subparsers.add_parser(
        "recommend-frames",
        help="grade a benchmark JSON into fast/balanced/conservative/unsupported",
    )
    recommend_parser.add_argument("--benchmark", type=Path, required=True)
    recommend_parser.add_argument("--result", type=Path)
    recommend_parser.set_defaults(func=command_recommend_frames)

    bridge = subparsers.add_parser("passthrough", help="bridge a physical mic to BlackHole")
    bridge.add_argument("--input-device", required=True)
    bridge.add_argument("--output-device", default=BLACKHOLE_NAME)
    bridge.add_argument("--duration", type=float, default=30.0)
    bridge.add_argument("--blocksize", type=int, default=480)
    bridge.add_argument("--result", type=Path)
    bridge.set_defaults(func=command_passthrough)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
