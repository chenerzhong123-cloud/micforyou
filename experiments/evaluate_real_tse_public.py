"""Evaluate a causal REAL-TSE checkpoint on a deterministic public DEV subset.

This deliberately does not run ASR. REAL-T has no isolated clean target, so
the report uses the checkpoint's frozen ECAPA encoder as a diagnostic speaker-
similarity measure and preserves audio outputs for later listening/Doubao A/B.
"""

from __future__ import annotations

import argparse
import csv
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


def choose_rows(metadata: list[Path], count: int) -> list[dict[str, str]]:
    selected = []
    for path in metadata:
        with path.open(newline="", encoding="utf-8") as source:
            rows = list(csv.DictReader(source))
        rows.sort(
            key=lambda row: (
                -float(row["mixture_ratio"]),
                row["mixture_utterance"],
                row["enrolment_speakers_utterance"],
            )
        )
        mixtures: set[str] = set()
        speakers: set[str] = set()
        for row in rows:
            if row["mixture_utterance"] in mixtures or row["speaker"] in speakers:
                continue
            selected.append(row)
            mixtures.add(row["mixture_utterance"])
            speakers.add(row["speaker"])
            if len(mixtures) == count:
                break
    return selected


def embedding(model, waveform: torch.Tensor) -> torch.Tensor:
    return model.spk_ft.spkemb.compute(waveform)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--embedding-model-dir", type=Path)
    parser.add_argument("--metadata", type=Path, action="append", required=True)
    parser.add_argument("--audio-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--count-per-source", type=int, default=3)
    args = parser.parse_args()

    sys.path.insert(0, str(args.repo))
    import wesep  # noqa: PLC0415

    extractor = wesep.load_model_local(str(args.model_dir))
    extractor.set_output_norm(False)
    model = extractor.model.eval()
    embedding_model = (
        wesep.load_model_local(str(args.embedding_model_dir)).model.eval()
        if args.embedding_model_dir
        else model
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    with torch.inference_mode():
        for row in choose_rows(args.metadata, args.count_per_source):
            mixture_path = args.audio_dir / f"{row['mixture_utterance']}.wav"
            enrollment_path = (
                args.audio_dir / f"{row['enrolment_speakers_utterance']}.wav"
            )
            output_path = args.output_dir / (
                f"{row['source']}-{row['mixture_utterance']}-{row['speaker']}.wav"
            )
            mixture, mixture_rate = torchaudio.load(mixture_path)
            enrollment, enrollment_rate = torchaudio.load(enrollment_path)

            start = time.perf_counter()
            output = extractor.extract_speech_from_pcm(
                mixture, mixture_rate, enrollment, enrollment_rate
            )[0]
            inference_seconds = time.perf_counter() - start
            sf.write(output_path, output.numpy(), extractor.resample_rate, subtype="FLOAT")

            enrollment_emb = embedding(embedding_model, enrollment)
            mixture_emb = embedding(embedding_model, mixture)
            output_emb = embedding(embedding_model, output.unsqueeze(0))
            results.append(
                {
                    "source": row["source"],
                    "mixture": row["mixture_utterance"],
                    "enrollment": row["enrolment_speakers_utterance"],
                    "speaker": row["speaker"],
                    "gender": row["gender"],
                    "speaker_ratio": float(row["speaker_ratio"]),
                    "overlap_ratio": float(row["mixture_ratio"]),
                    "audio_seconds": mixture.shape[-1] / mixture_rate,
                    "inference_seconds": inference_seconds,
                    "rtf": inference_seconds / (mixture.shape[-1] / mixture_rate),
                    "mixture_enrollment_cosine": float(
                        cosine_similarity(mixture_emb, enrollment_emb).item()
                    ),
                    "output_enrollment_cosine": float(
                        cosine_similarity(output_emb, enrollment_emb).item()
                    ),
                    "mixture_rms": float(mixture.square().mean().sqrt()),
                    "output_rms": float(output.square().mean().sqrt()),
                    "output": str(output_path),
                    "output_sha256": sha256(output_path),
                }
            )

    summary = {
        "selection": "highest overlap, unique mixture and speaker, deterministic lexical tie-break",
        "count": len(results),
        "mean_rtf": sum(row["rtf"] for row in results) / len(results),
        "mean_mixture_enrollment_cosine": sum(
            row["mixture_enrollment_cosine"] for row in results
        )
        / len(results),
        "mean_output_enrollment_cosine": sum(
            row["output_enrollment_cosine"] for row in results
        )
        / len(results),
        "records": results,
    }
    result_path = args.output_dir / "evaluation.json"
    result_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
