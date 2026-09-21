"""Probe whether a REAL-TSE checkpoint can take one bounded MPS training step.

This is a capability smoke test, not model fine-tuning. It uses deterministic
synthetic tensors, updates the final mask projection layers in memory, and
never writes a checkpoint or audio.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
import sys
import time

import torch


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def select_device(requested: str) -> torch.device:
    if requested == "auto":
        requested = "mps" if torch.backends.mps.is_available() else "cpu"
    if requested == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("MPS was requested but is not available")
    return torch.device(requested)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--device", choices=("auto", "mps", "cpu"), default="auto")
    parser.add_argument("--mix-seconds", type=float, default=1.0)
    parser.add_argument("--enrollment-seconds", type=float, default=2.0)
    parser.add_argument("--seed", type=int, default=20260922)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    sys.path.insert(0, str(args.repo.resolve()))
    import wesep  # noqa: PLC0415

    device = select_device(args.device)
    extractor = wesep.load_model_local(str(args.model_dir.resolve()))
    model = extractor.model
    sample_rate = int(extractor.resample_rate)

    for parameter in model.parameters():
        parameter.requires_grad = False
    # Each frequency band's last 1x1 convolution projects features to a
    # complex mask. Keeping only these projections trainable bounds optimizer
    # state and reduces overfitting risk for a future small-data experiment.
    for mask_block in model.sep_model.band_masker.mask:
        for parameter in mask_block[5].parameters():
            parameter.requires_grad = True

    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    if not trainable:
        raise RuntimeError("no trainable final mask projection parameters found")

    model = model.to(device).train()
    generator = torch.Generator(device="cpu").manual_seed(args.seed)
    mix_samples = round(args.mix_seconds * sample_rate)
    enrollment_samples = round(args.enrollment_seconds * sample_rate)
    mix = torch.randn(1, 1, mix_samples, generator=generator).mul_(0.01).to(device)
    enrollment = (
        torch.randn(1, 1, enrollment_samples, generator=generator)
        .mul_(0.01)
        .to(device)
    )
    optimizer = torch.optim.AdamW(trainable, lr=1e-5)

    started = time.perf_counter()
    output = model(mix, enrollment)
    forward_seconds = time.perf_counter() - started
    loss = output.float().square().mean()

    started = time.perf_counter()
    loss.backward()
    backward_seconds = time.perf_counter() - started
    gradients_finite = all(
        parameter.grad is None or bool(torch.isfinite(parameter.grad).all().item())
        for parameter in trainable
    )
    if not gradients_finite:
        raise RuntimeError("non-finite gradient detected")
    optimizer.step()
    if device.type == "mps":
        torch.mps.synchronize()

    checkpoint = args.model_dir / "avg_model.pt"
    report = {
        "schema": "micforyou/finetune-capability-smoke/1",
        "warning": "Synthetic capability smoke only; no quality claim and no checkpoint saved.",
        "device": device.type,
        "torch_version": torch.__version__,
        "model_sha256": sha256(checkpoint),
        "sample_rate": sample_rate,
        "mix_samples": mix_samples,
        "enrollment_samples": enrollment_samples,
        "total_parameters": sum(parameter.numel() for parameter in model.parameters()),
        "trainable_parameters": sum(parameter.numel() for parameter in trainable),
        "output_shape": list(output.shape),
        "loss": float(loss.detach().cpu()),
        "gradients_finite": gradients_finite,
        "forward_seconds": forward_seconds,
        "backward_seconds": backward_seconds,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "checkpoint_saved": False,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
