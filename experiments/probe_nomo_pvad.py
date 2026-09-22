"""Probe an external nomo-pvad checkout as an auxiliary target-presence gate.

This experiment does not replace TSE and never writes processed audio.  It
scores held-out waveforms in 160 ms chunks, reports probability distributions
and measures the actual sliding-window wrapper cost used by the upstream
release.

Example:
    python experiments/probe_nomo_pvad.py \
      --source-root /path/to/nomo-pvad \
      --eres-dir /path/to/eres2netv2 \
      --enrollment /private/enrollment.wav \
      --case Q01=/private/Q01.wav --case Q02=/private/Q02.wav \
      --output /private/report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


TARGET_RATE = 16_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_mono_16k(path: Path) -> np.ndarray:
    audio, rate = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    if rate != TARGET_RATE:
        audio = resample_poly(audio, TARGET_RATE, rate).astype(np.float32)
    if not np.isfinite(audio).all():
        raise ValueError(f"non-finite input: {path.name}")
    return np.asarray(audio, dtype=np.float32)


def parse_case(value: str) -> tuple[str, Path]:
    case_id, separator, path = value.partition("=")
    if not separator or not case_id or not path:
        raise argparse.ArgumentTypeError("case must be ID=/path/to/audio.wav")
    return case_id, Path(path).expanduser().resolve()


def git_revision(source_root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--eres-dir", type=Path, required=True)
    parser.add_argument("--enrollment", type=Path, required=True)
    parser.add_argument("--case", action="append", type=parse_case, required=True)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source_root = args.source_root.expanduser().resolve()
    checkpoint = (args.checkpoint or source_root / "weights/nomo_pvad.pt").resolve()
    eres_dir = args.eres_dir.expanduser().resolve()
    enrollment_path = args.enrollment.expanduser().resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(source_root))
    import torch  # imported from the isolated probe environment
    from nomo_pvad import CHUNK_SAMPLES, NomoPVAD, NomoPVADSession

    torch.set_num_threads(args.threads)
    model = NomoPVAD(str(checkpoint), eres2netv2_dir=str(eres_dir), device="cpu")
    enrollment = load_mono_16k(enrollment_path)
    started = time.perf_counter()
    embedding = model.extract_emb(enrollment)
    enrollment_ms = (time.perf_counter() - started) * 1000

    results = []
    for case_id, case_path in args.case:
        audio = load_mono_16k(case_path)
        session = NomoPVADSession(model)
        session.set_enrollment_emb(embedding.cpu().numpy())
        probabilities: list[float] = []
        call_ms: list[float] = []
        for offset in range(0, len(audio), CHUNK_SAMPLES):
            chunk = audio[offset : offset + CHUNK_SAMPLES]
            if len(chunk) < CHUNK_SAMPLES:
                chunk = np.pad(chunk, (0, CHUNK_SAMPLES - len(chunk)))
            call_started = time.perf_counter()
            probabilities.append(session.process_chunk(chunk))
            call_ms.append((time.perf_counter() - call_started) * 1000)

        probs = np.asarray(probabilities, dtype=np.float64)
        timings = np.asarray(call_ms, dtype=np.float64)
        if not np.isfinite(probs).all():
            raise ValueError(f"non-finite probability: {case_id}")
        quantile_values = np.percentile(probs, [0, 10, 25, 50, 75, 90, 100])
        results.append(
            {
                "id": case_id,
                "audio_name": case_path.name,
                "audio_sha256": sha256(case_path),
                "seconds": len(audio) / TARGET_RATE,
                "chunks": len(probs),
                "probability_quantiles": dict(
                    zip(
                        ("min", "p10", "p25", "p50", "p75", "p90", "max"),
                        map(float, quantile_values),
                    )
                ),
                "fraction_at_or_above": {
                    str(threshold): float((probs >= threshold).mean())
                    for threshold in (0.3, 0.5, 0.7)
                },
                "call_ms_p50": float(np.percentile(timings, 50)),
                "call_ms_p95": float(np.percentile(timings, 95)),
                "processing_rtf": float(timings.sum() / (len(timings) * 160.0)),
            }
        )

    report = {
        "schema": "micforyou/nomo-pvad-probe/1",
        "purpose": "auxiliary target-presence gate only; not a TSE replacement",
        "source_revision": git_revision(source_root),
        "checkpoint_sha256": sha256(checkpoint),
        "eres_checkpoint_sha256": sha256(eres_dir / "pretrained_eres2netv2.ckpt"),
        "threads": args.threads,
        "sample_rate": TARGET_RATE,
        "chunk_samples": CHUNK_SAMPLES,
        "enrollment_name": enrollment_path.name,
        "enrollment_sha256": sha256(enrollment_path),
        "enrollment_seconds": len(enrollment) / TARGET_RATE,
        "enrollment_encode_ms": enrollment_ms,
        "cases": results,
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
