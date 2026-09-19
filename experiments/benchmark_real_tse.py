"""Repeatable full-path performance benchmark for the REAL-TSE live bridge.

For each candidate ``--frames-per-chunk`` value this drives the complete
48 kHz -> 16 kHz -> causal TSE -> 16 kHz -> 48 kHz chain over deterministic
synthetic audio (no user speech) and reports RTF, model-call percentiles, and
integrity checks as machine-readable JSON. It ends with an explicit
fast/balanced/conservative/unsupported recommendation; the live bridge still
requires the user to pass ``--frames-per-chunk`` explicitly.

Run with the official REAL-TSE venv, e.g.:

/Users/deuce/claudeproject/codexworks/micforyou/model-sources/wesep-real-tse/.venv-official/bin/python \
  experiments/benchmark_real_tse.py --repo .../wesep-real-tse --model-dir .../tfmap_context_causal_100 \
  --result /Users/deuce/claudeproject/codexworks/micforyou/runs/benchmark.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch
import torchaudio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from micforyou.recommendation import BenchmarkCandidate, recommend
from micforyou.reporting import collect_system_info
from micforyou.synth import DEFAULT_SEED, synthetic_blocks

from probe_real_tse_stateful import precompute_conditioning, sha256
from run_real_tse_bridge import CausalTseStream, make_real_tse_transform

DEFAULT_ENROLLMENT = Path(
    "/Users/deuce/claudeproject/codexworks/micforyou/test-data/public/target-enrollment.flac"
)


def run_candidate(
    model,
    conditioning,
    frames: int,
    input_audio: np.ndarray,
    audio_block: int,
) -> dict:
    """One warmup + one measured pass over the complete bridge DSP path."""
    def build():
        stream = CausalTseStream(model, conditioning, frames, torch.device("cpu"))
        return (stream, *make_real_tse_transform(stream))

    warmup_frames = min(len(input_audio), 48_000 * 3)
    warmup_stream, warmup_transform, warmup_flush = build()
    started = time.perf_counter()
    with torch.inference_mode():
        for offset in range(0, warmup_frames, audio_block):
            warmup_transform(input_audio[offset : offset + audio_block])
        warmup_flush()
    warmup_seconds = time.perf_counter() - started
    del warmup_stream

    stream, transform, flush = build()
    outputs: list[np.ndarray] = []
    error: str | None = None
    started = time.perf_counter()
    try:
        with torch.inference_mode():
            for offset in range(0, len(input_audio), audio_block):
                outputs.append(transform(input_audio[offset : offset + audio_block]))
            outputs.append(flush())
    except Exception as failure:  # recorded; candidate is marked invalid
        error = repr(failure)
    processing_seconds = time.perf_counter() - started

    output = (
        np.concatenate([part for part in outputs if len(part)])
        if error is None
        else np.zeros(0, dtype=np.float32)
    )
    calls = np.asarray(stream.call_ms, dtype=np.float64)
    return {
        "frames_per_chunk": frames,
        "model_chunk_ms": frames * 8,
        "warmup_seconds": warmup_seconds,
        "processing_seconds": processing_seconds,
        "processing_rtf": processing_seconds / (len(input_audio) / 48_000),
        "model_calls": int(len(calls)),
        "model_call_ms_p50": float(np.percentile(calls, 50)) if len(calls) else None,
        "model_call_ms_p95": float(np.percentile(calls, 95)) if len(calls) else None,
        "model_call_ms_max": float(calls.max()) if len(calls) else None,
        "input_samples": len(input_audio),
        "output_samples": len(output),
        "length_match": len(output) == len(input_audio),
        "nonfinite_samples": int((~np.isfinite(output)).sum()) if error is None else -1,
        "output_peak": float(np.abs(output).max()) if len(output) else 0.0,
        "output_rms": (
            float(np.sqrt(np.mean(np.square(output, dtype=np.float64))))
            if len(output)
            else 0.0
        ),
        "error": error,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument(
        "--enrollment",
        type=Path,
        default=DEFAULT_ENROLLMENT,
        help="speaker-conditioning audio; the default is a public sample, not user voice",
    )
    parser.add_argument(
        "--mixture",
        type=Path,
        default=None,
        help="optional 48 kHz mono input file; default is deterministic synthetic audio",
    )
    parser.add_argument("--frames", type=int, nargs="+", default=[8, 16, 24])
    parser.add_argument("--audio-seconds", type=float, default=60.0)
    parser.add_argument("--audio-block", type=int, default=480)
    parser.add_argument(
        "--torch-threads",
        type=int,
        default=None,
        help="override the thread count after wesep import (upstream sets it to 1)",
    )
    parser.add_argument(
        "--torch-interop-threads",
        type=int,
        default=None,
        help="limit PyTorch operator-level scheduling threads before model load",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--tir-db", type=float, default=-6.0)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    if any(frames < 1 or frames > 128 for frames in args.frames):
        raise SystemExit("frames values must be within 1..128")
    if args.audio_seconds < 5:
        raise SystemExit("--audio-seconds must be >= 5 for stable percentiles")
    if args.torch_threads is not None and args.torch_threads < 1:
        raise SystemExit("--torch-threads must be >= 1")
    if args.torch_interop_threads is not None and args.torch_interop_threads < 1:
        raise SystemExit("--torch-interop-threads must be >= 1")

    sys.path.insert(0, str(args.repo))
    import wesep  # noqa: PLC0415

    upstream_torch_threads = torch.get_num_threads()
    upstream_torch_interop_threads = torch.get_num_interop_threads()
    if args.torch_threads is not None:
        torch.set_num_threads(args.torch_threads)
    if args.torch_interop_threads is not None:
        torch.set_num_interop_threads(args.torch_interop_threads)

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

    total_frames = int(round(args.audio_seconds * 48_000))
    if args.mixture is not None:
        source, source_rate = torchaudio.load(args.mixture)
        if source.shape[0] > 1:
            source = source.mean(dim=0, keepdim=True)
        if source_rate != 48_000:
            source = torchaudio.functional.resample(source, source_rate, 48_000)
        source = source.reshape(-1).numpy()
        repeats = -(-total_frames // len(source))
        input_audio = np.tile(source, repeats)[:total_frames].astype(np.float32)
        input_description = {
            "source": str(args.mixture),
            "kind": "file",
            "tiled": repeats,
        }
    else:
        input_audio = np.concatenate(
            list(
                synthetic_blocks(
                    total_frames,
                    seed=args.seed,
                    tir_db=args.tir_db,
                    pulse_every_seconds=None,
                    block_frames=args.audio_block,
                )
            )
        )
        input_description = {
            "source": "in-process synthetic speech-shaped noise, no user audio",
            "kind": "synthetic",
            "seed": args.seed,
            "tir_db": args.tir_db,
        }

    system = collect_system_info(
        {
            "torch": torch.__version__,
            "torch_threads": torch.get_num_threads(),
            "torch_interop_threads": torch.get_num_interop_threads(),
            "upstream_torch_threads": upstream_torch_threads,
            "upstream_torch_interop_threads": upstream_torch_interop_threads,
            "benchmark_host_note": "single-host snapshot; results are not transferable",
        }
    )
    print(
        f"benchmarking frames={args.frames} over {args.audio_seconds:g}s "
        f"({'synthetic' if args.mixture is None else 'file'}) input",
        flush=True,
    )

    results = []
    for frames in args.frames:
        print(f"  frames={frames} ...", flush=True)
        results.append(
            run_candidate(model, conditioning, frames, input_audio, args.audio_block)
        )

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
        for item in results
    ]
    recommendation = recommend(candidates)

    payload = {
        "schema": "micforyou-benchmark-1",
        "generated_at": system["captured_at"],
        "system": system,
        "model": {
            "repo_commit": "2a540977a348fbaa92e623210505430e2cec608d",
            "weights_sha256": sha256(args.model_dir / "avg_model.pt"),
            "model_id": "tfmap_context_causal_100",
            "hop_ms": 8,
            "algorithmic_latency_ms": 24,
        },
        "input": {
            **input_description,
            "sample_rate": 48_000,
            "seconds": args.audio_seconds,
            "audio_block": args.audio_block,
            "samples": len(input_audio),
            "peak": float(np.abs(input_audio).max()),
        },
        "runtime": {
            "enrollment": str(args.enrollment),
            "resamplers": "soxr HQ streams, 48k->16k->48k",
            "path": "full bridge DSP path; no audio devices were opened",
            "audio_written": False,
        },
        "candidates": results,
        "recommendation": recommendation.to_dict(),
        "command": [str(part) for part in sys.argv],
    }
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    print(json.dumps(payload["recommendation"], ensure_ascii=False, indent=2))
    print(f"result json: {args.result}")
    sys.stdout.flush()
    # The official venv's C++ audio/torch teardown path can abort after the
    # result is already written; exit deterministically once done.
    import os

    os._exit(0)


if __name__ == "__main__":
    main()
