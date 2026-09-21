"""Stream a long real-environment recording through personalized ONNX TSE."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import soundfile as sf
import torch
import torchaudio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from micforyou.runtime import (
    build_ort_cpu_session,
    select_enrollment_window,
    validate_ort_conditioning_shapes,
)

from benchmark_onnx_tse import OnnxTseStream, make_onnx_transform
from probe_real_tse_stateful import precompute_conditioning


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--enrollment", type=Path, required=True)
    parser.add_argument("--enrollment-seconds", type=float, default=6.0)
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--onnx-threads", type=int, default=1)
    parser.add_argument("--frames-per-chunk", type=int, default=8)
    parser.add_argument("--audio-block", type=int, default=480)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

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
    enrollment, enrollment_selection = select_enrollment_window(
        enrollment, int(extractor.resample_rate), args.enrollment_seconds
    )
    with torch.inference_mode():
        conditioning = precompute_conditioning(model, enrollment)

    session, runtime = build_ort_cpu_session(args.onnx, args.onnx_threads)
    validate_ort_conditioning_shapes(session, conditioning)
    stream = OnnxTseStream(
        session,
        conditioning,
        args.frames_per_chunk,
        len(model.sep_model.separator.separation),
    )
    transform, flush = make_onnx_transform(stream)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    input_samples = 0
    output_samples = 0
    input_square_sum = 0.0
    output_square_sum = 0.0
    started = time.perf_counter()
    with sf.SoundFile(args.input) as source:
        if source.samplerate != 48_000 or source.channels != 1:
            raise ValueError("input must be mono 48 kHz audio")
        expected_samples = len(source)
        with sf.SoundFile(
            args.output,
            mode="w",
            samplerate=48_000,
            channels=1,
            subtype="PCM_16",
        ) as destination:
            while True:
                block = source.read(args.audio_block, dtype="float32", always_2d=False)
                if not len(block):
                    break
                input_samples += len(block)
                input_square_sum += float(np.square(block, dtype=np.float64).sum())
                enhanced = transform(block)
                remaining = expected_samples - output_samples
                if len(enhanced) and remaining > 0:
                    enhanced = enhanced[:remaining]
                    if not np.isfinite(enhanced).all():
                        raise ValueError("TSE output contains non-finite samples")
                    destination.write(enhanced)
                    output_samples += len(enhanced)
                    output_square_sum += float(
                        np.square(enhanced, dtype=np.float64).sum()
                    )
            enhanced = flush()
            remaining = expected_samples - output_samples
            if len(enhanced) and remaining > 0:
                enhanced = enhanced[:remaining]
                if not np.isfinite(enhanced).all():
                    raise ValueError("TSE flush contains non-finite samples")
                destination.write(enhanced)
                output_samples += len(enhanced)
                output_square_sum += float(np.square(enhanced, dtype=np.float64).sum())

    elapsed = time.perf_counter() - started
    calls = np.asarray(stream.call_ms, dtype=np.float64)
    input_rms = float(np.sqrt(input_square_sum / max(input_samples, 1)))
    output_rms = float(np.sqrt(output_square_sum / max(output_samples, 1)))
    report = {
        "schema": "micforyou/real-environment-extraction/1",
        "input": str(args.input),
        "input_sha256": sha256(args.input),
        "output": str(args.output),
        "output_sha256": sha256(args.output),
        "onnx_sha256": sha256(args.onnx),
        "enrollment": "<local-private-audio>",
        "enrollment_selection": enrollment_selection,
        "runtime": runtime,
        "input_samples": input_samples,
        "output_samples": output_samples,
        "length_match": input_samples == output_samples,
        "audio_seconds": input_samples / 48_000,
        "processing_seconds": elapsed,
        "processing_rtf": elapsed / (input_samples / 48_000),
        "model_calls": len(calls),
        "model_call_ms_p50": float(np.percentile(calls, 50)),
        "model_call_ms_p95": float(np.percentile(calls, 95)),
        "model_call_ms_max": float(calls.max()),
        "input_rms": input_rms,
        "output_rms": output_rms,
        "output_attenuation_db": float(
            20 * np.log10(max(output_rms, 1e-20) / max(input_rms, 1e-20))
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
