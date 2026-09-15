"""Exercise the live bridge DSP path from a file without opening audio devices."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import soundfile as sf
import soxr
import torch
import torchaudio

from probe_real_tse_stateful import load_audio, precompute_conditioning, sha256
from run_real_tse_bridge import CausalTseStream


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--mixture", type=Path, required=True)
    parser.add_argument("--enrollment", type=Path, required=True)
    parser.add_argument("--frames-per-chunk", type=int, default=8)
    parser.add_argument("--audio-block", type=int, default=480)
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="repeat the input contiguously for an offline soak; must be positive",
    )
    parser.add_argument("--output-wav", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(args.repo))
    import wesep  # noqa: PLC0415

    extractor = wesep.load_model_local(str(args.model_dir))
    model = extractor.model.eval()
    enrollment = load_audio(args.enrollment, extractor.resample_rate)
    if args.repeat < 1:
        raise ValueError("--repeat must be positive")
    source = load_audio(args.mixture, 48_000).reshape(-1).numpy()
    source = np.tile(source, args.repeat)
    with torch.inference_mode():
        conditioning = precompute_conditioning(model, enrollment)
    stream = CausalTseStream(model, conditioning, args.frames_per_chunk, torch.device("cpu"))
    down = soxr.ResampleStream(48_000, 16_000, 1, dtype="float32", quality="HQ")
    up = soxr.ResampleStream(16_000, 48_000, 1, dtype="float32", quality="HQ")
    outputs: list[np.ndarray] = []

    started = time.perf_counter()
    with torch.inference_mode():
        for offset in range(0, len(source), args.audio_block):
            low_rate = down.resample_chunk(source[offset : offset + args.audio_block], last=False)
            if len(low_rate):
                enhanced = stream.feed(low_rate)
                if len(enhanced):
                    outputs.append(up.resample_chunk(enhanced, last=False))
        low_rate = down.resample_chunk(np.empty(0, dtype=np.float32), last=True)
        if len(low_rate):
            enhanced = stream.feed(low_rate)
            if len(enhanced):
                outputs.append(up.resample_chunk(enhanced, last=False))
        tail = stream.flush()
        if len(tail):
            outputs.append(up.resample_chunk(tail, last=False))
        outputs.append(up.resample_chunk(np.empty(0, dtype=np.float32), last=True))
    processing_seconds = time.perf_counter() - started

    output = np.concatenate([part for part in outputs if len(part)])
    if not np.isfinite(output).all():
        raise ValueError("bridge output contains non-finite samples")
    args.output_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(args.output_wav, output, 48_000, subtype="FLOAT")
    calls = np.asarray(stream.call_ms)
    result = {
        "model_sha256": sha256(args.model_dir / "avg_model.pt"),
        "input_samples_48k": len(source),
        "input_repetitions": args.repeat,
        "output_samples_48k": len(output),
        "duration_delta_ms": (len(output) - len(source)) / 48,
        "processing_seconds": processing_seconds,
        "processing_rtf": processing_seconds / (len(source) / 48_000),
        "model_chunk_ms": args.frames_per_chunk * 8,
        "algorithmic_latency_ms": 24,
        "model_call_ms_p50": float(np.percentile(calls, 50)),
        "model_call_ms_p95": float(np.percentile(calls, 95)),
        "model_call_ms_max": float(calls.max()),
        "output_peak": float(np.abs(output).max()),
        "output_rms": float(np.sqrt(np.mean(np.square(output)))),
        "output_wav": str(args.output_wav),
        "output_sha256": sha256(args.output_wav),
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
