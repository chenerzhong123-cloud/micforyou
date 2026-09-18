"""ONNX Runtime benchmark for the stateful REAL-TSE core.

Mirrors experiments/benchmark_real_tse.py exactly -- same deterministic
synthetic input, same 48k -> 16k -> TSE -> 16k -> 48k path, same streaming
STFT/OLA, same warmup + measured pass and integrity checks -- with one
difference: the neural core runs in an ONNX Runtime CPU session instead of
PyTorch. Correctness must already be PASS (see compare_torch_onnx.py).

CPU mode supports the original auto/1/2/4 × 8/16/24 matrix. CoreML mode
uses a static-shape model and preserves each requested thread setting for the
CPU fallback path; never label an explicitly configured session as ``auto``.

    .venv-official/bin/python experiments/benchmark_onnx_tse.py \
      --repo local-models/wesep-real-tse \
      --model-dir .../tfmap_context_causal_100 \
      --enrollment private-audio/enrollment_b.wav \
      --onnx handoff/real_tse_core_fp32.onnx \
      --torch-baseline handoff/mac-b-thread-1-10s.json \
      --result handoff/mac-b-onnx-cpu-benchmark.json
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

from micforyou.reporting import collect_system_info
from micforyou.runtime import ort_thread_settings
from micforyou.synth import DEFAULT_SEED, synthetic_blocks

from probe_real_tse_stateful import (
    StreamingOLA,
    StreamingSTFT,
    precompute_conditioning,
    sha256,
)


class OnnxTseStream:
    """Streaming wrapper calling the exported stateful ONNX core."""

    def __init__(self, session, conditioning, frames_per_chunk, layer_count):
        self.session = session
        self.frames_per_chunk = frames_per_chunk
        self.layer_count = layer_count
        self.stft = StreamingSTFT(512, 128, torch.device("cpu"))
        self.ola = StreamingOLA(512, 128, torch.device("cpu"))
        self.pending: list[torch.Tensor] = []
        self.call_ms: list[float] = []
        self.static_feed = {
            "enroll_tfmap": conditioning["tfmap"].numpy().astype(np.float32),
            "enroll_context": conditioning["context"].numpy().astype(np.float32),
        }
        nband = 32
        hidden = 256
        zeros = np.zeros((1, nband, hidden), dtype=np.float32)
        self.states = [
            (zeros.copy(), zeros.copy()) for _ in range(layer_count)
        ]

    def _run_core(self, spec):
        feed = dict(self.static_feed)
        feed["spec_ri"] = torch.stack([spec.real, spec.imag], dim=1).numpy().astype(
            np.float32
        )
        for index, (h, c) in enumerate(self.states, start=1):
            feed[f"state_{index}_h"] = h
            feed[f"state_{index}_c"] = c
        results = self.session.run(None, feed)
        self.states = [
            (results[1 + 2 * i], results[2 + 2 * i])
            for i in range(self.layer_count)
        ]
        est = torch.from_numpy(results[0])
        return torch.complex(est[:, 0, 0], est[:, 1, 0])

    def _process(self, force: bool = False):
        outputs = []
        if force and self.pending:
            # static-shape session: pad the final partial chunk with silence
            while len(self.pending) < self.frames_per_chunk:
                self.pending.append(torch.zeros(1, 257, 1))
        while len(self.pending) >= self.frames_per_chunk or (force and self.pending):
            count = min(self.frames_per_chunk, len(self.pending))
            spec = torch.cat(self.pending[:count], dim=-1)
            self.pending = self.pending[count:]
            started = time.perf_counter()
            estimated = self._run_core(spec)
            outputs.extend(self.ola.push(estimated))
            self.call_ms.append((time.perf_counter() - started) * 1000)
        return outputs

    def feed(self, samples: np.ndarray) -> np.ndarray:
        self.pending.extend(self.stft.push(torch.from_numpy(samples)))
        outputs = self._process()
        if not outputs:
            return np.empty(0, dtype=np.float32)
        return torch.cat(outputs, dim=-1).reshape(-1).numpy()

    def flush(self) -> np.ndarray:
        self.pending.extend(self.stft.flush())
        outputs = self._process(force=True)
        outputs.extend(self.ola.flush())
        if not outputs:
            return np.empty(0, dtype=np.float32)
        return torch.cat(outputs, dim=-1).reshape(-1).numpy()


def make_onnx_transform(stream: OnnxTseStream, sample_rate: int = 48_000):
    import soxr

    down = soxr.ResampleStream(sample_rate, 16_000, 1, dtype="float32", quality="HQ")
    up = soxr.ResampleStream(16_000, sample_rate, 1, dtype="float32", quality="HQ")

    def transform(block: np.ndarray) -> np.ndarray:
        low = down.resample_chunk(block, last=False)
        if not len(low):
            return np.empty(0, dtype=np.float32)
        enhanced = stream.feed(low)
        if not len(enhanced):
            return np.empty(0, dtype=np.float32)
        return up.resample_chunk(enhanced, last=False)

    def flush_transform() -> np.ndarray:
        pieces = []
        low_tail = down.resample_chunk(np.empty(0, dtype=np.float32), last=True)
        if len(low_tail):
            middle = stream.feed(low_tail)
            if len(middle):
                pieces.append(up.resample_chunk(middle, last=False))
        tail = stream.flush()
        if len(tail):
            pieces.append(up.resample_chunk(tail, last=False))
        pieces.append(up.resample_chunk(np.empty(0, dtype=np.float32), last=True))
        return np.concatenate(pieces) if len(pieces) else np.empty(0, dtype=np.float32)

    return transform, flush_transform


def run_candidate(session, conditioning, frames, input_audio, audio_block, layer_count):
    def build():
        stream = OnnxTseStream(session, conditioning, frames, layer_count)
        return stream, *make_onnx_transform(stream)

    warmup_frames = min(len(input_audio), 48_000 * 3)
    warmup_stream, warmup_transform, warmup_flush = build()
    started = time.perf_counter()
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
        for offset in range(0, len(input_audio), audio_block):
            outputs.append(transform(input_audio[offset : offset + audio_block]))
        outputs.append(flush())
    except Exception as failure:
        error = repr(failure)
    processing_seconds = time.perf_counter() - started

    output = (
        np.concatenate([part for part in outputs if len(part)])
        if error is None
        else np.zeros(0, dtype=np.float32)
    )
    raw_output_samples = len(output)
    # zero-padded final chunk yields a few extra samples; trim to the input
    # length so the integrity check matches the dynamic-shape contract
    if error is None and len(output) >= len(input_audio):
        output = output[: len(input_audio)]
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
        "raw_output_samples": raw_output_samples,
        "length_match": len(output) == len(input_audio),
        "nonfinite_samples": int((~np.isfinite(output)).sum()) if error is None else -1,
        "output_peak": float(np.abs(output).max()) if len(output) else 0.0,
        "output_rms": (
            float(np.sqrt(np.mean(np.square(output, dtype=np.float64))))
            if len(output)
            else 0.0
        ),
        "first_inference_ms": float(calls[0]) if len(calls) else None,
        "error": error,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--enrollment", type=Path, required=True)
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--torch-baseline", type=Path, default=None,
                        help="thread-sweep JSON for speedup reference")
    parser.add_argument("--audio-seconds", type=float, default=10.0)
    parser.add_argument("--frames", type=int, nargs="+", default=[8, 16, 24])
    parser.add_argument("--threads", type=int, nargs="+", default=[0, 1, 2, 4],
                        help="0 means ORT default (auto)")
    parser.add_argument("--audio-block", type=int, default=480)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--tir-db", type=float, default=-6.0)
    parser.add_argument(
        "--provider",
        choices=["cpu", "coreml"],
        default="cpu",
        help="coreml puts CoreMLExecutionProvider first (requires static shapes)",
    )
    parser.add_argument(
        "--session-log",
        type=Path,
        default=None,
        help="capture ORT stderr (partitioning/compute-plan evidence) here",
    )
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    import onnxruntime as ort

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
    layer_count = len(model.sep_model.separator.separation)

    total_frames = int(round(args.audio_seconds * 48_000))
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

    baseline = {}
    if args.torch_baseline and args.torch_baseline.exists():
        base_data = json.loads(args.torch_baseline.read_text())
        for candidate in base_data.get("candidates", []):
            baseline[candidate["frames_per_chunk"]] = {
                "rtf": candidate["processing_rtf"],
                "p95": candidate["model_call_ms_p95"],
            }

    def capture_stderr(target: Path):
        import os

        class Capture:
            def __enter__(self):
                self.saved = os.dup(2)
                self.fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
                os.dup2(self.fd, 2)
                return self

            def __exit__(self, *exc):
                os.dup2(self.saved, 2)
                os.close(self.saved)
                os.close(self.fd)

        return Capture()

    def build_session(provider: str, thread_setting, drop_diagnostics: bool):
        options = ort.SessionOptions()
        if thread_setting.intra_op_num_threads is not None:
            options.intra_op_num_threads = thread_setting.intra_op_num_threads
            options.inter_op_num_threads = thread_setting.inter_op_num_threads
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if provider == "coreml":
            options.log_severity_level = 0  # verbose: partitioning evidence
            coreml_options = {
                "ModelFormat": "MLProgram",
                "MLComputeUnits": "ALL",
                "RequireStaticInputShapes": "1",
            }
            if not drop_diagnostics:
                coreml_options["ProfileComputePlan"] = "1"
            providers = [
                ("CoreMLExecutionProvider", coreml_options),
                "CPUExecutionProvider",
            ]
        else:
            providers = ["CPUExecutionProvider"]
        log_base = args.session_log or args.result.with_name(
            args.result.stem + "-session.log"
        )
        log_target = log_base.with_name(
            f"{log_base.stem}-threads-{thread_setting.label}{log_base.suffix}"
        )
        started = time.perf_counter()
        with capture_stderr(log_target):
            session = ort.InferenceSession(
                str(args.onnx), sess_options=options, providers=providers
            )
        creation_seconds = time.perf_counter() - started
        return session, {
            "providers_registered": session.get_providers(),
            "session_create_seconds": creation_seconds,
            "stderr_log": log_target.name,
            "requested_intra_op_threads": thread_setting.label,
        }

    candidates = []
    creation_info = None
    for thread_setting in ort_thread_settings(args.threads):
        if args.provider == "coreml":
            try:
                session, creation_info = build_session(
                    "coreml", thread_setting, drop_diagnostics=False
                )
            except Exception as failure:
                print(f"CoreML EP with diagnostic options failed: {failure!r}")
                print("retrying without ProfileComputePlan ...")
                session, creation_info = build_session(
                    "coreml", thread_setting, drop_diagnostics=True
                )
                creation_info["dropped_options"] = ["ProfileComputePlan"]
        else:
            session, creation_info = build_session(
                "cpu", thread_setting, drop_diagnostics=True
            )
        label = thread_setting.label
        print(f"providers registered: {creation_info['providers_registered']}")
        print(
            f"session create/compile [{label} threads]: "
            f"{creation_info['session_create_seconds']:.2f}s"
        )
        for frames in args.frames:
            result = run_candidate(
                session, conditioning, frames, input_audio, args.audio_block,
                layer_count,
            )
            base = baseline.get(frames)
            result.update(
                {
                    "runtime": (
                        "onnxruntime-coreml-ep"
                        if args.provider == "coreml"
                        else "onnxruntime-cpu"
                    ),
                    "intra_op_threads": label,
                    "requested_intra_op_threads": creation_info[
                        "requested_intra_op_threads"
                    ],
                    "providers_registered": creation_info["providers_registered"],
                    "session_create_seconds": creation_info["session_create_seconds"],
                    "speedup_rtf_vs_torch_1t": (
                        base["rtf"] / result["processing_rtf"]
                        if base and result["processing_rtf"] > 0
                        else None
                    ),
                }
            )
            candidates.append(result)
            print(
                f"{result['runtime']}[{label}t] {frames}f: RTF {result['processing_rtf']:.3f} "
                f"p95 {result['model_call_ms_p95']:.1f} ms "
                f"speedup {result['speedup_rtf_vs_torch_1t'] and round(result['speedup_rtf_vs_torch_1t'], 2)}"
            )

    valid = [c for c in candidates if c["error"] is None and c["length_match"]
             and c["nonfinite_samples"] == 0]
    best = min(valid, key=lambda c: c["processing_rtf"]) if valid else None
    if best is not None:
        if best["processing_rtf"] <= 0.80:
            gate = f"{args.provider.upper()}: SUCCESS (RTF <= 0.80)"
        elif best["processing_rtf"] <= 1.00:
            gate = f"{args.provider.upper()}: MARGINAL (0.80 < RTF <= 1.00)"
        else:
            speedups = [c["speedup_rtf_vs_torch_1t"] for c in valid]
            measured_speedups = [s for s in speedups if s is not None]
            top = max(measured_speedups) if measured_speedups else None
            gate = (
                f"{args.provider.upper()}: FAIL (best RTF > 1.00); "
                + (
                    (
                        f"max speedup {top:.2f}x "
                        + ("< 1.2x: ORT CPU helps little for this architecture"
                           if top < 1.2 else "vs PyTorch single thread")
                    )
                    if top is not None
                    else "no matching PyTorch baseline"
                )
            )
    else:
        gate = f"{args.provider.upper()}: FAIL (no valid candidate)"

    args.result.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "micforyou/onnx-cpu-benchmark/1",
        "system": collect_system_info({"torch": torch.__version__}),
        "onnx_sha256": sha256(args.onnx),
        "checkpoint_sha256": sha256(args.model_dir / "avg_model.pt"),
        "provider": (
            "CoreMLExecutionProvider+CPUExecutionProvider"
            if args.provider == "coreml"
            else "CPUExecutionProvider"
        ),
        "execution_mode": "SEQUENTIAL",
        "graph_optimization": "ALL",
        "session_info": creation_info,
        "audio_seconds": args.audio_seconds,
        "torch_baseline_source": args.torch_baseline.name if args.torch_baseline else None,
        "candidates": candidates,
        "best": {
            "intra_op_threads": best["intra_op_threads"],
            "frames_per_chunk": best["frames_per_chunk"],
            "rtf": best["processing_rtf"],
            "p95_ms": best["model_call_ms_p95"],
        }
        if best
        else None,
        "gate": gate,
    }
    args.result.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"gate: {gate}")
    print(f"result json: {args.result}")
    if args.provider == "coreml":
        # CoreML EP teardown can crash at process exit (recursive_mutex) after
        # all results are safely written; skip interpreter shutdown.
        import os

        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    main()
