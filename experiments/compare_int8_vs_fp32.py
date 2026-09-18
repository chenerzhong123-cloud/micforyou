"""Branch A correctness gate: INT8 dynamic-quantized core vs FP32 ORT core.

Boundary identical to compare_torch_onnx.py / the project benchmarks: real
checkpoint, real enrollment conditioning (precomputed once via wesep), the
same deterministic waveform and streaming STFT framing. Both sessions run the
same 100-chunk stream with all 12 recurrent states handed chunk to chunk.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import onnxruntime as ort
import torch
import torchaudio


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--enrollment", type=Path, required=True)
    parser.add_argument("--fp32", type=Path, required=True)
    parser.add_argument("--int8", type=Path, required=True)
    parser.add_argument("--frames-per-chunk", type=int, default=8)
    parser.add_argument("--chunks", type=int, default=100)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(args.repo))
    import wesep  # noqa: PLC0415

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from probe_real_tse_stateful import (
        StreamingSTFT,
        precompute_conditioning,
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

    sessions = {
        label: ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        for label, path in (("fp32", args.fp32), ("int8", args.int8))
    }

    # deterministic waveform identical in spirit to the FP32 gate
    sample_rate = int(extractor.resample_rate)
    samples_needed = args.frames_per_chunk * 128 * (args.chunks + 2)
    waveform = torch.randn(1, samples_needed) * 0.05

    streamer = StreamingSTFT(model.sep_model.win, model.sep_model.stride, torch.device("cpu"))
    frame_list = []
    block = sample_rate // 100
    with torch.inference_mode():
        for offset in range(0, waveform.shape[1], block):
            frame_list.extend(streamer.push(waveform[:, offset : offset + block]))
    specs = torch.cat(frame_list, dim=-1)
    usable = (specs.shape[-1] // args.frames_per_chunk) * args.frames_per_chunk
    required = args.chunks * args.frames_per_chunk
    if usable < required:
        raise SystemExit(
            f"stream produced {usable} usable frames; {required} are required"
        )

    static_feed = {
        "enroll_tfmap": conditioning["tfmap"].numpy().astype(np.float32),
        "enroll_context": conditioning["context"].numpy().astype(np.float32),
    }
    nband = model.sep_model.nband
    hidden = 2 * model.sep_model.feature_dim
    layer_count = len(model.sep_model.separator.separation)
    zero = np.zeros((1, nband, hidden), dtype=np.float32)
    states = {
        label: [(zero.copy(), zero.copy()) for _ in range(layer_count)]
        for label in sessions
    }

    def run(label, spec_ri):
        feed = dict(static_feed)
        feed["spec_ri"] = spec_ri
        for i, (h, c) in enumerate(states[label], start=1):
            feed[f"state_{i}_h"] = h
            feed[f"state_{i}_c"] = c
        out = sessions[label].run(None, feed)
        return out[0], [(out[1 + 2 * i], out[2 + 2 * i]) for i in range(layer_count)]

    max_abs = 0.0
    diff_sq = ref_sq = 0.0
    abs_sum = elements = 0
    nonfinite_outputs = 0
    nonfinite_states = 0
    per_chunk_max = []
    for index in range(args.chunks):
        chunk_frames = specs[
            ..., index * args.frames_per_chunk : (index + 1) * args.frames_per_chunk
        ]
        spec_ri = np.stack(
            [chunk_frames.real.numpy(), chunk_frames.imag.numpy()], axis=1
        ).astype(np.float32)
        outputs = {}
        for label in sessions:
            est, states[label] = run(label, spec_ri)
            outputs[label] = est
            nonfinite_outputs += int((~np.isfinite(est)).sum())
            nonfinite_states += sum(
                int((~np.isfinite(value)).sum())
                for pair in states[label]
                for value in pair
            )
        diff = outputs["int8"] - outputs["fp32"]
        per_chunk_max.append(float(np.abs(diff).max()))
        max_abs = max(max_abs, per_chunk_max[-1])
        abs_sum += float(np.abs(diff).sum())
        elements += diff.size
        diff_sq += float((diff**2).sum())
        ref_sq += float((outputs["fp32"] ** 2).sum())
    state_diff = []
    for i in range(layer_count):
        h_f, c_f = states["fp32"][i]
        h_q, c_q = states["int8"][i]
        state_diff.append(
            {
                "layer": i + 1,
                "h_max_abs": float(np.abs(h_q - h_f).max()),
                "c_max_abs": float(np.abs(c_q - c_f).max()),
            }
        )

    relative = float(np.sqrt(diff_sq / ref_sq)) if ref_sq else 0.0
    gate_pass = (
        max_abs <= 1e-2
        and nonfinite_outputs == 0
        and nonfinite_states == 0
    )
    args.result.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "micforyou/onnx-int8-correctness/1",
        "fp32_sha256": sha256(args.fp32),
        "int8_sha256": sha256(args.int8),
        "checkpoint_sha256": sha256(args.model_dir / "avg_model.pt"),
        "enrollment_conditioning": True,
        "chunks": args.chunks,
        "frames_per_chunk": args.frames_per_chunk,
        "nonfinite_outputs": int(nonfinite_outputs),
        "nonfinite_states": int(nonfinite_states),
        "output_max_abs_error": max_abs,
        "output_mean_abs_error": abs_sum / elements,
        "output_relative_error_l2": relative,
        "first_chunk_max_abs": per_chunk_max[0],
        "last_chunk_max_abs": per_chunk_max[-1],
        "final_state_errors": state_diff,
        "gate": "PASS" if gate_pass else "FAIL",
        "gate_limit": "output max_abs <= 1e-2 and no non-finite output/state values (quantization is expected to be far coarser than the FP32 1e-3 export gate)",
    }
    args.result.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"chunks={args.chunks} max_abs={max_abs:.4e} rel_l2={relative:.4e}")
    print(
        f"first={per_chunk_max[0]:.4e} last={per_chunk_max[-1]:.4e} "
        f"nonfinite_output={nonfinite_outputs} nonfinite_state={nonfinite_states}"
    )
    print(f"final states: h_max={max(s['h_max_abs'] for s in state_diff):.4e} "
          f"c_max={max(s['c_max_abs'] for s in state_diff):.4e}")
    print(f"gate: {report['gate']}")


if __name__ == "__main__":
    main()
