"""Evaluate a REAL-TSE checkpoint on deterministic local mixture cases.

This only measures source separation and speaker similarity. It does not use
or invoke ASR.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import soundfile as sf
import torch
import torchaudio
from torch.nn.functional import cosine_similarity


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def si_sdr(estimate: torch.Tensor, reference: torch.Tensor) -> float:
    length = min(estimate.numel(), reference.numel())
    estimate = estimate.reshape(-1)[:length].double()
    reference = reference.reshape(-1)[:length].double()
    estimate -= estimate.mean()
    reference -= reference.mean()
    desired = reference * (estimate @ reference) / reference.square().sum().clamp_min(1e-20)
    error = estimate - desired
    return float(10 * torch.log10(desired.square().sum() / error.square().sum().clamp_min(1e-20)))


def rms(audio: torch.Tensor) -> float:
    return float(audio.float().square().mean().sqrt())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--embedding-model-dir", type=Path, required=True)
    parser.add_argument("--enrollment", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(args.repo))
    import wesep  # noqa: PLC0415

    cases = json.loads(args.metadata.read_text(encoding="utf-8"))
    extractor = wesep.load_model_local(str(args.model_dir))
    extractor.set_output_norm(False)
    model = extractor.model.eval()
    embedding_extractor = wesep.load_model_local(str(args.embedding_model_dir))
    embedding_model = embedding_extractor.model.eval()
    embedding_rate = embedding_extractor.resample_rate
    enrollment, enrollment_rate = torchaudio.load(args.enrollment)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = []

    with torch.inference_mode():
        enrollment_for_embedding = (
            torchaudio.functional.resample(enrollment, enrollment_rate, embedding_rate)
            if enrollment_rate != embedding_rate
            else enrollment
        )
        enrollment_embedding = embedding_model.spk_ft.spkemb.compute(
            enrollment_for_embedding
        )
        for case in cases["cases"]:
            mixture_path = Path(case["mixture"])
            mixture, mixture_rate = torchaudio.load(mixture_path)
            start = time.perf_counter()
            output = extractor.extract_speech_from_pcm(
                mixture, mixture_rate, enrollment, enrollment_rate
            )[0]
            elapsed = time.perf_counter() - start
            label = mixture_path.stem.replace("-mix", "")
            output_path = args.output_dir / f"{label}-extracted.wav"
            sf.write(output_path, output.numpy(), extractor.resample_rate, subtype="FLOAT")

            mixture_for_embedding = (
                torchaudio.functional.resample(mixture, mixture_rate, embedding_rate)
                if mixture_rate != embedding_rate
                else mixture
            )
            output_for_embedding = (
                torchaudio.functional.resample(
                    output.unsqueeze(0), extractor.resample_rate, embedding_rate
                )
                if extractor.resample_rate != embedding_rate
                else output.unsqueeze(0)
            )
            mixture_embedding = embedding_model.spk_ft.spkemb.compute(
                mixture_for_embedding
            )
            output_embedding = embedding_model.spk_ft.spkemb.compute(output_for_embedding)
            record = {
                "kind": case["kind"],
                "requested_tir_db": case.get("requested_tir_db"),
                "measured_tir_db": case.get("measured_tir_db"),
                "mixture": str(mixture_path),
                "output": str(output_path),
                "output_sha256": sha256(output_path),
                "audio_seconds": mixture.shape[-1] / mixture_rate,
                "inference_seconds": elapsed,
                "rtf": elapsed / (mixture.shape[-1] / mixture_rate),
                "mixture_rms": rms(mixture),
                "output_rms": rms(output),
                "output_attenuation_db": 20 * torch.log10(
                    torch.tensor(max(rms(output), 1e-20) / max(rms(mixture), 1e-20))
                ).item(),
                "mixture_enrollment_cosine": float(
                    cosine_similarity(mixture_embedding, enrollment_embedding).item()
                ),
                "output_enrollment_cosine": float(
                    cosine_similarity(output_embedding, enrollment_embedding).item()
                ),
            }
            if case["kind"] == "target-present":
                target, target_rate = torchaudio.load(case["target"])
                target_for_embedding = (
                    torchaudio.functional.resample(target, target_rate, embedding_rate)
                    if target_rate != embedding_rate
                    else target
                )
                if target_rate != extractor.resample_rate:
                    target = torchaudio.functional.resample(
                        target, target_rate, extractor.resample_rate
                    )
                if mixture_rate != extractor.resample_rate:
                    mixture_for_score = torchaudio.functional.resample(
                        mixture, mixture_rate, extractor.resample_rate
                    )
                else:
                    mixture_for_score = mixture
                mixture_score = si_sdr(mixture_for_score, target)
                output_score = si_sdr(output.unsqueeze(0), target)
                record.update(
                    {
                        "target": case["target"],
                        "mixture_si_sdr_db": mixture_score,
                        "output_si_sdr_db": output_score,
                        "si_sdri_db": output_score - mixture_score,
                        "target_enrollment_cosine": float(
                            cosine_similarity(
                                embedding_model.spk_ft.spkemb.compute(
                                    target_for_embedding
                                ),
                                enrollment_embedding,
                            ).item()
                        ),
                    }
                )
            records.append(record)

    result = {
        "model_sha256": sha256(args.model_dir / "avg_model.pt"),
        "embedding_model_sha256": sha256(args.embedding_model_dir / "avg_model.pt"),
        "enrollment": str(args.enrollment),
        "enrollment_sha256": sha256(args.enrollment),
        "metadata": str(args.metadata),
        "metadata_sha256": sha256(args.metadata),
        "records": records,
    }
    result["mean_rtf"] = sum(row["rtf"] for row in records) / len(records)
    args.output_dir.joinpath("evaluation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
