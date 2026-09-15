"""Experimental physical-mic -> causal REAL-TSE -> BlackHole bridge.

Audio callbacks only move bounded PCM blocks. Resampling and model inference run
on a worker thread. Any queue overflow or worker exception causes fault-silence;
raw microphone audio is never passed through as a fallback.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
import queue
import sys
import threading
import time

import numpy as np
import sounddevice as sd
import soxr
import torch
import torchaudio

from probe_real_tse_stateful import (
    StreamingOLA,
    StreamingSTFT,
    condition_features,
    mask_frames,
    precompute_conditioning,
    separator_chunk,
    sha256,
)


class AudioRing:
    def __init__(self, maximum_frames: int):
        self.maximum_frames = maximum_frames
        self.blocks: deque[np.ndarray] = deque()
        self.offset = 0
        self.frames = 0
        self.maximum_observed = 0
        self.lock = threading.Lock()

    def push(self, audio: np.ndarray) -> bool:
        value = np.asarray(audio, dtype=np.float32).reshape(-1)
        if not len(value):
            return True
        with self.lock:
            if self.frames + len(value) > self.maximum_frames:
                self.blocks.clear()
                self.offset = 0
                self.frames = 0
                return False
            self.blocks.append(value)
            self.frames += len(value)
            self.maximum_observed = max(self.maximum_observed, self.frames)
        return True

    def pop(self, count: int) -> tuple[np.ndarray, int]:
        result = np.zeros(count, dtype=np.float32)
        written = 0
        with self.lock:
            while written < count and self.blocks:
                block = self.blocks[0]
                take = min(count - written, len(block) - self.offset)
                result[written : written + take] = block[self.offset : self.offset + take]
                written += take
                self.offset += take
                self.frames -= take
                if self.offset == len(block):
                    self.blocks.popleft()
                    self.offset = 0
        return result, written

    def available(self) -> int:
        with self.lock:
            return self.frames


class CausalTseStream:
    def __init__(self, model, conditioning, frames_per_chunk: int, device: torch.device):
        self.model = model
        self.conditioning = conditioning
        self.frames_per_chunk = frames_per_chunk
        self.stft = StreamingSTFT(model.sep_model.win, model.sep_model.stride, device)
        self.ola = StreamingOLA(model.sep_model.win, model.sep_model.stride, device)
        self.pending: list[torch.Tensor] = []
        self.states = [None] * len(model.sep_model.separator.separation)
        self.call_ms: list[float] = []

    def _process(self, force: bool = False) -> list[torch.Tensor]:
        outputs = []
        while len(self.pending) >= self.frames_per_chunk or (force and self.pending):
            count = min(self.frames_per_chunk, len(self.pending))
            spec = torch.cat(self.pending[:count], dim=-1)
            self.pending = self.pending[count:]
            started = time.perf_counter()
            features, mixture = condition_features(self.model, spec, self.conditioning)
            separated, self.states = separator_chunk(
                self.model.sep_model.separator, features, self.states
            )
            estimated = mask_frames(self.model, separated, mixture)
            outputs.extend(self.ola.push(estimated))
            self.call_ms.append((time.perf_counter() - started) * 1000)
        return outputs

    def feed(self, samples: np.ndarray) -> np.ndarray:
        tensor = torch.from_numpy(np.asarray(samples, dtype=np.float32)).to(
            next(self.model.parameters()).device
        )
        self.pending.extend(self.stft.push(tensor))
        outputs = self._process()
        if not outputs:
            return np.empty(0, dtype=np.float32)
        return torch.cat(outputs, dim=-1).reshape(-1).cpu().numpy()

    def flush(self) -> np.ndarray:
        self.pending.extend(self.stft.flush())
        outputs = self._process(force=True)
        outputs.extend(self.ola.flush())
        if not outputs:
            return np.empty(0, dtype=np.float32)
        return torch.cat(outputs, dim=-1).reshape(-1).cpu().numpy()


def resolve_device(selector: str, direction: str) -> tuple[int, dict]:
    devices = [dict(item) for item in sd.query_devices()]
    channel_key = f"max_{direction}_channels"
    exact = [
        (index, item)
        for index, item in enumerate(devices)
        if item["name"].casefold() == selector.casefold() and item[channel_key] > 0
    ]
    matches = exact or [
        (index, item)
        for index, item in enumerate(devices)
        if selector.casefold() in item["name"].casefold() and item[channel_key] > 0
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one {direction} device for {selector!r}, got {matches}")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--enrollment", type=Path, required=True)
    parser.add_argument("--input-device", required=True)
    parser.add_argument("--output-device", default="BlackHole 2ch")
    parser.add_argument("--duration", type=float, default=0)
    parser.add_argument(
        "--frames-per-chunk",
        type=int,
        required=True,
        help="must be selected from a local benchmark; do not assume a safe default",
    )
    parser.add_argument("--audio-block", type=int, default=480)
    parser.add_argument("--queue-ms", type=float, default=500)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    input_index, input_info = resolve_device(args.input_device, "input")
    output_index, output_info = resolve_device(args.output_device, "output")
    if "blackhole" in input_info["name"].casefold():
        raise ValueError("BlackHole cannot be the physical input")
    if "blackhole 2ch" not in output_info["name"].casefold():
        raise ValueError("output must be BlackHole 2ch")
    if input_index == output_index:
        raise ValueError("input and output cannot be the same device")

    sys.path.insert(0, str(args.repo))
    import wesep  # noqa: PLC0415

    extractor = wesep.load_model_local(str(args.model_dir))
    model = extractor.model.eval()
    enrollment, enrollment_rate = torchaudio.load(args.enrollment)
    if enrollment.shape[0] > 1:
        enrollment = enrollment.mean(dim=0, keepdim=True)
    if enrollment_rate != extractor.resample_rate:
        enrollment = torchaudio.functional.resample(
            enrollment, enrollment_rate, extractor.resample_rate
        )
    with torch.inference_mode():
        conditioning = precompute_conditioning(model, enrollment)
    tse = CausalTseStream(model, conditioning, args.frames_per_chunk, torch.device("cpu"))

    sample_rate = 48_000
    maximum_frames = round(sample_rate * args.queue_ms / 1000)
    input_queue: queue.Queue[np.ndarray | None] = queue.Queue(
        maxsize=max(2, maximum_frames // args.audio_block)
    )
    output_ring = AudioRing(maximum_frames)
    fault = threading.Event()
    capture_enabled = threading.Event()
    capture_enabled.set()
    worker_done = threading.Event()
    errors: list[str] = []
    statuses: list[str] = []
    input_queue_max = 0
    callback_count = 0
    startup_silence_frames = 0
    underrun_frames = 0
    output_started = False

    def worker() -> None:
        nonlocal input_queue_max
        down = soxr.ResampleStream(sample_rate, 16_000, 1, dtype="float32", quality="HQ")
        up = soxr.ResampleStream(16_000, sample_rate, 1, dtype="float32", quality="HQ")

        def push_or_raise(value: np.ndarray) -> None:
            if len(value) and not output_ring.push(value):
                raise RuntimeError("output queue exceeded its bound")

        try:
            while True:
                block = input_queue.get()
                if block is None:
                    break
                input_queue_max = max(input_queue_max, input_queue.qsize())
                downsampled = down.resample_chunk(block, last=False)
                if len(downsampled):
                    enhanced = tse.feed(downsampled)
                    push_or_raise(up.resample_chunk(enhanced, last=False))
            down_tail = down.resample_chunk(np.empty(0, dtype=np.float32), last=True)
            if len(down_tail):
                tail = tse.feed(down_tail)
                if len(tail):
                    push_or_raise(up.resample_chunk(tail, last=False))
            tail = tse.flush()
            if len(tail):
                push_or_raise(up.resample_chunk(tail, last=False))
            push_or_raise(up.resample_chunk(np.empty(0, dtype=np.float32), last=True))
        except Exception as error:  # callback must remain fault-silent
            errors.append(repr(error))
            fault.set()
        finally:
            worker_done.set()

    thread = threading.Thread(target=worker, name="micforyou-tse", daemon=True)
    thread.start()

    def callback(indata, outdata, frames, time_info, status) -> None:
        nonlocal callback_count, startup_silence_frames, underrun_frames, output_started
        callback_count += 1
        if status:
            statuses.append(str(status))
        outdata.fill(0)
        if fault.is_set():
            return
        if capture_enabled.is_set():
            try:
                input_queue.put_nowait(indata[:frames, 0].copy())
            except queue.Full:
                errors.append("input queue exceeded its bound")
                fault.set()
                return
        mono, written = output_ring.pop(frames)
        if written:
            output_started = True
            outdata[:, 0] = mono
            outdata[:, 1] = mono
        if written < frames:
            if output_started:
                underrun_frames += frames - written
            else:
                startup_silence_frames += frames - written

    started = time.monotonic()
    stream_latency = None
    with sd.Stream(
        device=(input_index, output_index),
        samplerate=sample_rate,
        blocksize=args.audio_block,
        channels=(1, 2),
        dtype="float32",
        callback=callback,
    ) as stream:
        stream_latency = stream.latency
        try:
            if args.duration > 0:
                sd.sleep(round(args.duration * 1000))
            else:
                while not fault.is_set():
                    sd.sleep(200)
        except KeyboardInterrupt:
            pass
        capture_enabled.clear()
        input_queue.put(None)
        worker_done.wait(timeout=10)
        drain_deadline = time.monotonic() + 2
        while output_ring.available() and time.monotonic() < drain_deadline:
            sd.sleep(10)

    elapsed = time.monotonic() - started
    values = np.asarray(tse.call_ms, dtype=np.float64)
    result = {
        "status": "FAULT" if fault.is_set() else "STOPPED",
        "input_device": input_info["name"],
        "output_device": output_info["name"],
        "sample_rate": sample_rate,
        "audio_block": args.audio_block,
        "frames_per_model_chunk": args.frames_per_chunk,
        "model_chunk_ms": args.frames_per_chunk * 8,
        "algorithmic_latency_ms": 24,
        "estimated_core_latency_ms": 24 + args.frames_per_chunk * 8 + (
            float(np.percentile(values, 95)) if len(values) else 0
        ),
        "portaudio_stream_latency_seconds": stream_latency,
        "model_sha256": sha256(args.model_dir / "avg_model.pt"),
        "elapsed_seconds": elapsed,
        "callback_count": callback_count,
        "model_call_count": len(tse.call_ms),
        "model_call_ms_p50": float(np.percentile(values, 50)) if len(values) else None,
        "model_call_ms_p95": float(np.percentile(values, 95)) if len(values) else None,
        "model_call_ms_max": float(values.max()) if len(values) else None,
        "input_queue_max_blocks": input_queue_max,
        "output_queue_max_frames": output_ring.maximum_observed,
        "startup_silence_ms": startup_silence_frames / sample_rate * 1000,
        "underrun_ms": underrun_frames / sample_rate * 1000,
        "stream_statuses": statuses,
        "errors": errors,
    }
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if fault.is_set():
        raise SystemExit(2)


if __name__ == "__main__":
    main()
