from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
import json
from pathlib import Path
import queue
import subprocess
import sys
import time
from typing import Any, Iterable

import numpy as np
from scipy.signal import correlate, correlation_lags, resample_poly
import sounddevice as sd
import soundfile as sf


BLACKHOLE_NAME = "BlackHole 2ch"


@dataclass(frozen=True)
class Device:
    index: int
    name: str
    hostapi: int
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float

    @classmethod
    def from_sounddevice(cls, index: int, value: dict[str, Any]) -> "Device":
        return cls(
            index=index,
            name=str(value["name"]),
            hostapi=int(value["hostapi"]),
            max_input_channels=int(value["max_input_channels"]),
            max_output_channels=int(value["max_output_channels"]),
            default_samplerate=float(value["default_samplerate"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_devices() -> list[Device]:
    return [Device.from_sounddevice(i, dict(item)) for i, item in enumerate(sd.query_devices())]


def list_devices_fresh(timeout_seconds: float = 2.0) -> list[Device]:
    """Return CoreAudio devices from a short-lived process.

    During a hot unplug, PortAudio can keep the current process's device
    inventory alive even after its input stream has failed.  A child process
    gets a new CoreAudio inventory and is used only to decide whether the
    explicitly configured route may be reopened.  It never selects a fallback
    device or carries audio.
    """
    if timeout_seconds <= 0:
        raise ValueError("fresh device-query timeout must be positive")
    probe = (
        "import json, sounddevice as sd; "
        "print(json.dumps([dict(item) for item in sd.query_devices()]))"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            check=True,
            text=True,
            timeout=timeout_seconds,
        )
        raw_devices = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise RuntimeError(f"fresh CoreAudio device query failed: {error}") from error
    if not isinstance(raw_devices, list):
        raise RuntimeError("fresh CoreAudio device query returned invalid data")
    return [Device.from_sounddevice(i, dict(item)) for i, item in enumerate(raw_devices)]


def resolve_device(
    devices: Iterable[Device], selector: str, direction: str
) -> Device:
    if direction not in {"input", "output"}:
        raise ValueError(f"invalid direction: {direction}")
    items = list(devices)
    channel_attr = f"max_{direction}_channels"

    if selector.isdecimal():
        matches = [item for item in items if item.index == int(selector)]
    else:
        exact = [item for item in items if item.name.casefold() == selector.casefold()]
        matches = exact or [
            item for item in items if selector.casefold() in item.name.casefold()
        ]
    matches = [item for item in matches if getattr(item, channel_attr) > 0]
    if not matches:
        raise ValueError(f"no {direction} device matches {selector!r}")
    if len(matches) > 1:
        rendered = ", ".join(f"{item.index}:{item.name}" for item in matches)
        raise ValueError(f"ambiguous {direction} device {selector!r}: {rendered}")
    return matches[0]


def ensure_safe_route(input_device: Device, output_device: Device) -> None:
    if input_device.index == output_device.index:
        raise ValueError("input and output are the same device; refusing an audio loop")
    if BLACKHOLE_NAME.casefold() in input_device.name.casefold():
        raise ValueError("BlackHole cannot be the physical input; refusing an audio loop")
    if BLACKHOLE_NAME.casefold() not in output_device.name.casefold():
        raise ValueError(
            f"output must be {BLACKHOLE_NAME!r}, got {output_device.name!r}"
        )


class InputRouteMonitor:
    """Detect whether the explicitly selected physical input disappears.

    CoreAudio can keep an existing stream alive by changing its physical route
    after a headset is unplugged.  Sounddevice does not expose that reroute in
    the callback, so the controller polls the device inventory outside the
    real-time thread.  This monitor reports only inventory state; it never
    changes an audio route or starts a fallback stream.
    """

    def __init__(self, expected: Device):
        if expected.max_input_channels <= 0:
            raise ValueError("route monitor requires an input device")
        self.expected_name = expected.name
        self._available = True
        self.events: list[dict[str, Any]] = []

    def observe(self, devices: Iterable[Device], now: float | None = None) -> dict | None:
        observed_at = time.monotonic() if now is None else now
        try:
            current = resolve_device(devices, self.expected_name, "input")
        except ValueError as error:
            available = False
            detail = str(error)
            device = None
        else:
            available = True
            detail = None
            device = current.to_dict()
        if available == self._available:
            return None
        self._available = available
        event = {
            "elapsed_seconds": observed_at,
            "state": "available" if available else "unavailable",
            "expected_input_device": self.expected_name,
            "device": device,
            "detail": detail,
        }
        self.events.append(event)
        return event

    def stats(self) -> dict:
        return {
            "expected_input_device": self.expected_name,
            "currently_available": self._available,
            "events": list(self.events),
        }


def resample(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return np.asarray(audio, dtype=np.float32)
    ratio = Fraction(target_rate, source_rate).limit_denominator()
    return np.asarray(
        resample_poly(audio, ratio.numerator, ratio.denominator, axis=0),
        dtype=np.float32,
    )


def map_channels(audio: np.ndarray, output_channels: int) -> np.ndarray:
    value = np.asarray(audio, dtype=np.float32)
    if value.ndim == 1:
        value = value[:, None]
    if output_channels == value.shape[1]:
        return value
    mono = value.mean(axis=1, keepdims=True)
    if output_channels == 1:
        return mono
    return np.repeat(mono, output_channels, axis=1)


def play_file(path: Path, output_device: Device) -> dict[str, Any]:
    audio, source_rate = sf.read(path, dtype="float32", always_2d=True)
    target_rate = int(output_device.default_samplerate)
    audio = resample(audio, int(source_rate), target_rate)
    channels = min(2, output_device.max_output_channels)
    audio = map_channels(audio, channels)
    started = time.monotonic()
    sd.play(audio, samplerate=target_rate, device=output_device.index, blocking=True)
    elapsed = time.monotonic() - started
    return {
        "file": str(path.resolve()),
        "source_rate": int(source_rate),
        "output_rate": target_rate,
        "output_device": output_device.to_dict(),
        "audio_seconds": len(audio) / target_rate,
        "wall_seconds": elapsed,
    }


def probe_loopback(path: Path, device: Device) -> dict[str, Any]:
    """Play into and capture from the same virtual device, then measure fidelity."""
    if BLACKHOLE_NAME.casefold() not in device.name.casefold():
        raise ValueError(f"loopback probe requires {BLACKHOLE_NAME!r}")
    if not device.max_input_channels or not device.max_output_channels:
        raise ValueError("loopback probe requires a duplex virtual device")
    audio, source_rate = sf.read(path, dtype="float32", always_2d=True)
    sample_rate = int(device.default_samplerate)
    mono = map_channels(resample(audio, int(source_rate), sample_rate), 1)[:, 0]
    padding = np.zeros(sample_rate // 4, dtype=np.float32)
    signal = np.concatenate((padding, mono, padding))
    output = map_channels(signal, min(2, device.max_output_channels))
    captured = sd.playrec(
        output,
        samplerate=sample_rate,
        device=device.index,
        channels=min(2, device.max_input_channels),
        dtype="float32",
        blocking=True,
    )
    observed = captured[:, 0]
    values = correlate(observed, signal, mode="full", method="fft")
    lags = correlation_lags(len(observed), len(signal), mode="full")
    best = int(np.argmax(np.abs(values)))
    lag = int(lags[best])
    start_observed = max(lag, 0)
    start_signal = max(-lag, 0)
    length = min(len(observed) - start_observed, len(signal) - start_signal)
    aligned_observed = observed[start_observed : start_observed + length]
    aligned_signal = signal[start_signal : start_signal + length]
    denominator = float(np.dot(aligned_signal, aligned_signal))
    gain = float(np.dot(aligned_observed, aligned_signal) / denominator) if denominator else 0.0
    residual = aligned_observed - gain * aligned_signal
    signal_power = float(np.mean(np.square(gain * aligned_signal)))
    noise_power = float(np.mean(np.square(residual)))
    snr_db = float(10 * np.log10(signal_power / max(noise_power, 1e-20)))
    normalized_correlation = float(
        abs(values[best])
        / max(np.linalg.norm(observed) * np.linalg.norm(signal), 1e-20)
    )
    return {
        "file": str(path.resolve()),
        "device": device.to_dict(),
        "samplerate": sample_rate,
        "lag_frames": lag,
        "lag_ms": lag / sample_rate * 1000,
        "gain": gain,
        "normalized_correlation": normalized_correlation,
        "snr_db": snr_db,
        "captured_peak": float(np.max(np.abs(observed))),
    }


def passthrough(
    input_device: Device,
    output_device: Device,
    duration: float,
    blocksize: int,
) -> dict[str, Any]:
    ensure_safe_route(input_device, output_device)
    input_rate = int(input_device.default_samplerate)
    output_rate = int(output_device.default_samplerate)
    if input_rate != output_rate:
        raise ValueError(
            f"phase-A passthrough requires equal rates, got {input_rate} -> {output_rate}"
        )
    channels_out = min(2, output_device.max_output_channels)
    statuses: queue.SimpleQueue[str] = queue.SimpleQueue()
    callback_count = 0

    def callback(indata: np.ndarray, outdata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        nonlocal callback_count
        callback_count += 1
        if status:
            statuses.put(str(status))
        mapped = map_channels(indata[:frames], channels_out)
        outdata[:frames] = mapped

    started = time.monotonic()
    with sd.Stream(
        device=(input_device.index, output_device.index),
        samplerate=input_rate,
        blocksize=blocksize,
        dtype="float32",
        channels=(1, channels_out),
        callback=callback,
    ):
        sd.sleep(round(duration * 1000))
    elapsed = time.monotonic() - started
    errors: list[str] = []
    while not statuses.empty():
        errors.append(statuses.get())
    return {
        "input_device": input_device.to_dict(),
        "output_device": output_device.to_dict(),
        "samplerate": input_rate,
        "blocksize": blocksize,
        "nominal_block_ms": blocksize / input_rate * 1000,
        "requested_seconds": duration,
        "wall_seconds": elapsed,
        "callback_count": callback_count,
        "stream_statuses": errors,
    }


def record_input(
    input_device: Device,
    output_path: Path,
    duration: float,
    countdown: float = 3.0,
) -> dict[str, Any]:
    if BLACKHOLE_NAME.casefold() in input_device.name.casefold():
        raise ValueError("recording requires a physical input, not BlackHole")
    if countdown > 0:
        sd.sleep(round(countdown * 1000))
    sample_rate = int(input_device.default_samplerate)
    frames = round(duration * sample_rate)
    audio = sd.rec(
        frames,
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        device=input_device.index,
        blocking=True,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output_path, audio, sample_rate, subtype="FLOAT")
    absolute = np.abs(audio)
    return {
        "file": str(output_path.resolve()),
        "input_device": input_device.to_dict(),
        "samplerate": sample_rate,
        "duration_seconds": len(audio) / sample_rate,
        "peak": float(np.max(absolute)),
        "rms": float(np.sqrt(np.mean(np.square(audio, dtype=np.float64)))),
        "near_clip_fraction": float(np.mean(absolute >= 0.99)),
    }
