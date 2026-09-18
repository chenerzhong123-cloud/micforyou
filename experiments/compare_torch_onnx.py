"""ONNX correctness gate for the stateful REAL-TSE core (Spec Phase R1).

Checks, in order and before any speed claim:
  1. ONNX checker (done at export) + ORT session creation
  2. input/output shapes
  3. single chunk: PyTorch streaming path vs ONNX numerical agreement
  4. 100 consecutive chunks: stateful streaming stays in agreement
     (states handed from one chunk to the next on both sides; no resets)

Writes handoff/mac-b-onnx-correctness.json. Suggested FP32 gate:
max_abs_error <= 1e-4 ~ 1e-3.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import torch
import torchaudio


def relative_error(diff: np.ndarray, reference: np.ndarray) -> float:
    denominator = np.linalg.norm(reference)
    return float(np.linalg.norm(diff) / denominator) if denominator else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--enrollment", type=Path, required=True)
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--frames-per-chunk", type=int, default=8)
    parser.add_argument("--chunks", type=int, default=100)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    import onnxruntime as ort

    sys.path.insert(0, str(args.repo))
    import wesep  # noqa: PLC0415

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from probe_real_tse_stateful import (
        condition_features,
        mask_frames,
        precompute_conditioning,
        separator_chunk,
        sha256,
    )

    torch.manual_seed(20260918)
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

    session = ort.InferenceSession(
        str(args.onnx), providers=["CPUExecutionProvider"]
    )
    input_names = {item.name for item in session.get_inputs()}
    output_names = [item.name for item in session.get_outputs()]

    # ---- deterministic shared input: identical frames fed to both paths ----
    sample_rate = int(extractor.resample_rate)
    samples_needed = args.chunks * args.frames_per_chunk * 128 + 16000
    waveform = torch.randn(1, sample_rate * (samples_needed // sample_rate + 1))
    waveform = waveform[:, :samples_needed] * 0.05

    from probe_real_tse_stateful import StreamingSTFT

    streamer = StreamingSTFT(model.sep_model.win, model.sep_model.stride, torch.device("cpu"))
    frame_list = []
    block = sample_rate // 100
    with torch.inference_mode():
        for offset in range(0, waveform.shape[1], block):
            frame_list.extend(streamer.push(waveform[:, offset : offset + block]))
        frame_list.extend(streamer.flush())
    specs = torch.cat(frame_list, dim=-1)  # (1, F, N) complex
    total_frames = specs.shape[-1]
    usable = (total_frames // args.frames_per_chunk) * args.frames_per_chunk
    specs = specs[..., :usable]

    nband = model.sep_model.nband
    hidden = 2 * model.sep_model.feature_dim
    layer_count = len(model.sep_model.separator.separation)
    zero_states = [
        (torch.zeros(1, nband, hidden), torch.zeros(1, nband, hidden))
        for _ in range(layer_count)
    ]

    def run_torch_chunk(spec_chunk, states):
        with torch.inference_mode():
            features, mixture = condition_features(model, spec_chunk, conditioning)
            separated, new_states = separator_chunk(
                model.sep_model.separator, features, states
            )
            estimated = mask_frames(model, separated, mixture)
        return estimated, new_states

    def run_onnx_chunk(spec_chunk, states):
        spec_ri = torch.stack([spec_chunk.real, spec_chunk.imag], dim=1).numpy()
        feed = {
            "spec_ri": spec_ri.astype(np.float32),
            "enroll_tfmap": conditioning["tfmap"].numpy().astype(np.float32),
            "enroll_context": conditioning["context"].numpy().astype(np.float32),
        }
        for index, (h, c) in enumerate(states, start=1):
            feed[f"state_{index}_h"] = h.numpy().astype(np.float32)
            feed[f"state_{index}_c"] = c.numpy().astype(np.float32)
        results = session.run(output_names, feed)
        est_ri = torch.from_numpy(results[0])
        new_states = [
            (
                torch.from_numpy(results[1 + 2 * i]),
                torch.from_numpy(results[2 + 2 * i]),
            )
            for i in range(layer_count)
        ]
        return est_ri, new_states

    chunks = [
        specs[..., offset : offset + args.frames_per_chunk]
        for offset in range(0, usable, args.frames_per_chunk)
    ]

    # ---- 3. single chunk ----
    est_ref, states_ref = run_torch_chunk(chunks[0], zero_states)
    est_onnx, states_onnx = run_onnx_chunk(chunks[0], zero_states)
    ref_ri = torch.stack([est_ref.real, est_ref.imag], dim=1)
    single = {
        "max_abs_error": float((est_onnx - ref_ri).abs().max()),
        "mean_abs_error": float((est_onnx - ref_ri).abs().mean()),
        "relative_error": relative_error(
            (est_onnx - ref_ri).numpy(), ref_ri.numpy()
        ),
        "shape_reference": list(ref_ri.shape),
        "shape_onnx": list(est_onnx.shape),
    }

    # ---- 4. stateful streaming over N chunks ----
    torch_states = [
        (h.clone(), c.clone()) for h, c in zero_states
    ]
    onnx_states = [
        (h.clone(), c.clone()) for h, c in zero_states
    ]
    per_chunk_max = []
    diff_sum = 0.0
    count = 0
    total_elements = 0
    final_ref = final_onnx = None
    for index, chunk in enumerate(chunks[: args.chunks]):
        est_ref, torch_states = run_torch_chunk(chunk, torch_states)
        est_onnx, onnx_states = run_onnx_chunk(chunk, onnx_states)
        ref_ri = torch.stack([est_ref.real, est_ref.imag], dim=1)
        diff = (est_onnx - ref_ri).abs()
        per_chunk_max.append(float(diff.max()))
        diff_sum += float(diff.sum())
        count += diff.numel()
        total_elements += diff.numel()
        final_ref, final_onnx = ref_ri, est_onnx
    stream_max_abs = max(per_chunk_max)
    state_errors = []
    for layer, ((h_ref, c_ref), (h_onnx, c_onnx)) in enumerate(
        zip(torch_states, onnx_states), start=1
    ):
        state_errors.append(
            {
                "layer": layer,
                "h_max_abs": float((h_onnx - h_ref).abs().max()),
                "c_max_abs": float((c_onnx - c_ref).abs().max()),
            }
        )
    streaming = {
        "chunks": min(args.chunks, len(chunks)),
        "frames_per_chunk": args.frames_per_chunk,
        "max_abs_error": stream_max_abs,
        "mean_abs_error": diff_sum / count,
        "relative_error": relative_error(
            (final_onnx - final_ref).numpy(), final_ref.numpy()
        ),
        "first_chunk_max_abs": per_chunk_max[0],
        "last_chunk_max_abs": per_chunk_max[-1],
        "final_state_errors": state_errors,
    }

    gate_limit = 1e-3
    state_limit = 1e-3
    verdict_pass = (
        streaming["max_abs_error"] <= gate_limit
        and max(s["h_max_abs"] for s in state_errors) <= state_limit
        and max(s["c_max_abs"] for s in state_errors) <= state_limit
    )

    args.result.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "micforyou/onnx-correctness/1",
        "onnx_sha256": sha256(args.onnx),
        "checkpoint_sha256": sha256(args.model_dir / "avg_model.pt"),
        "onnx_inputs": sorted(input_names),
        "onnx_outputs": output_names,
        "single_chunk": single,
        "streaming_100": streaming,
        "gate": {
            "est_max_abs_limit": gate_limit,
            "state_max_abs_limit": state_limit,
            "verdict": "PASS" if verdict_pass else "FAIL",
        },
    }
    args.result.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"single chunk: max_abs={single['max_abs_error']:.3e} "
          f"rel={single['relative_error']:.3e}")
    print(f"streaming {streaming['chunks']} chunks: max_abs={streaming['max_abs_error']:.3e} "
          f"first={streaming['first_chunk_max_abs']:.3e} last={streaming['last_chunk_max_abs']:.3e}")
    print(f"final states: h_max={max(s['h_max_abs'] for s in state_errors):.3e} "
          f"c_max={max(s['c_max_abs'] for s in state_errors):.3e}")
    print(f"verdict: {report['gate']['verdict']}")


if __name__ == "__main__":
    main()
