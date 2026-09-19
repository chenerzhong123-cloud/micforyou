"""Source, correctness, and runtime probe for the causal Pos/Neg TSE model.

This probe uses deterministic synthetic signals only. It does not evaluate
speaker extraction quality and it never invokes an ASR system.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import torch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--chunk-samples", type=int, default=512)
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--seed", type=int, default=20260919)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * fraction)))
    return ordered[index]


def tensors(value: Any):
    if isinstance(value, torch.Tensor):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from tensors(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            yield from tensors(child)


def build_model(repo: Path, checkpoint: Path) -> torch.nn.Module:
    sys.path.insert(0, str(repo))
    from model.GridnetAttnHead import GridNetBlock_attnhead
    from model.tfgridnet_KVfusion import TFGridNet_KVfusion
    from model.tfgridnet_crossattn_causal_single_emb import (
        TFGridNet_origcrossattn_causal_single_emb,
    )
    from model.tfgridnet_encoder import TFGridNet_encoder

    encoder = TFGridNet_encoder(
        num_ch=2, n_fft=128, stride=64, num_blocks=3, binaural=False
    )
    encoder_head = GridNetBlock_attnhead(layer_num=2, pooling_size=1, stride=1)
    model = TFGridNet_origcrossattn_causal_single_emb(
        n_fft=128,
        stride=64,
        n_layers=3,
        lstm_hidden_units=64,
        emb_dim=64,
        emb_ks=1,
        model_normalize=True,
        Fusion_class=TFGridNet_KVfusion,
        pooling_size=40,
        fusion_stride=40,
        encoder=encoder,
        encoder_head=encoder_head,
        train_encoder=False,
        train_encoder_head=False,
        fusion_layer=[0, 1],
        binaural=False,
    )
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    model.load_state_dict(payload["state_dict"], strict=True)
    return model.eval()


def synthetic_signal(samples: int, generator: torch.Generator) -> torch.Tensor:
    noise = torch.randn((1, 1, samples), generator=generator) * 0.012
    timeline = torch.arange(samples, dtype=torch.float32) / 16_000.0
    tone = 0.025 * torch.sin(2.0 * torch.pi * 173.0 * timeline)
    return noise + tone.view(1, 1, -1)


def run_stream(
    model: torch.nn.Module,
    condition: torch.Tensor,
    signal: torch.Tensor,
    chunk_samples: int,
) -> tuple[torch.Tensor, list[float], dict[str, Any]]:
    state = model.init_buffers(1, "cpu")
    outputs: list[torch.Tensor] = []
    calls_ms: list[float] = []
    for start in range(0, signal.shape[-1], chunk_samples):
        chunk = signal[..., start : start + chunk_samples]
        before = time.perf_counter()
        output, state = model(chunk, condition, state)
        calls_ms.append((time.perf_counter() - before) * 1000.0)
        outputs.append(output)
    merged = torch.cat(outputs, dim=-1)
    state_tensors = list(tensors(state))
    state_summary = {
        "tensor_count": len(state_tensors),
        "finite": all(bool(torch.isfinite(item).all()) for item in state_tensors),
        "max_abs": max(float(item.abs().max()) for item in state_tensors),
    }
    return merged, calls_ms, state_summary


def main() -> None:
    args = parse_args()
    if args.chunk_samples < 128 or args.chunk_samples % 64:
        raise SystemExit("--chunk-samples must be >=128 and divisible by 64")
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    generator = torch.Generator().manual_seed(args.seed)
    model = build_model(args.repo.resolve(), args.checkpoint.resolve())

    positive = synthetic_signal(48_000, generator)
    negative = synthetic_signal(48_000, generator)
    with torch.inference_mode():
        before = time.perf_counter()
        condition = model.encode(positive, negative)
        enrollment_ms = (time.perf_counter() - before) * 1000.0

        requested_samples = int(round(args.seconds * 16_000))
        requested_samples -= requested_samples % args.chunk_samples
        signal = synthetic_signal(requested_samples, generator)

        # Untimed warm-up with a fresh state for the measured stream.
        warm_state = model.init_buffers(1, "cpu")
        model(signal[..., : args.chunk_samples], condition, warm_state)
        before = time.perf_counter()
        output, calls_ms, state_summary = run_stream(
            model, condition, signal, args.chunk_samples
        )
        elapsed = time.perf_counter() - before

        repeat, _, _ = run_stream(model, condition, signal, args.chunk_samples)
        silence_state = model.init_buffers(1, "cpu")
        silence, _ = model(
            torch.zeros((1, 1, args.chunk_samples)), condition, silence_state
        )

        parity_samples = min(requested_samples, 32_768)
        parity_samples -= parity_samples % args.chunk_samples
        parity_signal = signal[..., :parity_samples]
        whole_state = model.init_buffers(1, "cpu")
        whole, _ = model(parity_signal, condition, whole_state)
        chunked, _, _ = run_stream(
            model, condition, parity_signal, args.chunk_samples
        )
        delta = whole - chunked

    source_commit = subprocess.run(
        ["git", "-C", str(args.repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    result = {
        "status": "PROBE_ONLY",
        "scope": "synthetic correctness and runtime; not extraction quality",
        "source": {
            "repo": "https://github.com/xu-shitong/TSE-through-Positive-Negative-Enroll",
            "commit": source_commit,
            "checkpoint": args.checkpoint.name,
            "checkpoint_bytes": args.checkpoint.stat().st_size,
            "checkpoint_sha256": sha256(args.checkpoint),
            "weight_license": "CC-BY-NC-ND-4.0 (Hugging Face metadata)",
        },
        "environment": {
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "threads": args.threads,
            "device": "cpu",
        },
        "model": {
            "parameters": sum(parameter.numel() for parameter in model.parameters()),
            "sample_rate": 16_000,
            "chunk_samples": args.chunk_samples,
            "chunk_ms": args.chunk_samples / 16.0,
            "condition_shape": list(condition.shape),
            "enrollment_encode_ms": enrollment_ms,
        },
        "stream": {
            "audio_seconds": requested_samples / 16_000.0,
            "elapsed_seconds": elapsed,
            "rtf": elapsed / (requested_samples / 16_000.0),
            "calls": len(calls_ms),
            "call_ms_p50": statistics.median(calls_ms),
            "call_ms_p95": percentile(calls_ms, 0.95),
            "call_ms_max": max(calls_ms),
            "input_samples": requested_samples,
            "output_samples": output.shape[-1],
            "output_finite": bool(torch.isfinite(output).all()),
            "output_peak": float(output.abs().max()),
            "state": state_summary,
            "repeat_max_abs_delta": float((output - repeat).abs().max()),
        },
        "silence": {
            "finite": bool(torch.isfinite(silence).all()),
            "nonfinite_samples": int((~torch.isfinite(silence)).sum()),
        },
        "whole_vs_chunked": {
            "samples": parity_samples,
            "max_abs_delta": float(delta.abs().max()),
            "mean_abs_delta": float(delta.abs().mean()),
            "whole_rms": float(whole.square().mean().sqrt()),
            "chunked_rms": float(chunked.square().mean().sqrt()),
        },
    }
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
