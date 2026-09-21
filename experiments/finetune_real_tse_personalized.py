"""Run a bounded personalized REAL-TSE fine-tuning proof of concept.

The script keeps the source checkpoint immutable, trains only the final mask
projection convolutions, and writes a separate model directory plus a JSON
report. It never uses the private real-office held-out recordings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import sys
import time

import torch
import torchaudio


TRAIN_SPEAKERS = (84, 1462, 1673, 1919, 174, 251, 422, 652)
VALIDATION_SPEAKERS = (1988, 1993, 777, 1272)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_mono(path: Path, sample_rate: int) -> torch.Tensor:
    audio, source_rate = torchaudio.load(path)
    if audio.shape[0] > 1:
        audio = audio.mean(dim=0, keepdim=True)
    if source_rate != sample_rate:
        audio = torchaudio.functional.resample(audio, source_rate, sample_rate)
    return audio.squeeze(0).to(torch.float32)


def tile_to_length(audio: torch.Tensor, length: int) -> torch.Tensor:
    if not audio.numel():
        raise ValueError("empty audio")
    if len(audio) < length:
        audio = audio.repeat(math.ceil(length / len(audio)))
    return audio


def random_crop(
    audio: torch.Tensor, length: int, generator: random.Random
) -> torch.Tensor:
    audio = tile_to_length(audio, length)
    start = generator.randrange(len(audio) - length + 1)
    return audio[start : start + length].clone()


def energy_crop(
    audio: torch.Tensor,
    length: int,
    generator: random.Random,
    candidates: int = 16,
) -> torch.Tensor:
    audio = tile_to_length(audio, length)
    best = None
    best_energy = -1.0
    for _ in range(candidates):
        candidate = random_crop(audio, length, generator)
        energy = float(candidate.square().mean())
        if energy > best_energy:
            best = candidate
            best_energy = energy
    assert best is not None
    return best


def select_enrollment(audio: torch.Tensor, length: int) -> tuple[torch.Tensor, int]:
    audio = tile_to_length(audio, length)
    hop = max(length // 4, 1)
    starts = list(range(0, len(audio) - length + 1, hop))
    final_start = len(audio) - length
    if starts[-1] != final_start:
        starts.append(final_start)
    energies = [float(audio[start : start + length].square().mean()) for start in starts]
    index = max(range(len(starts)), key=energies.__getitem__)
    start = starts[index]
    return audio[start : start + length].clone(), start


def mix_at_tir(
    target: torch.Tensor, interferer: torch.Tensor, tir_db: float
) -> tuple[torch.Tensor, torch.Tensor]:
    target_rms = target.square().mean().sqrt().clamp_min(1e-8)
    interferer_rms = interferer.square().mean().sqrt().clamp_min(1e-8)
    desired_interferer_rms = target_rms / (10 ** (tir_db / 20))
    interferer = interferer * (desired_interferer_rms / interferer_rms)
    mixture = target + interferer
    peak = mixture.abs().max().clamp_min(1e-8)
    safety_gain = min(1.0, 0.95 / float(peak))
    return mixture * safety_gain, target * safety_gain


def si_sdr(estimate: torch.Tensor, reference: torch.Tensor) -> torch.Tensor:
    estimate = estimate - estimate.mean(dim=-1, keepdim=True)
    reference = reference - reference.mean(dim=-1, keepdim=True)
    reference_energy = reference.square().sum(dim=-1, keepdim=True).clamp_min(1e-8)
    projection = (
        (estimate * reference).sum(dim=-1, keepdim=True) * reference / reference_energy
    )
    noise = estimate - projection
    ratio = projection.square().sum(dim=-1) / noise.square().sum(dim=-1).clamp_min(
        1e-8
    )
    return 10 * torch.log10(ratio.clamp_min(1e-8))


def find_speaker_audio(root: Path, speaker_ids: tuple[int, ...]) -> dict[int, list[Path]]:
    result: dict[int, list[Path]] = {}
    for speaker_id in speaker_ids:
        files = sorted((root / str(speaker_id)).glob("*/*.flac"))
        if not files:
            raise FileNotFoundError(f"no LibriSpeech files for speaker {speaker_id}")
        result[speaker_id] = files
    return result


def freeze_final_mask_projections(model: torch.nn.Module) -> list[torch.nn.Parameter]:
    for parameter in model.parameters():
        parameter.requires_grad = False
    for mask_block in model.sep_model.band_masker.mask:
        for parameter in mask_block[5].parameters():
            parameter.requires_grad = True
    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    if not trainable:
        raise RuntimeError("no final mask projection parameters found")
    return trainable


def evaluate(
    model: torch.nn.Module,
    enrollment: torch.Tensor,
    target_files: list[Path],
    interferers: dict[int, list[Path]],
    sample_rate: int,
    crop_samples: int,
    device: torch.device,
    seed: int,
) -> dict[str, object]:
    model.eval()
    generator = random.Random(seed)
    cases: list[dict[str, object]] = []
    speaker_ids = list(interferers)
    with torch.inference_mode():
        for index, target_file in enumerate(target_files):
            target_audio = load_mono(target_file, sample_rate)
            target = energy_crop(target_audio, crop_samples, generator)
            for tir_db in (0.0, -6.0):
                speaker_id = speaker_ids[(index * 2 + int(abs(tir_db) // 6)) % len(speaker_ids)]
                source = interferers[speaker_id][0]
                interferer = random_crop(
                    load_mono(source, sample_rate), crop_samples, generator
                )
                mixture, reference = mix_at_tir(target, interferer, tir_db)
                output = model(
                    mixture[None, None].to(device), enrollment[None, None]
                ).squeeze(0).squeeze(0)
                output_cpu = output.cpu()
                cases.append(
                    {
                        "kind": "target_present",
                        "target_file": target_file.name,
                        "interferer_speaker": speaker_id,
                        "tir_db": tir_db,
                        "mixture_si_sdr": float(si_sdr(mixture[None], reference[None])),
                        "output_si_sdr": float(si_sdr(output_cpu[None], reference[None])),
                    }
                )
        for speaker_id in speaker_ids[:2]:
            source = interferers[speaker_id][1]
            mixture = random_crop(load_mono(source, sample_rate), crop_samples, generator)
            output = model(
                mixture[None, None].to(device), enrollment[None, None]
            ).squeeze(0).squeeze(0)
            attenuation = 10 * torch.log10(
                output.float().square().mean().cpu().clamp_min(1e-12)
                / mixture.square().mean().clamp_min(1e-12)
            )
            cases.append(
                {
                    "kind": "target_absent",
                    "interferer_speaker": speaker_id,
                    "attenuation_db": float(attenuation),
                }
            )
    present = [case for case in cases if case["kind"] == "target_present"]
    absent = [case for case in cases if case["kind"] == "target_absent"]
    return {
        "cases": cases,
        "mean_output_si_sdr": sum(float(case["output_si_sdr"]) for case in present)
        / len(present),
        "mean_si_sdri": sum(
            float(case["output_si_sdr"]) - float(case["mixture_si_sdr"])
            for case in present
        )
        / len(present),
        "mean_target_absent_attenuation_db": sum(
            float(case["attenuation_db"]) for case in absent
        )
        / len(absent),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--train-target-dir", type=Path, required=True)
    parser.add_argument("--validation-target-dir", type=Path, required=True)
    parser.add_argument("--librispeech-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--crop-seconds", type=float, default=1.0)
    parser.add_argument("--enrollment-seconds", type=float, default=6.0)
    parser.add_argument("--learning-rate", type=float, default=1e-6)
    parser.add_argument("--proximity-weight", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=20260922)
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(f"output directory is not empty: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.repo.resolve()))
    import wesep  # noqa: PLC0415

    if args.device == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("MPS is not available")
    device = torch.device(args.device)
    checkpoint = args.model_dir / "avg_model.pt"
    source_checkpoint_sha256 = sha256(checkpoint)
    extractor = wesep.load_model_local(str(args.model_dir))
    model = extractor.model
    sample_rate = int(extractor.resample_rate)
    crop_samples = round(args.crop_seconds * sample_rate)
    enrollment_samples = round(args.enrollment_seconds * sample_rate)
    trainable = freeze_final_mask_projections(model)
    model = model.to(device)
    initial_trainable = [parameter.detach().clone() for parameter in trainable]
    initial_trainable_energy = sum(
        parameter.float().square().sum() for parameter in initial_trainable
    ).clamp_min(1e-12)

    train_enrollment_audio = load_mono(
        args.train_target_dir / "enrollment_b.wav", sample_rate
    )
    train_enrollment, train_enrollment_start = select_enrollment(
        train_enrollment_audio, enrollment_samples
    )
    validation_enrollment_audio = load_mono(
        args.validation_target_dir / "enrollment_b.wav", sample_rate
    )
    validation_enrollment, validation_enrollment_start = select_enrollment(
        validation_enrollment_audio, enrollment_samples
    )
    train_enrollment = train_enrollment.to(device)
    validation_enrollment = validation_enrollment.to(device)

    train_target_files = [
        args.train_target_dir / "test_normal_b.wav",
        args.train_target_dir / "test_quiet_b.wav",
    ]
    validation_target_files = [
        args.validation_target_dir / "test_normal_b.wav",
        args.validation_target_dir / "test_quiet_b.wav",
    ]
    train_interferers = find_speaker_audio(args.librispeech_root, TRAIN_SPEAKERS)
    validation_interferers = find_speaker_audio(
        args.librispeech_root, VALIDATION_SPEAKERS
    )
    baseline = evaluate(
        model,
        validation_enrollment,
        validation_target_files,
        validation_interferers,
        sample_rate,
        crop_samples,
        device,
        args.seed + 1000,
    )

    optimizer = torch.optim.AdamW(trainable, lr=args.learning_rate)
    generator = random.Random(args.seed)
    step_reports: list[dict[str, object]] = []
    started = time.perf_counter()
    train_speaker_ids = list(train_interferers)
    target_present_count = 0
    for step in range(args.steps):
        optimizer.zero_grad(set_to_none=True)
        target_absent = step % 4 == 1
        speaker_id = train_speaker_ids[step % len(train_speaker_ids)]
        source_files = train_interferers[speaker_id]
        interferer_file = source_files[step % len(source_files)]
        interferer = random_crop(
            load_mono(interferer_file, sample_rate), crop_samples, generator
        )
        model.train()
        if target_absent:
            mixture = interferer
            output = model(
                mixture[None, None].to(device), train_enrollment[None, None]
            ).squeeze(0).squeeze(0)
            energy_ratio = output.float().square().mean() / mixture.to(device).square().mean().clamp_min(
                1e-8
            )
            loss = 0.25 * 10 * torch.log10(energy_ratio.clamp_min(1e-8))
            case = {"kind": "target_absent", "interferer_speaker": speaker_id}
        else:
            target_file = train_target_files[
                target_present_count % len(train_target_files)
            ]
            target = energy_crop(
                load_mono(target_file, sample_rate), crop_samples, generator
            )
            tir_db = (0.0, -6.0)[
                (target_present_count // len(train_target_files)) % 2
            ]
            target_present_count += 1
            mixture, reference = mix_at_tir(target, interferer, tir_db)
            output = model(
                mixture[None, None].to(device), train_enrollment[None, None]
            ).squeeze(0).squeeze(0)
            loss = -si_sdr(output[None], reference[None].to(device)).mean()
            case = {
                "kind": "target_present",
                "target_file": target_file.name,
                "interferer_speaker": speaker_id,
                "tir_db": tir_db,
            }
        proximity = sum(
            (parameter - initial).float().square().sum()
            for parameter, initial in zip(trainable, initial_trainable)
        ) / initial_trainable_energy
        loss = loss + args.proximity_weight * proximity
        if not bool(torch.isfinite(loss).item()):
            raise RuntimeError(f"non-finite loss at step {step}")
        loss.backward()
        gradient_norm = torch.nn.utils.clip_grad_norm_(trainable, 1.0)
        if not bool(torch.isfinite(gradient_norm).item()):
            raise RuntimeError(f"non-finite gradient norm at step {step}")
        optimizer.step()
        step_reports.append(
            {
                "step": step + 1,
                **case,
                "loss": float(loss.detach().cpu()),
                "relative_parameter_distance_squared": float(
                    proximity.detach().cpu()
                ),
                "gradient_norm_before_clip": float(gradient_norm.detach().cpu()),
            }
        )
    if device.type == "mps":
        torch.mps.synchronize()
    training_seconds = time.perf_counter() - started

    candidate = evaluate(
        model,
        validation_enrollment,
        validation_target_files,
        validation_interferers,
        sample_rate,
        crop_samples,
        device,
        args.seed + 1000,
    )
    final_relative_parameter_distance_squared = float(
        (
            sum(
                (parameter - initial).float().square().sum()
                for parameter, initial in zip(trainable, initial_trainable)
            )
            / initial_trainable_energy
        )
        .detach()
        .cpu()
    )
    state = {key: value.detach().cpu() for key, value in model.state_dict().items()}
    candidate_checkpoint = args.output_dir / "avg_model.pt"
    torch.save(
        {
            "models": [state],
            "optimizers": [optimizer.state_dict()],
            "schedulers": [None],
            "scaler": None,
        },
        candidate_checkpoint,
    )
    shutil.copy2(args.model_dir / "config.yaml", args.output_dir / "config.yaml")
    if sha256(checkpoint) != source_checkpoint_sha256:
        raise RuntimeError("source checkpoint changed during the experiment")

    report = {
        "schema": "micforyou/personalized-finetune-poc/1",
        "warning": "Experimental candidate only; real-office held-out audio was not trained.",
        "source_checkpoint_sha256": source_checkpoint_sha256,
        "candidate_checkpoint_sha256": sha256(candidate_checkpoint),
        "source_checkpoint_unchanged": True,
        "device": device.type,
        "sample_rate": sample_rate,
        "steps": args.steps,
        "crop_seconds": args.crop_seconds,
        "learning_rate": args.learning_rate,
        "proximity_weight": args.proximity_weight,
        "total_parameters": sum(parameter.numel() for parameter in model.parameters()),
        "trainable_parameters": sum(parameter.numel() for parameter in trainable),
        "train_speakers": list(TRAIN_SPEAKERS),
        "validation_speakers": list(VALIDATION_SPEAKERS),
        "train_enrollment_start_seconds": train_enrollment_start / sample_rate,
        "validation_enrollment_start_seconds": validation_enrollment_start
        / sample_rate,
        "training_seconds": training_seconds,
        "final_relative_parameter_distance_squared": (
            final_relative_parameter_distance_squared
        ),
        "steps_detail": step_reports,
        "baseline_validation": baseline,
        "candidate_validation": candidate,
        "quality_gate_run": False,
        "deployment_allowed": False,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    (args.output_dir / "report.json").write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
