#!/usr/bin/env python3
"""Interactive, local-only capture kit for MicForYou device migration."""

from __future__ import annotations

import hashlib
import json
import math
import platform
from pathlib import Path
import subprocess
import sys
import time
import zipfile

import numpy as np
import sounddevice as sd
import soundfile as sf


NORMAL_TEXT = (
    "我正在测试一套只保留本人声音的麦克风工具。今天的会议改到下午三点，"
    "文档编号是二零二六。Please review the final version before Friday. "
    "这段话只用于测试，不属于注册语音。"
)
QUIET_TEXT = (
    "现在我会用比平时更轻的声音继续说话。即使旁边有人交谈，句子的开头、"
    "数字七十三和最后几个字也应该尽量保留。这里是轻声测试的结尾。"
)
RECORDINGS = (
    (
        "enrollment_b.wav",
        60,
        "注册语音：自然讲话，不要读后面的测试文本。包含停顿、数字、英文词，"
        "并加入两三句自然轻声；不要耳语。",
    ),
    ("test_normal_b.wav", 25, f"正常音量测试，请朗读：\n{NORMAL_TEXT}"),
    ("test_quiet_b.wav", 25, f"自然轻声测试，不要耳语，请朗读：\n{QUIET_TEXT}"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dbfs(value: float) -> float | None:
    return 20 * math.log10(value) if value > 0 else None


def audio_metrics(audio: np.ndarray, sample_rate: int) -> dict:
    peak = float(np.abs(audio).max()) if len(audio) else 0.0
    rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64))) if len(audio) else 0.0
    return {
        "frames": int(len(audio)),
        "duration_seconds": len(audio) / sample_rate,
        "sample_rate": sample_rate,
        "channels": 1,
        "peak": peak,
        "peak_dbfs": dbfs(peak),
        "rms": rms,
        "rms_dbfs": dbfs(rms),
        "near_clipping_fraction": float(np.mean(np.abs(audio) >= 0.999)),
        "finite": bool(np.isfinite(audio).all()),
    }


def macos_version() -> dict[str, str]:
    result = {"platform": platform.platform(), "machine": platform.machine()}
    try:
        output = subprocess.run(
            ["/usr/bin/sw_vers"], capture_output=True, text=True, check=True
        ).stdout
        for line in output.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                result[key.strip()] = value.strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    return result


def input_devices() -> list[tuple[int, dict]]:
    return [
        (index, dict(device))
        for index, device in enumerate(sd.query_devices())
        if device["max_input_channels"] > 0
    ]


def select_device(devices: list[tuple[int, dict]]) -> tuple[int, dict]:
    if not devices:
        raise RuntimeError("没有检测到输入设备。请连接耳机后重试。")
    print("\n检测到以下输入设备：")
    for index, device in devices:
        print(
            f"  [{index}] {device['name']} | "
            f"{device['max_input_channels']} ch | {device['default_samplerate']:.0f} Hz"
        )
    while True:
        raw = input("\n请输入耳机 B 麦克风前的编号：").strip()
        try:
            selected = next(item for item in devices if item[0] == int(raw))
        except (ValueError, StopIteration):
            print("编号无效，请重试。")
            continue
        index, device = selected
        name = str(device["name"])
        lowered = name.casefold()
        if "blackhole" in lowered:
            print("BlackHole 是虚拟设备，不能用于录制本人参考语音。")
            continue
        if "macbook" in lowered and "microphone" in lowered:
            confirm = input(
                "当前选择看起来是 Mac 内置麦克风，不是耳机 B。"
                "如确实要使用它，请输入 USE_BUILTIN；否则按 Enter 重选："
            ).strip()
            if confirm != "USE_BUILTIN":
                continue
        confirm = input(f"确认使用“{name}”请输入同一个编号 {index}：").strip()
        if confirm == str(index):
            return selected
        print("未确认，重新选择。")


def countdown(seconds: int = 5) -> None:
    for remaining in range(seconds, 0, -1):
        print(f"{remaining}...", flush=True)
        time.sleep(1)


def record_one(
    destination: Path, duration: int, sample_rate: int, device_index: int
) -> dict:
    countdown()
    print("开始录音。", flush=True)
    audio = sd.rec(
        round(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=device_index,
        blocking=True,
    ).reshape(-1)
    print("录音结束。", flush=True)
    metrics = audio_metrics(audio, sample_rate)
    if not metrics["finite"]:
        raise RuntimeError("录音包含非有限值，停止打包。")
    sf.write(destination, audio, sample_rate, subtype="PCM_24")
    metrics.update({"file": destination.name, "sha256": sha256(destination)})
    return metrics


def package_directory(directory: Path) -> Path:
    archive = directory.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for path in sorted(directory.iterdir()):
            target.write(path, arcname=path.name)
    return archive


def main() -> None:
    print("MicForYou 设备 B 本地录音采集")
    print("不会调用 ASR，不会上传音频，不会修改系统输入或输出。")
    devices = input_devices()
    device_index, device = select_device(devices)
    sample_rate = round(float(device["default_samplerate"]))
    sd.check_input_settings(device=device_index, channels=1, samplerate=sample_rate)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    output_dir = Path.cwd() / f"micforyou-device-b-{stamp}"
    output_dir.mkdir(parents=False)
    records = []
    for filename, duration, instructions in RECORDINGS:
        print(f"\n{'=' * 60}\n{instructions}\n计划录制 {duration} 秒。")
        input("准备好后按 Enter；随后有 5 秒倒计时。")
        metrics = record_one(output_dir / filename, duration, sample_rate, device_index)
        records.append(metrics)
        rms = metrics["rms_dbfs"]
        rms_text = f"{rms:.1f}" if rms is not None else "-inf"
        print(f"已保存 {filename}，RMS {rms_text} dBFS，peak {metrics['peak']:.3f}")
        if metrics["near_clipping_fraction"] > 0.001:
            print("警告：录音疑似削波；可以完成本次采集，但后续可能要求重录。")
        if rms is None or rms < -50:
            print("警告：录音电平很低；请确认耳机麦克风是否真的被选中。")

    manifest = {
        "format_version": 1,
        "created_local": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "privacy": "local-only capture; no ASR; no upload performed by this kit",
        "system": macos_version(),
        "selected_device": {
            "index_at_capture": device_index,
            "name": device["name"],
            "max_input_channels": device["max_input_channels"],
            "default_samplerate": device["default_samplerate"],
        },
        "recordings": records,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    archive = package_directory(output_dir)
    print("\n采集完成。")
    print(f"目录：{output_dir}")
    print(f"传输文件：{archive}")
    print("请使用 AirDrop、USB 或认可的本地同步方式传回当前电脑。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已取消。未完成的目录不会自动上传。", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"\n采集失败：{error}", file=sys.stderr)
        raise SystemExit(2) from error
