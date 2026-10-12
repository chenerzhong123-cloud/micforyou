"""Performance verdicts, admission rules, and attempt bookkeeping.

The voice registration and the machine performance check are separate
concerns: a saved voice is never discarded because performance failed, and a
candidate may only run live filtering after an explicit verdict.

A verdict is an immutable part of its candidate's registration folder; the
active registration is whichever folder ``config.json`` points at. Committing
is therefore a single atomic config rename: the old pair stays whole until
the rename and the new pair is whole after it — a failure or crash can never
leave a config paired with a foreign verdict.

Verdicts are bound to the full identity of the voice (input device, model and
enrollment hashes, app version/build, runtime frame parameters), so a result
from another microphone, an older build, or different runtime parameters can
never authorize a start. Missing identity information fails closed.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
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


def app_identity(bundle_root: Path | None) -> dict:
    """Runtime identity including the build, not just the marketing version.

    Two builds of the same 0.2.2 can differ in behavior; only the build (when
    recorded in the manifest) distinguishes them for verdict invalidation.
    """
    if bundle_root is None:
        return {"app_version": "dev", "app_build": None}
    try:
        manifest = json.loads((bundle_root / "bundle-manifest.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {"app_version": "unknown", "app_build": None}
    version, build = manifest.get("version"), manifest.get("build")
    return {"app_version": str(version) if version is not None else "unknown",
            "app_build": str(build) if build is not None else None}


def identity(input_device: str, onnx_model: Path, enrollment: Path,
             bundle_root: Path | None) -> dict:
    def digest(path: Path) -> str | None:
        return sha256_file(path) if path.exists() else None
    return {"input_device": input_device,
            "onnx_sha256": digest(onnx_model),
            "enrollment_sha256": digest(enrollment),
            **app_identity(bundle_root)}


def _finite_number(value) -> float | None:
    """A non-negative finite plain number, or None for anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return float(value)


def classify_latency(payload: dict) -> tuple[str, str | None, dict]:
    """Map one pacing report to (verdict, reason, metrics).

    verdict is ``pass`` (stable and below the latency limit),
    ``latency_warning`` (equally stable but slower), or ``blocked``. Stability
    requirements — completed run, matching lengths, finite output, no real
    underrun — are shared by both passing verdicts and are never relaxed.
    Malformed or non-numeric fields are rejected as invalid reports instead of
    raising, so a corrupt report can never become an approvable verdict.
    """
    inner = payload.get("bridge_internal") if isinstance(payload, dict) else None
    if not isinstance(inner, dict):
        return "blocked", "invalid_report", {}
    errors_value = inner.get("errors")
    metrics = {
        "status": inner.get("status") if isinstance(inner.get("status"), str) else None,
        "length_match": inner.get("length_match") if isinstance(inner.get("length_match"), bool) else None,
        "nonfinite_samples": inner.get("nonfinite_samples")
            if isinstance(inner.get("nonfinite_samples"), int)
            and not isinstance(inner.get("nonfinite_samples"), bool) else None,
        "underrun_ms": _finite_number(inner.get("underrun_ms")),
        "latency_ms_p95": None,
        "errors": [item for item in errors_value if isinstance(item, str)]
            if isinstance(errors_value, list) else [],
    }
    if metrics["status"] is None:
        return "blocked", "invalid_report", metrics
    if metrics["status"] != "COMPLETED":
        return "blocked", "fault", metrics
    if metrics["length_match"] is None:
        return "blocked", "invalid_report", metrics
    if metrics["length_match"] is not True:
        return "blocked", "length_mismatch", metrics
    if metrics["nonfinite_samples"] is None:
        return "blocked", "invalid_report", metrics
    if metrics["nonfinite_samples"] != 0:
        return "blocked", "nonfinite_output", metrics
    if metrics["underrun_ms"] is None:
        return "blocked", "invalid_report", metrics
    if metrics["underrun_ms"] > 0:
        return "blocked", "underrun", metrics
    bridge = inner.get("bridge_latency")
    p95 = _finite_number(bridge.get("latency_ms_p95")) if isinstance(bridge, dict) else None
    metrics["latency_ms_p95"] = p95
    if p95 is None:
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


def candidate_verdict_path(folder: Path) -> Path:
    """Legacy location (folder root) kept for reading build-8 registrations."""
    return folder / VERDICT_FILE


def read_candidate_verdict(folder: Path) -> dict | None:
    return _read_verdict_file(candidate_verdict_path(folder))


def attempt_verdict_path(folder: Path, ref: str) -> Path:
    return folder / "attempts" / ref / "verdict.json"


def read_attempt_verdict(folder: Path, ref: str) -> dict | None:
    """The immutable verdict one attempt wrote, plus its approval overlay."""
    verdict = _read_verdict_file(attempt_verdict_path(folder, ref))
    if verdict is None:
        return None
    approval = _read_verdict_file(folder / "attempts" / ref / "verdict-approved.json")
    if approval is not None:
        verdict = {**verdict, **{key: approval.get(key, verdict.get(key))
                                 for key in ("approved_trial",)}}
    return verdict


def latest_attempt_verdict(folder: Path) -> tuple[dict | None, str | None]:
    """Newest attempt verdict in a folder — what a pending approval operates
    on. Attempts are separate directories, so a newer retest never overwrites
    an older conclusion."""
    directory = folder / "attempts"
    if not directory.is_dir():
        return None, None
    best, best_ref, best_stamp = None, None, None
    for entry in directory.iterdir():
        if not entry.is_dir() or not _plain_name(entry.name):
            continue
        verdict_file = attempt_verdict_path(folder, entry.name)
        if not verdict_file.is_file():
            continue
        verdict = read_attempt_verdict(folder, entry.name)
        if verdict is None:
            continue
        try:
            stamp = verdict_file.stat().st_mtime
        except OSError:
            continue
        if best_stamp is None or stamp >= best_stamp:
            best, best_ref, best_stamp = verdict, entry.name, stamp
    return best, best_ref


def _plain_name(name: str) -> bool:
    import re as _re
    return _re.fullmatch(r"[0-9A-Za-z_-]{6,64}", name) is not None


def active_verdict_folder(config) -> Path:
    """The registration folder whose verdict authorizes this active config."""
    return config.enrollment.parent


def read_active_verdict(config) -> dict | None:
    """The verdict this config's atomic reference points at.

    ``verdict_ref`` names the attempts subdirectory written at commit time,
    so retests of the same folder create new attempt directories and can
    never overwrite the authorization an active config points at. Refs from
    older builds are absent; those registrations keep reading the folder-root
    file, which retests no longer write.
    """
    folder = active_verdict_folder(config)
    ref = getattr(config, "verdict_ref", None)
    if isinstance(ref, str) and _plain_name(ref):
        return read_attempt_verdict(folder, ref)
    return read_candidate_verdict(folder)


def _read_verdict_file(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != VERDICT_SCHEMA:
        return None
    return payload


def _verdict_payload(verdict: dict) -> dict:
    return {"schema": VERDICT_SCHEMA, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            **verdict}


def write_candidate_verdict(folder: Path, verdict: dict) -> None:
    """Write an attempt's verdict into its own immutable attempt directory."""
    attempt_id = verdict.get("attempt_id")
    if not isinstance(attempt_id, str) or not _plain_name(attempt_id):
        raise ValueError("attempt verdict needs a plain attempt_id")
    directory = folder / "attempts" / attempt_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "verdict.json").write_text(
        json.dumps(_verdict_payload(verdict), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def write_attempt_approval(folder: Path, attempt_id: str) -> None:
    """Record the explicit trial approval next to its (immutable) verdict."""
    if not _plain_name(attempt_id):
        raise ValueError("attempt id must be a plain directory name")
    directory = folder / "attempts" / attempt_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "verdict-approved.json").write_text(json.dumps(
        {"schema": VERDICT_SCHEMA,
         "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
         "approved_trial": True}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def commit_candidate(config, config_path: Path, verdict: dict) -> None:
    """Switch the active registration to this candidate's attempt.

    The verdict is an immutable file inside the attempt's own directory; the
    single atomic config rename (now carrying ``verdict_ref``) is the commit
    point. Before it, the active pair is entirely the old one — the old
    config still points at the old attempt's verdict, which no retest of the
    same folder overwrites; after it, entirely the new one. A crash at any
    step leaves the old pair intact plus a fully-written, retestable or
    approvable new attempt.
    """
    from dataclasses import replace as _replace
    from .product import save_config
    write_candidate_verdict(config.enrollment.parent, verdict)
    save_config(_replace(config, verdict_ref=verdict["attempt_id"]), config_path)


def validate_verdict(payload: dict) -> str | None:
    """Structural validation; returns None when valid, else a short reason.

    Numeric fields must be finite and non-negative; identity fields must be
    strings or explicitly None. This keeps corrupt or hand-edited files from
    becoming authorization, without raising on hostile shapes.
    """
    if not isinstance(payload, dict):
        return "payload"
    if payload.get("schema") != VERDICT_SCHEMA:
        return "schema"
    if payload.get("verdict") not in {"pass", "latency_warning", "blocked"}:
        return "verdict"
    if not isinstance(payload.get("approved_trial"), bool):
        return "approved_trial"
    frames = payload.get("frames_per_chunk")
    if not isinstance(frames, int) or isinstance(frames, bool) or frames <= 0:
        return "frames_per_chunk"
    if _finite_number(payload.get("prefill_ms")) is None:
        return "prefill_ms"
    if payload.get("verdict") in {"pass", "latency_warning"}:
        if _finite_number(payload.get("latency_ms_p95")) is None:
            return "latency_ms_p95"
    ident = payload.get("identity")
    if not isinstance(ident, dict):
        return "identity"
    for key in ("input_device", "onnx_sha256", "enrollment_sha256",
                "app_version", "app_build"):
        value = ident.get(key)
        if value is not None and not isinstance(value, str):
            return f"identity.{key}"
    if payload["verdict"] in {"pass", "latency_warning"}:
        if ident.get("onnx_sha256") is None or ident.get("enrollment_sha256") is None:
            return "identity.incomplete"
        if not isinstance(ident.get("input_device"), str) or not ident["input_device"]:
            return "identity.incomplete"
    return None


def admission(config, bundle_root: Path | None, config_path: Path) -> tuple[str, str | None]:
    """Decide whether the active config may start live filtering.

    Returns (decision, reason): ``allow``, ``warn_trial`` (stable but slower
    and not yet explicitly approved), or ``deny``. Only the verdict inside the
    active registration's own folder is consulted — a pending candidate's
    verdict lives in a different folder and never affects the active one.
    Developer configs keep their manual benchmark/latency flow and are not
    gated here.
    """
    if not config.bundle_managed:
        return "allow", None
    verdict = read_active_verdict(config)
    if verdict is None:
        return "deny", "unchecked"
    invalid = validate_verdict(verdict)
    if invalid is not None:
        return "deny", "invalid_verdict"
    if verdict["verdict"] == "blocked":
        return "deny", verdict.get("reason") or "blocked"
    if verdict["verdict"] == "latency_warning" and not verdict["approved_trial"]:
        return "warn_trial", "high_latency"
    if (config.frames_per_chunk != verdict["frames_per_chunk"]
            or config.prefill_ms != verdict["prefill_ms"]):
        return "deny", "params_changed"
    recorded = verdict["identity"]
    current = identity(config.input_device, config.onnx_model, config.enrollment,
                       bundle_root)
    if current["onnx_sha256"] is None:
        return "deny", "model_missing"
    if current["enrollment_sha256"] is None:
        return "deny", "model_missing"
    if recorded.get("input_device") != current["input_device"]:
        return "deny", "device_changed"
    if recorded.get("onnx_sha256") != current["onnx_sha256"]:
        return "deny", "model_changed"
    if recorded.get("enrollment_sha256") != current["enrollment_sha256"]:
        return "deny", "enrollment_changed"
    if (recorded.get("app_version") != current["app_version"]
            or recorded.get("app_build") != current["app_build"]):
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


def prune_attempt_folders(folder: Path, keep: set[str] | None = None) -> None:
    """Keep only the newest few per-candidate attempt report directories.

    Directories named in ``keep`` (the active config's reference and the
    pending conclusion awaiting approval) are never removed, however old.
    """
    directory = folder / "attempts"
    if not directory.is_dir():
        return
    preserve = keep or set()
    records = sorted(entry for entry in directory.iterdir() if entry.is_dir())
    for old in records[:-MAX_ATTEMPT_RECORDS]:
        if old.name in preserve:
            continue
        shutil.rmtree(old, ignore_errors=True)
