"""Same-folder retest isolation: the round-3 acceptance branch.

A successful registration leaves pending and active sharing one voice
folder. Every failing, cancelled, or uncommitted retest of that folder must
leave the old config and the verdict it references byte-identical and the
old registration startable; only a commit (pass, or an approved trial)
switches the reference, atomically, to the new attempt.
"""
import json
from pathlib import Path

import pytest

from micforyou import performance
from micforyou.product import ProductConfig, load_config, save_config


def latency_report(**changes):
    inner = dict(status="COMPLETED", length_match=True, nonfinite_samples=0,
                 underrun_ms=0, errors=[],
                 bridge_latency={"latency_ms_p95": 260.0})
    inner.update(changes)
    return {"bridge_internal": inner}


def benchmark_payload(rtf=0.5):
    return {"schema": "micforyou/onnx-cpu-benchmark/1", "candidates": [
        {"frames_per_chunk": 8, "intra_op_threads": "1",
         "processing_rtf": rtf, "model_call_ms_p95": 30.0, "model_calls": 100,
         "input_samples": 480000, "output_samples": 480000,
         "nonfinite_samples": 0, "error": None, "length_match": True}]}


def active_fixture(tmp_path: Path, monkeypatch):
    """A finished successful registration: committed config (24f/200ms),
    pending pointer and job pointing at the same voice folder."""
    from micforyou import setup
    from micforyou.audio import Device

    bundle = tmp_path / "Bundle/Runtime"
    bundle.mkdir(parents=True)
    (bundle / "bundle-manifest.json").write_text(
        json.dumps({"version": "0.2.3", "build": "9"}))
    monkeypatch.setenv("MICFORYOU_BUNDLE_ROOT", str(bundle))
    config_path = tmp_path / "userdata/config.json"
    token = "activevoice"
    folder = config_path.parent / "registrations" / token
    folder.mkdir(parents=True)
    (folder / "core.onnx").write_bytes(b"onnx")
    (folder / "enrollment.wav").write_bytes(b"wav")
    active = ProductConfig(
        input_device="Mic", model_repo=bundle / "vendor",
        model_dir=bundle / "models/tfmap_context_causal_100",
        enrollment=folder / "enrollment.wav", onnx_model=folder / "core.onnx",
        runtime_python=bundle / "python/bin/python3.12", project_root=bundle,
        bundle_managed=True, frames_per_chunk=24, prefill_ms=200.0)
    verdict = {
        "schema": performance.VERDICT_SCHEMA,
        "verdict": "pass", "reason": None, "approved_trial": False,
        "frames_per_chunk": 24, "prefill_ms": 200.0,
        "identity": performance.identity("Mic", folder / "core.onnx",
                                         folder / "enrollment.wav", bundle),
        "candidate_token": token, "attempt_id": "firstattempt01",
        "latency_ms_p95": 321.0}
    performance.commit_candidate(active, config_path, verdict)
    active = load_config(config_path)
    assert active.verdict_ref == "firstattempt01"
    (config_path.parent / "pending-candidate.json").write_text(json.dumps(
        {"token": token, "input_device": "Mic", "frames_per_chunk": 24,
         "prefill_ms": 200.0}))

    monkeypatch.setattr(setup, "same_worker", lambda job: True)
    monkeypatch.setattr(setup.signal, "signal", lambda *a: None)
    monkeypatch.setattr(setup, "list_devices", lambda: [
        Device(0, "Mic", 0, 1, 0, 48000), Device(1, "BlackHole 2ch", 0, 2, 2, 48000)])
    monkeypatch.setattr(setup, "record_input",
                        lambda *a, **k: pytest.fail("retest must not record"))
    from micforyou import cli
    monkeypatch.setattr(cli, "require_inactive", lambda *a: None)
    return setup, config_path, folder, bundle, active


def spawn_worker(setup, config_path, worker_token):
    setup.save_job(config_path, dict(
        status="RUNNING", stage="retest", progress=0, token=worker_token,
        pid=0, voice="saved", performance="checking"))


def retest(monkeypatch, setup, config_path, folder, worker_token,
           report_changes=None, rtf=0.5, fail_rename=False, interrupt=False):
    state = {}

    def run(command, **kwargs):
        name = Path(command[1]).name
        if name == "benchmark_onnx_tse.py":
            Path(command[command.index("--result") + 1]).write_text(
                json.dumps(benchmark_payload(rtf)))
        elif name == "measure_bridge_latency.py":
            if interrupt:
                raise KeyboardInterrupt()
            changes = dict(report_changes or {})
            bridge = changes.get("bridge_latency")
            if not (isinstance(bridge, dict) and "latency_ms_p95" in bridge):
                changes["bridge_latency"] = {"latency_ms_p95": 260.0}
            Path(command[command.index("--result") + 1]).write_text(
                json.dumps(latency_report(**changes)))
        else:
            pytest.fail(str(command))

    monkeypatch.setattr(setup.subprocess, "run", run)
    real_replace = Path.replace
    if fail_rename:
        def failing(source, target):
            if source.name == "config.json.tmp":
                state["failed"] = True
                raise OSError("injected final config rename failure")
            return real_replace(source, target)
        monkeypatch.setattr(Path, "replace", failing)
    setup.run_worker(config_path, "Mic", worker_token, stage="performance")
    return state


@pytest.mark.parametrize("scenario, report_changes, rtf, interrupt", [
    ("fault", dict(status="FAULT", errors=["queue exceeded"]), 0.5, False),
    ("insufficient_speed", {}, 1.1, False),
    ("warning", {"bridge_latency": {"latency_ms_p95": 450.0}}, 0.5, False),
    ("cancelled", {}, 0.5, True),
])
def test_failed_retest_of_active_folder_keeps_old_authorization(
        tmp_path, monkeypatch, scenario, report_changes, rtf, interrupt):
    setup, config_path, folder, bundle, active = active_fixture(tmp_path, monkeypatch)
    old_config_bytes = config_path.read_bytes()
    old_verdict_file = folder / "attempts" / active.verdict_ref / "verdict.json"
    old_verdict_bytes = old_verdict_file.read_bytes()

    spawn_worker(setup, config_path, "retestworker01")
    if scenario in {"fault", "insufficient_speed"}:
        with pytest.raises(ValueError):
            retest(monkeypatch, setup, config_path, folder, "retestworker01",
                   report_changes=report_changes, rtf=rtf)
    else:
        # warning ends WAITING, cancellation ends CANCELLED — no raise.
        retest(monkeypatch, setup, config_path, folder, "retestworker01",
               report_changes=report_changes, rtf=rtf, interrupt=interrupt)

    # Old pair byte-identical and still startable; the failed attempt wrote
    # only its own directory.
    assert config_path.read_bytes() == old_config_bytes
    assert old_verdict_file.read_bytes() == old_verdict_bytes
    reloaded = load_config(config_path)
    assert reloaded.verdict_ref == "firstattempt01"
    assert reloaded.frames_per_chunk == 24 and reloaded.prefill_ms == 200.0
    assert performance.admission(reloaded, bundle, config_path) == ("allow", None)
    new_attempt = performance.read_attempt_verdict(folder, "retestworker01")
    if scenario == "warning":
        assert new_attempt["verdict"] == "latency_warning"
        assert setup.read_job(config_path)["status"] == "WAITING"
    elif scenario == "cancelled":
        assert setup.read_job(config_path)["status"] == "CANCELLED"
    else:
        assert new_attempt["verdict"] == "blocked"
    if scenario != "warning":
        # The unapproved new conclusion never touches the active one.
        assert performance.read_active_verdict(reloaded)["verdict"] == "pass"


def test_parameter_change_commit_failure_keeps_old_pair(tmp_path, monkeypatch):
    """Round-3 probe scenario 2: same folder, parameters change 24f/200 ->
    16f/100, the final rename fails — the old authorization must survive."""
    setup, config_path, folder, bundle, active = active_fixture(tmp_path, monkeypatch)
    old_config_bytes = config_path.read_bytes()
    old_verdict_file = folder / "attempts" / active.verdict_ref / "verdict.json"

    spawn_worker(setup, config_path, "retestworker02")
    with monkeypatch.context() as isolated, \
            pytest.raises(OSError, match="injected final config rename"):
        retest(isolated, setup, config_path, folder, "retestworker02",
               fail_rename=True)

    assert config_path.read_bytes() == old_config_bytes  # still 24f/200
    assert old_verdict_file.read_bytes()  # untouched
    reloaded = load_config(config_path)
    assert reloaded.frames_per_chunk == 24 and reloaded.prefill_ms == 200.0
    assert performance.admission(reloaded, bundle, config_path) == ("allow", None)
    # The prepared verdict of the crashed commit stays approvable/retestable.
    prepared = performance.read_attempt_verdict(folder, "retestworker02")
    assert prepared is not None
    # Retrying after the transient failure commits the new parameters.
    spawn_worker(setup, config_path, "retestworker03")
    retest(monkeypatch, setup, config_path, folder, "retestworker03")
    reloaded = load_config(config_path)
    assert reloaded.frames_per_chunk == 8 and reloaded.prefill_ms == 100.0
    assert reloaded.verdict_ref == "retestworker03"
    assert performance.admission(reloaded, bundle, config_path) == ("allow", None)
    # The old attempt's verdict file survives for the record.
    assert performance.read_attempt_verdict(folder, "firstattempt01")["verdict"] == "pass"


def test_approve_commit_failure_then_retry(tmp_path, monkeypatch):
    setup, config_path, folder, bundle, active = active_fixture(tmp_path, monkeypatch)
    spawn_worker(setup, config_path, "retestworker04")
    retest(monkeypatch, setup, config_path, folder, "retestworker04",
           report_changes={"bridge_latency": {"latency_ms_p95": 450.0}})
    assert setup.read_job(config_path)["status"] == "WAITING"

    real_replace = Path.replace

    def failing(source, target):
        if source.name == "config.json.tmp":
            raise OSError("injected approval config failure")
        return real_replace(source, target)

    monkeypatch.setattr(Path, "replace", failing)
    with pytest.raises(OSError):
        setup.approve_trial(config_path)
    monkeypatch.setattr(Path, "replace", real_replace)
    # Old authorization survived the failed approval; retrying succeeds.
    assert performance.admission(load_config(config_path), bundle, config_path) == ("allow", None)
    assert setup.read_job(config_path)["status"] == "WAITING"
    result = setup.approve_trial(config_path)
    assert result["status"] == "READY"
    reloaded = load_config(config_path)
    assert reloaded.verdict_ref == "retestworker04"
    assert performance.admission(reloaded, bundle, config_path) == ("allow", None)


def test_passing_retest_switches_reference_and_survives_reload(tmp_path, monkeypatch):
    setup, config_path, folder, bundle, active = active_fixture(tmp_path, monkeypatch)
    spawn_worker(setup, config_path, "retestworker05")
    retest(monkeypatch, setup, config_path, folder, "retestworker05")
    reloaded = load_config(config_path)
    assert reloaded.verdict_ref == "retestworker05"
    assert (reloaded.frames_per_chunk, reloaded.prefill_ms) == (8, 100.0)
    assert performance.admission(reloaded, bundle, config_path) == ("allow", None)
    # Simulated app restart: re-reading from disk gives the same answer.
    assert performance.admission(load_config(config_path), bundle, config_path) == ("allow", None)


def test_legacy_root_verdict_survives_same_folder_retest(tmp_path, monkeypatch):
    """Build-8 registration: no verdict_ref, verdict at the folder root. A
    failing retest of the same folder must not touch the root file."""
    from dataclasses import replace
    setup, config_path, folder, bundle, active = active_fixture(tmp_path, monkeypatch)
    root_verdict = performance.read_attempt_verdict(folder, active.verdict_ref)
    legacy = replace(active, verdict_ref=None)
    save_config(legacy, config_path)
    performance.write_attempt_root_for_test = None  # noqa - clarity only
    (folder / "performance.json").write_text(json.dumps(
        {"schema": performance.VERDICT_SCHEMA,
         "updated_at": "2026-10-12T00:00:00+0800", **root_verdict}))
    root_bytes = (folder / "performance.json").read_bytes()
    assert performance.admission(load_config(config_path), bundle, config_path) == ("allow", None)

    spawn_worker(setup, config_path, "retestworker06")
    with pytest.raises(ValueError):
        retest(monkeypatch, setup, config_path, folder, "retestworker06",
               report_changes=dict(status="FAULT", errors=["x"]))
    assert (folder / "performance.json").read_bytes() == root_bytes
    assert performance.admission(load_config(config_path), bundle, config_path) == ("allow", None)


def test_pruning_never_deletes_referenced_or_pending_attempts(tmp_path):
    """Retention keeps the newest few attempt dirs, but the active config's
    reference and the pending (approvable) conclusion survive any pruning."""
    from micforyou import setup
    folder = tmp_path / "registrations" / "activevoice"
    folder.mkdir(parents=True)
    config_path = tmp_path / "config.json"
    active = ProductConfig(
        input_device="Mic", model_repo=tmp_path / "vendor",
        model_dir=tmp_path / "models", enrollment=folder / "enrollment.wav",
        onnx_model=folder / "core.onnx", runtime_python=tmp_path / "python",
        project_root=tmp_path, bundle_managed=True)
    (folder / "enrollment.wav").write_bytes(b"wav")
    (folder / "core.onnx").write_bytes(b"onnx")

    def verdict_for(ref):
        return {
            "schema": performance.VERDICT_SCHEMA,
            "verdict": "latency_warning" if ref == "attempt06" else "pass",
            "reason": None, "approved_trial": False,
            "frames_per_chunk": 8, "prefill_ms": 100.0,
            "identity": {"input_device": "Mic"}, "candidate_token": "activevoice",
            "attempt_id": ref, "latency_ms_p95": 300.0}

    for index in range(1, 8):
        ref = f"attempt0{index}"
        performance.write_candidate_verdict(folder, verdict_for(ref))
    save_config(active, config_path)
    # Point the active config at the OLDEST attempt and let the newest be the
    # pending warning: both must survive pruning to the newest five.
    from dataclasses import replace
    save_config(replace(active, verdict_ref="attempt01"), config_path)
    setup._prune_attempts_preserving_references(config_path, folder)
    remaining = {entry.name for entry in (folder / "attempts").iterdir()}
    assert "attempt01" in remaining       # active reference
    assert "attempt06" in remaining       # newest (pending warning)
    assert len(remaining) <= performance.MAX_ATTEMPT_RECORDS + 1
    assert "attempt02" not in remaining   # old, unreferenced: pruned
