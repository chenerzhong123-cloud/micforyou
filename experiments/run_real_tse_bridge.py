"""Experimental physical-mic -> causal REAL-TSE -> BlackHole bridge.

Audio callbacks only move bounded PCM blocks. Resampling and model inference run
on a worker thread. Any queue overflow or worker exception causes fault-silence;
raw microphone audio is never passed through as a fallback.

The queue/ring/fault core lives in ``micforyou.bridging.BridgeEngine`` so unit
tests can replay overflow and inference failures without audio hardware.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soxr
import torch
import torchaudio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from micforyou.audio import ensure_safe_route, list_devices, resolve_device
from micforyou.bridging import BridgeEngine, LatencyLedger
from micforyou.recommendation import estimate_core_latency_ms

from probe_real_tse_stateful import (
    StreamingOLA,
    StreamingSTFT,
    condition_features,
    mask_frames,
    precompute_conditioning,
    separator_chunk,
    sha256,
)


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
        self.call_times: list[float] = []

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
            finished = time.perf_counter()
            self.call_ms.append((finished - started) * 1000)
            self.call_times.append(finished)
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


def make_real_tse_transform(tse: CausalTseStream, sample_rate: int = 48_000):
    """Build the live 48 kHz -> 16 kHz -> TSE -> 16 kHz -> 48 kHz chain.

    Returns ``(transform, flush_transform)`` callables for ``BridgeEngine``.
    Inference mode is entered inside the callables because it is thread-local:
    the engine worker thread does not inherit the caller's context.
    """

    down = soxr.ResampleStream(sample_rate, 16_000, 1, dtype="float32", quality="HQ")
    up = soxr.ResampleStream(16_000, sample_rate, 1, dtype="float32", quality="HQ")

    def transform(block: np.ndarray) -> np.ndarray:
        low = down.resample_chunk(block, last=False)
        if not len(low):
            return np.empty(0, dtype=np.float32)
        with torch.inference_mode():
            enhanced = tse.feed(low)
        if not len(enhanced):
            return np.empty(0, dtype=np.float32)
        return up.resample_chunk(enhanced, last=False)

    def flush_transform() -> np.ndarray:
        pieces: list[np.ndarray] = []
        low_tail = down.resample_chunk(np.empty(0, dtype=np.float32), last=True)
        with torch.inference_mode():
            if len(low_tail):
                middle = tse.feed(low_tail)
                if len(middle):
                    pieces.append(up.resample_chunk(middle, last=False))
            tail = tse.flush()
        if len(tail):
            pieces.append(up.resample_chunk(tail, last=False))
        pieces.append(up.resample_chunk(np.empty(0, dtype=np.float32), last=True))
        return np.concatenate(pieces) if len(pieces) else np.empty(0, dtype=np.float32)

    return transform, flush_transform


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
    parser.add_argument(
        "--torch-threads",
        type=int,
        default=None,
        help="override the thread count after wesep import (upstream sets it to 1)",
    )
    parser.add_argument("--queue-ms", type=float, default=500)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    if args.torch_threads is not None and args.torch_threads < 1:
        raise SystemExit("--torch-threads must be >= 1")

    devices = list_devices()
    input_device = resolve_device(devices, args.input_device, "input")
    output_device = resolve_device(devices, args.output_device, "output")
    ensure_safe_route(input_device, output_device)

    sys.path.insert(0, str(args.repo))
    import wesep  # noqa: PLC0415

    upstream_torch_threads = torch.get_num_threads()
    if args.torch_threads is not None:
        torch.set_num_threads(args.torch_threads)

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
    transform, flush_transform = make_real_tse_transform(tse)

    sample_rate = 48_000
    maximum_frames = round(sample_rate * args.queue_ms / 1000)
    engine = BridgeEngine(
        transform,
        flush_transform,
        input_bound_blocks=max(2, maximum_frames // args.audio_block),
        ring_maximum_frames=maximum_frames,
    )
    ledger = LatencyLedger()
    capture_enabled = threading.Event()
    capture_enabled.set()
    statuses: list[str] = []
    callback_count = 0
    startup_silence_frames = 0
    underrun_frames = 0
    output_started = False
    position_in = 0

    def callback(indata, outdata, frames, time_info, status) -> None:
        nonlocal callback_count, startup_silence_frames, underrun_frames
        nonlocal output_started, position_in
        callback_count += 1
        if status:
            statuses.append(str(status))
        outdata.fill(0)
        arrival = time.perf_counter()
        if capture_enabled.is_set():
            engine.submit(indata[:frames, 0].copy())
            ledger.record_input(position_in, frames, arrival)
            position_in += frames
        mono, written = engine.write_output(frames)
        if written:
            # Map by ring audio position, not the output slot: after underruns
            # the slot runs ahead of the audio still buffered in the ring.
            audio_start = engine.output_ring.total_popped - written
            ledger.record_output(audio_start, written, time.perf_counter())
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
        device=(input_device.index, output_device.index),
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
                while not engine.fault.is_set():
                    sd.sleep(200)
        except KeyboardInterrupt:
            pass
        capture_enabled.clear()
        engine.finish(timeout=10)
        drain_deadline = time.monotonic() + 2
        while engine.output_ring.available() and time.monotonic() < drain_deadline:
            sd.sleep(10)

    elapsed = time.monotonic() - started
    values = np.asarray(tse.call_ms, dtype=np.float64)
    result = {
        "status": "FAULT" if engine.fault.is_set() else "STOPPED",
        "input_device": input_device.name,
        "output_device": output_device.name,
        "sample_rate": sample_rate,
        "audio_block": args.audio_block,
        "frames_per_model_chunk": args.frames_per_chunk,
        "torch_threads": torch.get_num_threads(),
        "upstream_torch_threads": upstream_torch_threads,
        "model_chunk_ms": args.frames_per_chunk * 8,
        "algorithmic_latency_ms": 24,
        "estimated_core_latency_ms": estimate_core_latency_ms(
            args.frames_per_chunk,
            float(np.percentile(values, 95)) if len(values) else 0.0,
        ),
        "portaudio_stream_latency_seconds": stream_latency,
        "model_sha256": sha256(args.model_dir / "avg_model.pt"),
        "elapsed_seconds": elapsed,
        "callback_count": callback_count,
        "model_call_count": len(tse.call_ms),
        "model_call_ms_p50": float(np.percentile(values, 50)) if len(values) else None,
        "model_call_ms_p95": float(np.percentile(values, 95)) if len(values) else None,
        "model_call_ms_max": float(values.max()) if len(values) else None,
        "engine": engine.stats(),
        "bridge_latency": ledger.summary(),
        "startup_silence_ms": startup_silence_frames / sample_rate * 1000,
        "underrun_ms": underrun_frames / sample_rate * 1000,
        "stream_statuses": statuses,
        "errors": engine.errors,
    }
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if engine.fault.is_set():
        raise SystemExit(2)


if __name__ == "__main__":
    main()
