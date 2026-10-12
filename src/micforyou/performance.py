"""Performance verdicts, admission rules, and attempt bookkeeping.

The voice registration and the machine performance check are separate
concerns: a saved voice is never discarded because performance failed, and a
candidate may only run live filtering after an explicit verdict. Verdicts are
bound to the identity of the voice (device, model hash, app version) so a
result from another microphone or an older runtime cannot authorize a start.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time
import uuid

VERDICT_SCHEMA = "micforyou/performance-verdict/1"
LATENCY_P95_LIMIT_MS = 400.0
MAX_FRAMES_CANDIDATES = 3
MAX_ATTEMPT_RECORDS = 5
VERDICT_FILE = "performance.json"
ATTEMPTS_DIR = "performance-attempts"


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def app_version(bundle_root: Path | None) -> str:
    if bundle_root is not None:
        manifest = bundle_root / "bundle-manifest.json"
        try:
            return str(json.loads(manifest.read_text())["version"])
        except (OSError, KeyError, json.JSONDecodeError):
            return "unknown-bundle"
    return "dev"


def classify_latency(payload: dict) -> tuple[str, str | None, dict]:
    """Map one pacing report to (verdict, reason, metrics).

    verdict is ``pass`` (stable and below the latency limit),
    ``latency_warning`` (equally stable but slower), or ``blocked``. Stability
    requirements — completed run, matching lengths, finite output, no real
    underrun — are shared by both passing verdicts and are never relaxed.
    """
    inner = payload.get("bridge_internal")
    if not isinstance(inner, dict):
        return "blocked", "invalid_report", {}
    p95 = (inner.get("bridge_latency") or {}).get("latency_ms_p95")
    metrics = {
        "status": inner.get("status"),
        "length_match": inner.get("length_match"),
        "nonfinite_samples": inner.get("nonfinite_samples"),
        "underrun_ms": inner.get("underrun_ms"),
        "latency_ms_p95": p95,
        "errors": inner.get("errors") or [],
    }
    if metrics["status"] != "COMPLETED":
        return "blocked", "fault", metrics
    if metrics["length_match"] is not True:
        return "blocked", "length_mismatch", metrics
    if metrics["nonfinite_samples"] != 0:
        return "blocked", "nonfinite_output", metrics
    if not isinstance(metrics["underrun_ms"], (int, float)) or metrics["underrun_ms"] > 0:
        return "blocked", "underrun", metrics
    if not isinstance(p95, (int, float)) or not math.isfinite(p95):
        return "blocked", "invalid_report", metrics
    if p95 < LATENCY_P95_LIMIT_MS:
        return "pass", None, metrics
    return "latency_warning", "high_latency", metrics


def eligible_frames(benchmark_payload: dict) -> list[int]:
    """Eligible frame sizes, smallest chunk first, capped for bounded search.

    Ordering is latency-first: smaller chunks drain queues faster. The
    previous behavior of committing to the single best-RTF candidate could
    miss that a slightly slower but lower-latency candidate is stable.
    """
    if benchmark_payload.get("schema") != "micforyou/onnx-cpu-benchmark/1":
        raise ValueError("性能报告格式不正确")
    eligible = []
    for item in benchmark_payload.get("candidates", []):
        if item.get("intra_op_threads") != "1":
            continue
        rtf = item.get("processing_rtf")
        if not isinstance(rtf, (int, float)) or not math.isfinite(rtf) or rtf > 0.80:
            continue
        if item.get("error") or item.get("length_match") is False:
            continue
        if not item.get("model_calls") or item["model_calls"] < 10:
            continue
        frames = item.get("frames_per_chunk")
        if isinstance(frames, int) and frames > 0:
            eligible.append(frames)
    ordered = sorted(set(eligible))
    return ordered[:MAX_FRAMES_CANDIDATES]


def choose_best(candidates: list[dict]) -> dict | None:
    """Pick pass first, then the fastest stable latency warning, else None."""
    passes = [item for item in candidates if item["verdict"] == "pass"]
    if passes:
        return passes[0]
    warnings = [item for item in candidates if item["verdict"] == "latency_warning"]
    if warnings:
        return min(warnings, key=lambda item: item["metrics"].get("latency_ms_p95")
                   if isinstance(item["metrics"].get("latency_ms_p95"), (int, float))
                   else float("inf"))
    return None


def verdict_path(config_path: Path) -> Path:
    return config_path.parent / VERDICT_FILE


def read_verdict(config_path: Path) -> dict | None:
    path = verdict_path(config_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("schema") != VERDICT_SCHEMA:
        return None
    return payload


def write_verdict(config_path: Path, verdict: dict) -> None:
    payload = {"schema": VERDICT_SCHEMA, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               **verdict}
    verdict_path(config_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def identity(input_device: str, onnx_model: Path, version: str) -> dict:
    return {
        "input_device": input_device,
        "onnx_sha256": sha256_file(onnx_model) if onnx_model.exists() else None,
        "app_version": version,
    }


def admission(config, bundle_root: Path | None, config_path: Path) -> tuple[str, str | None]:
    """Decide whether the active config may start live filtering.

    Returns (decision, reason): ``allow``, ``warn_trial`` (stable but slower
    and not yet explicitly approved), or ``deny``. Developer configs keep
    their manual benchmark/latency flow and are not gated here.
    """
    if not config.bundle_managed:
        return "allow", None
    verdict = read_verdict(config_path)
    if verdict is None:
        return "deny", "unchecked"
    if verdict.get("verdict") == "pass":
        pass
    elif verdict.get("verdict") == "latency_warning":
        if not verdict.get("approved_trial"):
            return "warn_trial", "high_latency"
    else:
        return "deny", verdict.get("reason") or "blocked"
    recorded = verdict.get("identity") or {}
    current = identity(config.input_device, config.onnx_model, app_version(bundle_root))
    if recorded.get("input_device") != current["input_device"]:
        return "deny", "device_changed"
    if recorded.get("onnx_sha256") not in (None, current["onnx_sha256"]):
        return "deny", "model_changed"
    if recorded.get("app_version") != current["app_version"]:
        return "deny", "version_changed"
    return "allow", None


def record_attempt(config_path: Path, attempt: dict) -> None:
    """Persist one structured attempt; keep only the newest few."""
    directory = config_path.parent / ATTEMPTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    (directory / f"attempt-{stamp}.json").write_text(
        json.dumps(attempt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    records = sorted(directory.glob("attempt-*.json"))
    for old in records[:-MAX_ATTEMPT_RECORDS]:
        old.unlink(missing_ok=True)
