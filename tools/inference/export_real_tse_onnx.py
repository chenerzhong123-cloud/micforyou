"""Export the stateful REAL-TSE TSE core to FP32 ONNX (Spec Phase R1).

Exports only the neural inference core, exactly as requested:

    current STFT chunk (re/im) + enrollment conditioning + 6x LSTM h/c state
        -> StatefulTSECore
        -> estimated chunk (re/im) + new 6x LSTM h/c state

Streaming STFT / OLA / resamplers stay in the existing Python implementation.
Complex arithmetic is decomposed to real/imag at the wrapper boundary because
ONNX has no complex dtype; the math mirrors BandMasker.forward exactly.
Recurrent state is explicit: no state reset between chunks.

Run with the model runtime environment:

    "$MFY_RUNTIME/bin/python" tools/inference/export_real_tse_onnx.py \
      --repo local-models/wesep-real-tse \
      --model-dir local-models/wesep-real-tse/pretrained/tfmap_context_causal_100 \
      --enrollment private-audio/enrollment_b.wav \
      --output handoff/real_tse_core_fp32.onnx \
      --report "$MFY_DATA/reports/onnx-export.json"
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import torch
import torchaudio
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


class StatefulTSECore(nn.Module):
    """Real-arithmetic, stateful chunk core of the causal REAL-TSE model.

    Mirrors condition_features + separator_chunk + mask_frames from
    tools/inference/probe_real_tse_stateful.py with two documented differences:
    complex values cross the boundary as re/im pairs, and BandMasker's mix
    bands are sliced from re/im instead of a complex tensor. Module weights
    are shared with the original model, not copied.
    """

    def __init__(self, model: nn.Module):
        super().__init__()
        self.sep_model = model.sep_model
        self.spk_ft = model.spk_ft
        self.spk_configs = model.spk_configs
        self.nband = model.sep_model.nband
        self.feature_dim = model.sep_model.feature_dim
        self.layers = model.sep_model.separator.separation
        self.band_widths = list(model.sep_model.band_split.band_width)
        self.mask_layers = model.sep_model.band_masker.mask
        self.nspk = model.sep_model.band_masker.nspk

    def forward(
        self,
        spec_ri: torch.Tensor,
        enroll_tfmap: torch.Tensor,
        enroll_context: torch.Tensor,
        *states: torch.Tensor,
    ) -> tuple[torch.Tensor, ...]:
        # spec_ri: (B, 2, F, T); states: state_1_h, state_1_c, ... state_6_h, state_6_c
        mix_real, mix_imag = spec_ri[:, 0], spec_ri[:, 1]
        mix_mag = torch.sqrt(mix_real * mix_real + mix_imag * mix_imag)

        # C2. TF-map feature (pure real ops inside the module).
        tf_map = self.spk_ft.tfmap.compute(enroll_tfmap, mix_mag)
        spec_ri3 = self.spk_ft.tfmap.post(spec_ri, tf_map.unsqueeze(1))

        subband_spec = self.sep_model.band_split(spec_ri3)
        features = self.sep_model.subband_norm(subband_spec)

        # C3. Context feature fusion (attention + multiply).
        features = self.spk_ft.context.post(features, enroll_context)

        # S4. Separator with explicit per-layer band-RNN state.
        batch = features.shape[0]
        frames = features.shape[-1]
        value = features.view(batch, self.nband * self.feature_dim, frames)
        new_states: list[torch.Tensor] = []
        for index, layer in enumerate(self.layers):
            state_h, state_c = states[2 * index], states[2 * index + 1]
            band_input = value.view(
                batch * self.nband, self.feature_dim, frames
            )
            normalized = layer.band_rnn.norm(band_input).transpose(1, 2).contiguous()
            recurrent, (h_new, c_new) = layer.band_rnn.rnn(
                normalized, (state_h, state_c)
            )
            projected = layer.band_rnn.proj(
                recurrent.reshape(-1, recurrent.shape[2])
            ).view(band_input.shape[0], band_input.shape[2], band_input.shape[1])
            band_output = (
                band_input + projected.transpose(1, 2).contiguous()
            ).view(batch, self.nband, self.feature_dim, frames)

            frequency_input = (
                band_output.permute(0, 3, 2, 1).contiguous().view(
                    batch * frames, self.feature_dim, self.nband
                )
            )
            frequency_output = layer.band_comm(frequency_input)
            value = (
                frequency_output.view(batch, frames, self.feature_dim, self.nband)
                .permute(0, 3, 2, 1)
                .contiguous()
                .view(batch, self.nband * self.feature_dim, frames)
            )
            new_states.extend([h_new, c_new])
        separated = value.view(batch, self.nband, self.feature_dim, frames)

        # S5. Complex mask applied to re/im mix bands (mirrors BandMasker.forward).
        est_real_parts = []
        est_imag_parts = []
        index = 0
        for band_index, mask_func in enumerate(self.mask_layers):
            width = self.band_widths[band_index]
            this_output = mask_func(separated[:, band_index])
            size, _, time = this_output.shape
            this_output = this_output.view(size, self.nspk, 2, 2, width, time)
            this_mask = this_output[:, :, 0] * torch.sigmoid(this_output[:, :, 1])
            mask_real = this_mask[:, :, 0]
            mask_imag = this_mask[:, :, 1]
            band_real = mix_real[:, index : index + width].unsqueeze(1)
            band_imag = mix_imag[:, index : index + width].unsqueeze(1)
            est_real_parts.append(band_real * mask_real - band_imag * mask_imag)
            est_imag_parts.append(band_real * mask_imag + band_imag * mask_real)
            index += width
        est_real = torch.cat(est_real_parts, dim=2)
        est_imag = torch.cat(est_imag_parts, dim=2)
        est_ri = torch.stack([est_real, est_imag], dim=1)  # (B, 2, S, F, T)
        return (est_ri, *new_states)


def build_example_inputs(model, conditioning, frames: int):
    frequency = model.sep_model.win // 2 + 1
    nband = model.sep_model.nband
    hidden = 2 * model.sep_model.feature_dim
    spec_ri = torch.randn(1, 2, frequency, frames) * 0.01
    states = []
    for _ in range(len(model.sep_model.separator.separation)):
        states.append(torch.zeros(1, nband, hidden))
        states.append(torch.zeros(1, nband, hidden))
    return (spec_ri, conditioning["tfmap"], conditioning["context"], *states)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--enrollment", type=Path, required=True)
    parser.add_argument("--enrollment-seconds", type=float, default=6.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument(
        "--static-frames",
        type=int,
        default=None,
        help="export with a fixed frames-per-chunk shape (no dynamic axes)",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(args.repo))
    import wesep  # noqa: PLC0415

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from probe_real_tse_stateful import precompute_conditioning

    torch.manual_seed(20260918)
    extractor = wesep.load_model_local(str(args.model_dir))
    model = extractor.model.eval()

    enrollment, enrollment_rate = torchaudio.load(args.enrollment)
    if enrollment.shape[0] > 1:
        enrollment = enrollment.mean(dim=0, keepdim=True)
    from micforyou.runtime import prepare_enrollment_reference

    reference = prepare_enrollment_reference(
        enrollment, enrollment_rate, args.enrollment_seconds, int(extractor.resample_rate))
    enrollment, enrollment_selection = reference.selected, reference.selection
    with torch.inference_mode():
        conditioning = precompute_conditioning(model, enrollment)

    wrapper = StatefulTSECore(model).eval()

    # --- torch-level parity self-check before export ---
    frames = 8
    example = build_example_inputs(model, conditioning, frames)
    frequency = model.sep_model.win // 2 + 1
    spec_complex = torch.complex(example[0][:, 0], example[0][:, 1])

    from probe_real_tse_stateful import (
        condition_features,
        mask_frames,
        separator_chunk,
    )

    zero_state = torch.zeros(1, model.sep_model.nband, 2 * model.sep_model.feature_dim)
    zero_states = [
        (zero_state.clone(), zero_state.clone())
        for _ in model.sep_model.separator.separation
    ]
    with torch.inference_mode():
        features, mixture = condition_features(model, spec_complex, conditioning)
        separated, new_states_ref = separator_chunk(
            model.sep_model.separator, features, zero_states
        )
        estimated_ref = mask_frames(model, separated, mixture)
        outputs = wrapper(*example)
    est_ref = torch.stack([estimated_ref.real, estimated_ref.imag], dim=1)
    core_max = (outputs[0] - est_ref).abs().max().item()
    state_max = max(
        (a - b).abs().max().item()
        for a, b in zip(outputs[1:], [s for pair in new_states_ref for s in pair])
    )
    print(f"torch self-check: est max_abs={core_max:.3e} state max_abs={state_max:.3e}")
    # state diff is bounded rounding spread from sqrt(re^2+im^2) in the wrapper
    # versus std::abs(complex) (hypot) in the reference; harmless at this scale.
    if core_max > 1e-5 or state_max > 1e-4:
        raise SystemExit("wrapper does not reproduce the torch streaming path")

    # --- export ---
    state_count = len(model.sep_model.separator.separation)
    input_names = ["spec_ri", "enroll_tfmap", "enroll_context"]
    for i in range(1, state_count + 1):
        input_names += [f"state_{i}_h", f"state_{i}_c"]
    output_names = ["est_ri"]
    for i in range(1, state_count + 1):
        output_names += [f"state_{i}_h_out", f"state_{i}_c_out"]
    if args.static_frames is not None:
        dynamic_axes = None
        frames = args.static_frames
        example = build_example_inputs(model, conditioning, frames)
    else:
        dynamic_axes = {
            "spec_ri": {3: "frames"},
            "est_ri": {4: "frames"},
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with torch.inference_mode():
        torch.onnx.export(
            wrapper,
            example,
            str(args.output),
            opset_version=args.opset,
            do_constant_folding=True,
            input_names=input_names,
            output_names=output_names,
            dynamic_axes=dynamic_axes,
        )

    import onnx

    onnx_model = onnx.load(str(args.output))
    onnx.checker.check_model(onnx_model)
    graph = onnx_model.graph
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()

    report = {
        "schema": "micforyou/onnx-export-report/1",
        "checkpoint_sha256": hashlib.sha256(
            (args.model_dir / "avg_model.pt").read_bytes()
        ).hexdigest(),
        "enrollment": "<local-private-audio>",
        "enrollment_selection": enrollment_selection,
        "opset": args.opset,
        "onnx_checker": "PASS",
        "onnx_file": args.output.name,
        "onnx_sha256": digest,
        "onnx_size_bytes": args.output.stat().st_size,
        "core": "StatefulTSECore",
        "inputs": {
            "spec_ri": [1, 2, frequency, "frames"],
            "enroll_tfmap": list(conditioning["tfmap"].shape),
            "enroll_context": list(conditioning["context"].shape),
            "states": [
                f"{name}: [1, {model.sep_model.nband}, {2 * model.sep_model.feature_dim}]"
                for name in input_names[3:]
            ],
        },
        "outputs": {
            "est_ri": [1, 2, 1, frequency, "frames"],
            "states": [f"{name}_out" for name in input_names[3:]],
        },
        "state_contract": "explicit h/c per band-RNN layer; no reset between chunks",
        "static_frames": args.static_frames,
        "torch_parity": {
            "est_max_abs": core_max,
            "state_max_abs": state_max,
        },
        "graph_nodes": len(graph.node),
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"export ok: {args.output} ({report['onnx_size_bytes']} bytes, "
          f"{len(graph.node)} nodes)")
    print(f"report: {args.report}")


if __name__ == "__main__":
    main()
