from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from .audio import resample


def load_mono(path: Path, sample_rate: int) -> np.ndarray:
    audio, source_rate = sf.read(path, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    return resample(mono, int(source_rate), sample_rate)


def rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))


def repeat_and_crop(audio: np.ndarray, length: int, rng: np.random.Generator) -> tuple[np.ndarray, int]:
    if not len(audio):
        raise ValueError("cannot crop empty audio")
    repeats = int(np.ceil((length + len(audio)) / len(audio)))
    tiled = np.tile(audio, repeats)
    start = int(rng.integers(0, len(audio)))
    return np.asarray(tiled[start : start + length], dtype=np.float32), start


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_mixtures(
    target_path: Path,
    interferer_path: Path,
    output_dir: Path,
    ratios_db: list[float],
    sample_rate: int = 16_000,
    seed: int = 20_260_913,
) -> dict[str, Any]:
    target = load_mono(target_path, sample_rate)
    interferer = load_mono(interferer_path, sample_rate)
    rng = np.random.default_rng(seed)
    interferer, crop_start = repeat_and_crop(interferer, len(target), rng)
    target_rms = rms(target)
    interferer_rms = rms(interferer)
    if target_rms == 0 or interferer_rms == 0:
        raise ValueError("target and interferer must both contain non-zero audio")

    output_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    for ratio_db in ratios_db:
        target_gain = (10 ** (ratio_db / 20)) * interferer_rms / target_rms
        target_stem = target * target_gain
        interferer_stem = interferer.copy()
        mixture = target_stem + interferer_stem
        peak = float(np.max(np.abs(mixture)))
        safety_gain = min(1.0, 0.98 / peak) if peak else 1.0
        target_stem *= safety_gain
        interferer_stem *= safety_gain
        mixture *= safety_gain
        sign = "neg" if ratio_db < 0 else "pos"
        label = f"tir_{sign}{abs(ratio_db):g}db"
        mix_path = output_dir / f"{label}-mix.wav"
        target_out = output_dir / f"{label}-target.wav"
        interferer_out = output_dir / f"{label}-interferer.wav"
        sf.write(mix_path, mixture, sample_rate, subtype="FLOAT")
        sf.write(target_out, target_stem, sample_rate, subtype="FLOAT")
        sf.write(interferer_out, interferer_stem, sample_rate, subtype="FLOAT")
        measured = 20 * np.log10(rms(target_stem) / rms(interferer_stem))
        cases.append(
            {
                "kind": "target-present",
                "requested_tir_db": ratio_db,
                "measured_tir_db": float(measured),
                "mixture": str(mix_path),
                "target": str(target_out),
                "interferer": str(interferer_out),
                "safety_gain": safety_gain,
            }
        )

    absent = interferer.copy()
    absent_gain = min(1.0, 0.98 / float(np.max(np.abs(absent))))
    absent *= absent_gain
    absent_path = output_dir / "target-absent-mix.wav"
    sf.write(absent_path, absent, sample_rate, subtype="FLOAT")
    cases.append(
        {
            "kind": "target-absent",
            "mixture": str(absent_path),
            "interferer": str(interferer_path),
            "safety_gain": absent_gain,
        }
    )
    return {
        "sample_rate": sample_rate,
        "rms_definition": "sqrt(mean(x^2)) over the full cropped waveform",
        "ratio_definition": "20*log10(RMS(target stem)/RMS(interferer stem))",
        "crop_rule": "repeat interferer if needed, then seeded uniform start offset",
        "seed": seed,
        "interferer_crop_start_samples": crop_start,
        "source_hashes": {
            "target": sha256(target_path),
            "interferer": sha256(interferer_path),
        },
        "cases": cases,
    }


def si_sdr(estimate: np.ndarray, reference: np.ndarray) -> float:
    length = min(len(estimate), len(reference))
    estimate = np.asarray(estimate[:length], dtype=np.float64)
    reference = np.asarray(reference[:length], dtype=np.float64)
    estimate -= np.mean(estimate)
    reference -= np.mean(reference)
    scale = np.dot(estimate, reference) / max(np.dot(reference, reference), 1e-20)
    desired = scale * reference
    error = estimate - desired
    return float(10 * np.log10(np.sum(desired**2) / max(np.sum(error**2), 1e-20)))


def score_output(output_path: Path, mixture_path: Path, target_path: Path | None) -> dict[str, Any]:
    output, output_rate = sf.read(output_path, dtype="float32", always_2d=True)
    mixture, mixture_rate = sf.read(mixture_path, dtype="float32", always_2d=True)
    output = output.mean(axis=1)
    mixture = mixture.mean(axis=1)
    if output_rate != mixture_rate:
        output = resample(output, int(output_rate), int(mixture_rate))
    result: dict[str, Any] = {
        "output": str(output_path),
        "mixture": str(mixture_path),
        "output_rms": rms(output),
        "mixture_rms": rms(mixture),
        "output_attenuation_db": float(20 * np.log10(max(rms(output), 1e-20) / max(rms(mixture), 1e-20))),
    }
    if target_path:
        target, target_rate = sf.read(target_path, dtype="float32", always_2d=True)
        target = target.mean(axis=1)
        if target_rate != mixture_rate:
            target = resample(target, int(target_rate), int(mixture_rate))
        baseline = si_sdr(mixture, target)
        extracted = si_sdr(output, target)
        result.update(
            {
                "target": str(target_path),
                "mixture_si_sdr_db": baseline,
                "output_si_sdr_db": extracted,
                "si_sdri_db": extracted - baseline,
            }
        )
    return result
