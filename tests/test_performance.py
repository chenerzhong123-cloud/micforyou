"""Performance verdict, admission, and retest behavior."""
import json
from pathlib import Path

import pytest

from micforyou import performance
from micforyou.performance import (
    admission,
    choose_best,
    classify_latency,
    eligible_frames,
    validate_verdict,
)
from micforyou.product import ProductConfig, load_config, save_config


def latency_report(**changes):
    inner = dict(status="COMPLETED", length_match=True, nonfinite_samples=0,
                 underrun_ms=0, errors=[],
                 bridge_latency={"latency_ms_p95": 260.0})
    inner.update(changes)
    return {"bridge_internal": inner}


def benchmark_payload(frames_rtf):
    return {"schema": "micforyou/onnx-cpu-benchmark/1", "candidates": [
        {"frames_per_chunk": frames, "intra_op_threads": "1",
         "processing_rtf": rtf, "model_call_ms_p95": 30.0, "model_calls": 100,
         "input_samples": 480000, "output_samples": 480000,
         "nonfinite_samples": 0, "error": None, "length_match": True}
        for frames, rtf in frames_rtf]}


def registered_config(root: Path, name: str = "c0ffee", **changes) -> ProductConfig:
    """A bundle-managed config whose voice lives in registrations/<name>."""
    folder = root / "registrations" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "core.onnx").write_bytes(b"onnx-" + name.encode())
    (folder / "enrollment.wav").write_bytes(b"wav-" + name.encode())
    values = dict(input_device="Mic", model_repo=root / "vendor",
                  model_dir=root / "models", enrollment=folder / "enrollment.wav",
                  onnx_model=folder / "core.onnx",
                  runtime_python=root / "python", project_root=root,
                  bundle_managed=True)
    values.update(changes)
    return ProductConfig(**values)


def config(tmp_path: Path, **changes) -> ProductConfig:
    values = dict(input_device="Mic", model_repo=tmp_path / "vendor",
                  model_dir=tmp_path / "models", enrollment=tmp_path / "voice.wav",
                  onnx_model=tmp_path / "core.onnx",
                  runtime_python=tmp_path / "python", project_root=tmp_path,
                  bundle_managed=True)
    values.update(changes)
    return ProductConfig(**values)


def write_voice_files(folder: Path) -> None:
    (folder / "core.onnx").write_bytes(b"onnx-bytes")
    (folder / "voice.wav").write_bytes(b"wav-bytes")


def pass_verdict(cfg: ProductConfig, bundle_root: Path | None,
                 **changes) -> dict:
    payload = {
        "schema": performance.VERDICT_SCHEMA,
        "verdict": "pass", "reason": None, "approved_trial": False,
        "frames_per_chunk": cfg.frames_per_chunk, "prefill_ms": cfg.prefill_ms,
        "identity": performance.identity(cfg.input_device, cfg.onnx_model,
                                         cfg.enrollment, bundle_root),
        "candidate_token": "c0ffee", "attempt_id": "a0ffee",
        "latency_ms_p95": 260.0}
    payload.update(changes)
    return payload


def test_classify_latency_pass_warning_and_blocks():
    assert classify_latency(latency_report())[0] == "pass"
    assert classify_latency(latency_report(
        bridge_latency={"latency_ms_p95": 450.0}))[0] == "latency_warning"
    for changes, reason in [
        (dict(status="FAULT"), "fault"),
        (dict(length_match=False), "length_mismatch"),
        (dict(nonfinite_samples=2), "nonfinite_output"),
        (dict(underrun_ms=5), "underrun"),
        (dict(bridge_latency={"latency_ms_p95": None}), "invalid_report"),
    ]:
        verdict, why, _ = classify_latency(latency_report(**changes))
        assert (verdict, why) == ("blocked", reason)
    assert classify_latency({"bridge_internal": None})[1] == "invalid_report"


def test_classify_latency_rejects_malformed_numbers_without_raising():
    """NaN/negative/typed-wrong fields are invalid reports, never passes."""
    for changes in [
        dict(underrun_ms=float("nan")),
        dict(underrun_ms=None),
        dict(underrun_ms="0"),
        dict(underrun_ms=True),
        dict(underrun_ms=-1.0),
        dict(bridge_latency={"latency_ms_p95": float("inf")}),
        dict(bridge_latency={"latency_ms_p95": "260"}),
        dict(bridge_latency={"latency_ms_p95": -5.0}),
        dict(bridge_latency={"latency_ms_p95": True}),
        dict(status=["COMPLETED"]),
        dict(length_match="yes"),
        dict(nonfinite_samples="0"),
        dict(nonfinite_samples=0.0),
    ]:
        verdict, why, _ = classify_latency(latency_report(**changes))
        assert verdict == "blocked", changes
        assert why in {"invalid_report", "underrun", "nonfinite_output"}, (changes, why)
    # A payload that is not even a report must not raise.
    assert classify_latency(["junk"])[1] == "invalid_report"
    assert classify_latency({})[1] == "invalid_report"


def test_eligible_frames_are_latency_first_and_bounded():
    assert eligible_frames(benchmark_payload([(24, 0.45), (16, 0.62), (8, 0.79)])) == [8, 16, 24]
    assert eligible_frames(benchmark_payload([(8, 0.9)])) == []
    assert eligible_frames(benchmark_payload(
        [(8, 0.5), (16, 0.5), (24, 0.5), (32, 0.5)])) == [8, 16, 24]
    with pytest.raises(ValueError):
        eligible_frames({"schema": "other"})


def test_choose_best_prefers_pass_then_fastest_warning():
    items = [
        {"verdict": "latency_warning", "metrics": {"latency_ms_p95": 480.0}},
        {"verdict": "pass", "metrics": {"latency_ms_p95": 380.0}},
    ]
    assert choose_best(items)["verdict"] == "pass"
    items = [
        {"verdict": "latency_warning", "metrics": {"latency_ms_p95": 520.0}},
        {"verdict": "latency_warning", "metrics": {"latency_ms_p95": 430.0}},
    ]
    assert choose_best(items)["metrics"]["latency_ms_p95"] == 430.0
    assert choose_best([{"verdict": "blocked", "metrics": {}}]) is None


def test_validate_verdict_rejects_hostile_shapes(tmp_path: Path):
    cfg = registered_config(tmp_path)
    good = pass_verdict(cfg, None)
    assert validate_verdict(good) is None
    for changes, why in [
        ({"verdict": "PASS"}, "verdict"),
        ({"approved_trial": "yes"}, "approved_trial"),
        ({"frames_per_chunk": True}, "frames_per_chunk"),
        ({"frames_per_chunk": 0}, "frames_per_chunk"),
        ({"prefill_ms": float("nan")}, "prefill_ms"),
        ({"prefill_ms": -100.0}, "prefill_ms"),
        ({"latency_ms_p95": float("nan")}, "latency_ms_p95"),
        ({"identity": "Mic"}, "identity"),
        ({"identity": {"input_device": "Mic", "onnx_sha256": None,
                       "enrollment_sha256": "h", "app_version": "v"}}, "identity.incomplete"),
    ]:
        payload = {**good, **changes}
        assert validate_verdict(payload) == why, changes


def test_admission_requires_verdict_for_bundled_configs(tmp_path: Path):
    cfg = registered_config(tmp_path)
    path = tmp_path / "config.json"
    save_config(cfg, path)
    assert admission(cfg, None, path) == ("deny", "unchecked")

    # A verdict written by an older build (no frames/prefill binding, no
    # enrollment/build identity) must not silently authorize the new build.
    performance.write_candidate_verdict(cfg.enrollment.parent,
                                        {"verdict": "pass", "identity": {
                                            "input_device": "Mic", "onnx_sha256": None,
                                            "app_version": "dev"}})
    assert admission(cfg, None, path) == ("deny", "invalid_verdict")

    performance.write_candidate_verdict(cfg.enrollment.parent, pass_verdict(cfg, None))
    assert admission(cfg, None, path) == ("allow", None)

    performance.write_candidate_verdict(
        cfg.enrollment.parent,
        pass_verdict(cfg, None, verdict="latency_warning", approved_trial=False))
    assert admission(cfg, None, path) == ("warn_trial", "high_latency")

    performance.write_candidate_verdict(
        cfg.enrollment.parent,
        pass_verdict(cfg, None, verdict="latency_warning", approved_trial=True))
    assert admission(cfg, None, path)[0] == "allow"

    changed = registered_config(tmp_path, name="c0ffee", input_device="Other Mic")
    assert admission(changed, None, path) == ("deny", "device_changed")

    dev = registered_config(tmp_path, name="c0ffee", bundle_managed=False)
    assert admission(dev, None, path) == ("allow", None)


def test_admission_binds_model_enrollment_params_and_build(tmp_path: Path):
    (tmp_path / "bundle-manifest.json").write_text(
        json.dumps({"version": "0.2.3", "build": "8"}))
    cfg = registered_config(tmp_path)
    path = tmp_path / "config.json"
    save_config(cfg, path)
    performance.write_candidate_verdict(cfg.enrollment.parent, pass_verdict(cfg, tmp_path))
    assert admission(cfg, tmp_path, path)[0] == "allow"

    (cfg.onnx_model).write_bytes(b"model-b")
    assert admission(cfg, tmp_path, path) == ("deny", "model_changed")
    (cfg.onnx_model).write_bytes(b"onnx-c0ffee")

    (cfg.enrollment).write_bytes(b"other-recording")
    assert admission(cfg, tmp_path, path) == ("deny", "enrollment_changed")
    (cfg.enrollment).write_bytes(b"wav-c0ffee")

    reparameterized = registered_config(tmp_path, frames_per_chunk=24)
    assert admission(reparameterized, tmp_path, path) == ("deny", "params_changed")

    # Same version, different build: the old verdict no longer applies.
    (tmp_path / "bundle-manifest.json").write_text(
        json.dumps({"version": "0.2.3", "build": "9"}))
    assert admission(cfg, tmp_path, path) == ("deny", "version_changed")
    (tmp_path / "bundle-manifest.json").write_text(json.dumps({"version": "0.2.3"}))
    assert admission(cfg, tmp_path, path) == ("deny", "version_changed")

    # Missing model files fail closed.
    (cfg.onnx_model).unlink()
    assert admission(cfg, tmp_path, path) == ("deny", "model_missing")


def test_pending_failure_never_overrides_active_authorization(tmp_path: Path):
    """P1: a new candidate's blocked verdict must not disable the old active."""
    (tmp_path / "bundle-manifest.json").write_text(
        json.dumps({"version": "0.2.3", "build": "8"}))
    active = registered_config(tmp_path, name="activeold")
    path = tmp_path / "config.json"
    save_config(active, path)
    performance.write_candidate_verdict(active.enrollment.parent,
                                        pass_verdict(active, tmp_path))
    original_verdict = (active.enrollment.parent / "performance.json").read_text()

    # A later registration fails its performance check: its verdict lives in
    # its own candidate folder; the active folder is never touched.
    pending = registered_config(tmp_path, name="newvoice01")
    performance.write_candidate_verdict(pending.enrollment.parent, {
        "schema": performance.VERDICT_SCHEMA,
        "verdict": "blocked", "reason": "fault", "approved_trial": False,
        "frames_per_chunk": 8, "prefill_ms": 100.0,
        "identity": performance.identity("Mic", pending.onnx_model,
                                         pending.enrollment, tmp_path),
        "candidate_token": "newvoice01", "attempt_id": "attempt001",
        "latency_ms_p95": None})
    performance.write_candidate_verdict(
        pending.enrollment.parent,
        pass_verdict(pending, tmp_path, verdict="latency_warning", approved_trial=False))

    # FAULT / insufficient speed / unapproved warning / cancel on the pending
    # side: the active registration stays allowed and its verdict untouched.
    for _ in range(4):
        assert admission(active, tmp_path, path) == ("allow", None)
    assert (active.enrollment.parent / "performance.json").read_text() == original_verdict


def test_commit_failure_leaves_old_pair_intact_and_candidate_retestable(
        tmp_path: Path, monkeypatch):
    """P1 round 2: an interrupted commit must never mismatch the pair.

    Injected failures at the verdict write or the final config rename each
    leave the old config + old verdict complete and usable, with the new
    candidate fully written and retestable/approvable.
    """
    (tmp_path / "bundle-manifest.json").write_text(
        json.dumps({"version": "0.2.3", "build": "8"}))
    old = registered_config(tmp_path, name="oldpair")
    new = registered_config(tmp_path, name="newpair")
    path = tmp_path / "config.json"
    save_config(old, path)
    performance.write_candidate_verdict(old.enrollment.parent, pass_verdict(old, tmp_path))
    assert admission(old, tmp_path, path) == ("allow", None)
    old_config_bytes = path.read_bytes()
    old_verdict_bytes = (old.enrollment.parent / "performance.json").read_bytes()

    verdict = pass_verdict(new, tmp_path)

    # Failure at the final config rename: old pair intact, new candidate
    # fully written (its verdict is part of its folder), still committable.
    real_replace = Path.replace

    def fail_config_rename(source, target):
        if source.name == "config.json.tmp":
            raise OSError("injected final config rename failure")
        return real_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_config_rename)
    with pytest.raises(OSError):
        performance.commit_candidate(new, path, verdict)
    assert path.read_bytes() == old_config_bytes
    assert (old.enrollment.parent / "performance.json").read_bytes() == old_verdict_bytes
    assert admission(old, tmp_path, path) == ("allow", None)
    stored = performance.read_candidate_verdict(new.enrollment.parent)
    assert stored["verdict"] == "pass"

    # After the transient failure clears, the same commit succeeds and the
    # new pair is complete and allowed.
    monkeypatch.setattr(Path, "replace", real_replace)
    performance.commit_candidate(new, path, verdict)
    assert admission(new, tmp_path, path) == ("allow", None)
    assert load_config(path).enrollment == new.enrollment

    # Failure while writing the new candidate's verdict: nothing changed at
    # all — old pair intact, new folder has no verdict, commit raised.
    monkeypatch.setattr(Path, "write_text", lambda self, *a, **k: (
        (_ for _ in ()).throw(OSError("injected verdict write failure"))
        if self.name == "performance.json" and self.parent.name == "newpair2"
        else real_write_text(self, *a, **k)))
    old2 = registered_config(tmp_path, name="oldpair2")
    new2 = registered_config(tmp_path, name="newpair2")
    save_config(old2, path)
    performance.write_candidate_verdict(old2.enrollment.parent, pass_verdict(old2, tmp_path))
    with pytest.raises(OSError):
        performance.commit_candidate(new2, path, pass_verdict(new2, tmp_path))
    assert load_config(path).enrollment == old2.enrollment
    assert performance.read_candidate_verdict(new2.enrollment.parent) is None
    assert admission(old2, tmp_path, path) == ("allow", None)


def test_attempt_records_are_bounded(tmp_path: Path):
    config_path = tmp_path / "config.json"
    for index in range(7):
        performance.record_attempt(config_path, {"attempt_id": str(index)})
    records = sorted((tmp_path / "performance-attempts").glob("attempt-*.json"))
    assert len(records) == performance.MAX_ATTEMPT_RECORDS


def test_attempt_folders_are_bounded(tmp_path: Path):
    folder = tmp_path / "registrations" / "c0ffee"
    attempts = folder / "attempts"
    for index in range(7):
        (attempts / f"attempt{index:02d}").mkdir(parents=True)
    performance.prune_attempt_folders(folder)
    assert len(list(attempts.iterdir())) == performance.MAX_ATTEMPT_RECORDS


real_write_text = Path.write_text


def _retest_fixture(tmp_path: Path, monkeypatch) -> tuple:
    from micforyou import setup
    from micforyou.audio import Device

    bundle = tmp_path / "Bundle/Runtime"
    bundle.mkdir(parents=True)
    (bundle / "bundle-manifest.json").write_text(json.dumps({"version": "0.2.3"}))
    monkeypatch.setenv("MICFORYOU_BUNDLE_ROOT", str(bundle))
    config_path = tmp_path / "userdata/config.json"
    token = "savedvoice01"
    folder = config_path.parent / "registrations" / token
    folder.mkdir(parents=True)
    (folder / "core.onnx").write_bytes(b"onnx")
    (folder / "enrollment.wav").write_bytes(b"wav")
    (config_path.parent / "pending-candidate.json").write_text(json.dumps(
        {"token": token, "input_device": "Mic", "frames_per_chunk": 8,
         "prefill_ms": 100.0}))
    monkeypatch.setattr(setup, "same_worker", lambda job: True)
    monkeypatch.setattr(setup.signal, "signal", lambda *a: None)
    devices = [Device(0, "Mic", 0, 1, 0, 48000),
               Device(1, "BlackHole 2ch", 0, 2, 2, 48000)]
    monkeypatch.setattr(setup, "list_devices", lambda: devices)
    monkeypatch.setattr(setup, "record_input",
                        lambda *a, **k: pytest.fail("retest must not record"))
    from micforyou import cli
    monkeypatch.setattr(cli, "require_inactive", lambda *a: None)
    return setup, config_path, folder, bundle


def test_worker_performance_stage_reuses_voice_without_recording(
        tmp_path: Path, monkeypatch):
    setup, config_path, folder, bundle = _retest_fixture(tmp_path, monkeypatch)
    save = setup.save_job
    save(config_path, dict(status="RUNNING", stage="retest", progress=0,
                           token="retest-token", pid=0, voice="saved",
                           performance="checking"))

    def run(command, **kwargs):
        name = Path(command[1]).name
        if name == "benchmark_onnx_tse.py":
            Path(command[command.index("--result") + 1]).write_text(json.dumps(
                benchmark_payload([(8, 0.5)])))
        elif name == "measure_bridge_latency.py":
            Path(command[command.index("--result") + 1]).write_text(
                json.dumps(latency_report()))
        else:
            pytest.fail(str(command))
    monkeypatch.setattr(setup.subprocess, "run", run)

    setup.run_worker(config_path, "Mic", "retest-token", stage="performance")
    job = setup.read_job(config_path)
    assert job["status"] == "READY" and job["performance"] == "pass"
    # The committed verdict lives inside the candidate folder the config now
    # points at — one folder, one pair.
    assert performance.read_candidate_verdict(folder)["verdict"] == "pass"
    from micforyou.product import load_config
    assert load_config(config_path).enrollment.parent == folder
    assert admission(load_config(config_path), bundle, config_path) == ("allow", None)
    attempt_dir = folder / "attempts" / "retest-token"
    assert (attempt_dir / "benchmark.json").is_file()
    assert (attempt_dir / "latency-8-100.json").is_file()
    # Attempt identity is the worker token, distinct from the candidate.
    records = sorted((config_path.parent / "performance-attempts").glob("attempt-*.json"))
    attempt = json.loads(records[-1].read_text())
    assert attempt["attempt_id"] == "retest-token"
    assert attempt["candidate_token"] == "savedvoice01"
    assert attempt["outcome"] == "ready"


def test_worker_records_terminal_attempts_for_failures(tmp_path: Path, monkeypatch):
    setup, config_path, folder, bundle = _retest_fixture(tmp_path, monkeypatch)
    save = setup.save_job
    save(config_path, dict(status="RUNNING", stage="retest", progress=0,
                           token="failingtok", pid=0, voice="saved",
                           performance="checking"))

    def run(command, **kwargs):
        name = Path(command[1]).name
        if name == "benchmark_onnx_tse.py":
            Path(command[command.index("--result") + 1]).write_text(json.dumps(
                benchmark_payload([(8, 0.5)])))
        elif name == "measure_bridge_latency.py":
            Path(command[command.index("--result") + 1]).write_text(json.dumps(
                latency_report(status="FAULT", errors=["output queue exceeded"])))
        else:
            pytest.fail(str(command))
    monkeypatch.setattr(setup.subprocess, "run", run)

    with pytest.raises(ValueError):
        setup.run_worker(config_path, "Mic", "failingtok", stage="performance")
    job = setup.read_job(config_path)
    assert job["status"] == "FAILED" and job["voice"] == "saved"
    assert job["performance"] == "blocked"
    records = sorted((config_path.parent / "performance-attempts").glob("attempt-*.json"))
    attempt = json.loads(records[-1].read_text())
    assert attempt["attempt_id"] == "failingtok"
    assert attempt["outcome"] == "blocked"
    assert performance.read_candidate_verdict(folder)["verdict"] == "blocked"


def test_start_retest_requires_saved_candidate_and_marker(tmp_path: Path, monkeypatch):
    from micforyou import setup
    config_path = tmp_path / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    bundle = tmp_path / "Bundle/Runtime"
    bundle.mkdir(parents=True)
    (bundle / "bundle-manifest.json").write_text("{}")
    monkeypatch.setenv("MICFORYOU_BUNDLE_ROOT", str(bundle))
    with pytest.raises(ValueError, match="候选"):
        setup.start_retest(config_path)

    (config_path.parent / "pending-candidate.json").write_text(json.dumps(
        {"token": "tttttttt", "input_device": "Mic", "frames_per_chunk": 8,
         "prefill_ms": 100.0}))
    folder = config_path.parent / "registrations" / "tttttttt"
    folder.mkdir(parents=True)
    (folder / "core.onnx").write_bytes(b"onnx")
    (folder / "enrollment.wav").write_bytes(b"wav")

    from micforyou.uninstall import begin_uninstall_window
    begin_uninstall_window(config_path.parent)
    try:
        with pytest.raises(ValueError, match="卸载"):
            setup.start_retest(config_path)
    finally:
        from micforyou.uninstall import end_uninstall_window
        end_uninstall_window(config_path.parent)


def test_start_retest_adopts_legacy_full_app_registration(tmp_path: Path, monkeypatch):
    """A pre-verdict-era registration can be re-checked without re-reading."""
    from micforyou import setup
    from micforyou.audio import Device
    from micforyou.product import save_config
    bundle = tmp_path / "Bundle/Runtime"
    bundle.mkdir(parents=True)
    (bundle / "bundle-manifest.json").write_text(json.dumps({"version": "0.2.3"}))
    monkeypatch.setenv("MICFORYOU_BUNDLE_ROOT", str(bundle))
    config_path = tmp_path / "userdata/config.json"
    folder = config_path.parent / "registrations" / "legacyvoice"
    folder.mkdir(parents=True)
    (folder / "core.onnx").write_bytes(b"onnx")
    (folder / "enrollment.wav").write_bytes(b"wav")
    legacy = ProductConfig(
        input_device="Mic", model_repo=bundle / "vendor",
        model_dir=bundle / "models/tfmap_context_causal_100",
        enrollment=folder / "enrollment.wav", onnx_model=folder / "core.onnx",
        runtime_python=bundle / "python/bin/python3.12", project_root=bundle,
        bundle_managed=True, frames_per_chunk=24, prefill_ms=150.0)
    save_config(legacy, config_path)

    monkeypatch.setattr(setup, "list_devices", lambda: [
        Device(0, "Mic", 0, 1, 0, 48000), Device(1, "BlackHole 2ch", 0, 2, 2, 48000)])
    monkeypatch.setattr(setup, "resolve_device", lambda *a: None)
    from micforyou import cli
    monkeypatch.setattr(cli, "require_inactive", lambda *a: None)
    launched = []
    monkeypatch.setattr(setup.subprocess, "Popen",
                        lambda command, **kwargs: launched.append(command) or type(
                            "P", (), {"pid": 4321})())
    job = setup.start_retest(config_path)
    assert job["status"] == "RUNNING" and job["voice"] == "saved"
    assert "--stage" in launched[0] and launched[0][
        launched[0].index("--stage") + 1] == "performance"
    pending = setup.read_pending_candidate(config_path)
    assert pending["token"] == "legacyvoice"
    assert pending["adopted_from_active"] is True
    assert setup.read_job(config_path)["status"] == "RUNNING"
    # Adoption never fabricates a pass verdict for the old record.
    assert performance.read_candidate_verdict(folder) is None


def _approvable_candidate(tmp_path: Path, monkeypatch, bundle) -> tuple:
    from micforyou import setup
    from micforyou import cli
    config_path = tmp_path / "userdata/config.json"
    token = "warned001"
    folder = config_path.parent / "registrations" / token
    folder.mkdir(parents=True)
    (folder / "core.onnx").write_bytes(b"onnx")
    (folder / "enrollment.wav").write_bytes(b"wav")
    (config_path.parent / "pending-candidate.json").write_text(json.dumps(
        {"token": token, "input_device": "Mic", "frames_per_chunk": 16,
         "prefill_ms": 150.0}))
    ident = performance.identity("Mic", folder / "core.onnx",
                                 folder / "enrollment.wav", bundle)
    performance.write_candidate_verdict(folder, {
        "schema": performance.VERDICT_SCHEMA,
        "verdict": "latency_warning", "reason": "high_latency",
        "approved_trial": False, "frames_per_chunk": 16, "prefill_ms": 150.0,
        "identity": ident, "candidate_token": token, "attempt_id": "attempt001",
        "latency_ms_p95": 521.0})
    setup.save_job(config_path, dict(
        status="WAITING", stage="等待确认", progress=1.0, token="windowtok",
        voice="saved", performance="latency_warning"))
    monkeypatch.setattr(cli, "require_inactive", lambda *a: None)
    monkeypatch.setattr(setup, "same_worker", lambda job: False)
    return setup, config_path, folder, token


def test_approve_trial_enables_warning_candidate(tmp_path: Path, monkeypatch):
    bundle = tmp_path / "Bundle/Runtime"
    bundle.mkdir(parents=True)
    (bundle / "bundle-manifest.json").write_text(
        json.dumps({"version": "0.2.3", "build": "8"}))
    monkeypatch.setenv("MICFORYOU_BUNDLE_ROOT", str(bundle))
    setup, config_path, folder, token = _approvable_candidate(tmp_path, monkeypatch, bundle)

    result = setup.approve_trial(config_path)
    assert result["status"] == "READY" and result["approved_trial"] is True
    assert result["token"] == "windowtok"  # the waiting window completes
    published = performance.read_candidate_verdict(folder)
    assert published["verdict"] == "latency_warning"
    assert published["approved_trial"] is True
    saved = load_config(config_path)
    assert saved.frames_per_chunk == 16 and saved.prefill_ms == 150.0
    assert saved.bundle_managed is True
    assert saved.enrollment.parent == folder
    job = setup.read_job(config_path)
    assert job["status"] == "READY" and job["token"] == "windowtok"
    assert job["performance"] == "latency_warning"
    # Admission now allows the approved trial against the active folder.
    assert admission(saved, bundle, config_path) == ("allow", None)


def test_approve_trial_commit_failure_is_retryable(tmp_path: Path, monkeypatch):
    """An approve interrupted at the config rename stays WAITING and retryable."""
    bundle = tmp_path / "Bundle/Runtime"
    bundle.mkdir(parents=True)
    (bundle / "bundle-manifest.json").write_text(
        json.dumps({"version": "0.2.3", "build": "8"}))
    monkeypatch.setenv("MICFORYOU_BUNDLE_ROOT", str(bundle))
    setup, config_path, folder, token = _approvable_candidate(tmp_path, monkeypatch, bundle)
    real_replace = Path.replace

    def fail_config_rename(source, target):
        if source.name == "config.json.tmp":
            raise OSError("injected config write failure during approval")
        return real_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_config_rename)
    with pytest.raises(OSError):
        setup.approve_trial(config_path)
    monkeypatch.setattr(Path, "replace", real_replace)
    # The waiting job is untouched; the approval can simply be repeated.
    assert setup.read_job(config_path)["status"] == "WAITING"
    result = setup.approve_trial(config_path)
    assert result["status"] == "READY"


def test_approve_trial_rejects_races_and_stale_candidates(tmp_path: Path, monkeypatch):
    from micforyou import setup
    from micforyou.uninstall import begin_uninstall_window, end_uninstall_window
    bundle = tmp_path / "Bundle/Runtime"
    bundle.mkdir(parents=True)
    (bundle / "bundle-manifest.json").write_text(json.dumps({"version": "0.2.3"}))
    monkeypatch.setenv("MICFORYOU_BUNDLE_ROOT", str(bundle))
    setup, config_path, folder, token = _approvable_candidate(tmp_path, monkeypatch, bundle)

    # A running worker forbids approval.
    monkeypatch.setattr(setup, "same_worker", lambda job: False)
    original_status = setup.setup_status
    running = setup.read_job(config_path)
    running.update(status="RUNNING", pid=999999)
    monkeypatch.setattr(setup, "setup_status", lambda *a: running)
    with pytest.raises(ValueError, match="正在进行"):
        setup.approve_trial(config_path)
    monkeypatch.setattr(setup, "setup_status", original_status)
    setup.save_job(config_path, dict(status="WAITING", stage="等待确认",
                                     progress=1.0, token="windowtok", voice="saved",
                                     performance="latency_warning"))

    # Uninstall takeover forbids approval.
    begin_uninstall_window(config_path.parent)
    try:
        with pytest.raises(ValueError, match="卸载"):
            setup.approve_trial(config_path)
    finally:
        end_uninstall_window(config_path.parent)

    # Live filtering forbids approval.
    from micforyou import cli

    def busy(config_path_arg):
        raise ValueError("end MicForYou before changing its configuration")
    monkeypatch.setattr(cli, "require_inactive", busy)
    with pytest.raises(ValueError, match="end MicForYou"):
        setup.approve_trial(config_path)
    monkeypatch.setattr(cli, "require_inactive", lambda *a: None)

    # A verdict replaced by a newer attempt cannot be approved.
    replaced = performance.read_candidate_verdict(folder)
    replaced["candidate_token"] = "newervoice"
    performance.write_candidate_verdict(folder, replaced)
    with pytest.raises(ValueError, match="替换"):
        setup.approve_trial(config_path)

    # A tampered verdict (files no longer match) is rejected.
    replaced["candidate_token"] = token
    performance.write_candidate_verdict(folder, replaced)
    (folder / "core.onnx").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="不一致"):
        setup.approve_trial(config_path)

    # Nothing was committed to an active config.
    assert not config_path.exists()


def test_status_ready_and_retest_mirror_admission(tmp_path: Path, monkeypatch, capsys):
    """Menu "ready" and the retest entry must match what the backend allows."""
    from micforyou import cli
    from micforyou.audio import Device
    from micforyou.product import save_config
    bundle = tmp_path / "Bundle/Runtime"
    bundle.mkdir(parents=True)
    (bundle / "bundle-manifest.json").write_text(
        json.dumps({"version": "0.2.3", "build": "8"}))
    monkeypatch.setenv("MICFORYOU_BUNDLE_ROOT", str(bundle))
    config_path = tmp_path / "userdata/config.json"
    active = registered_config(tmp_path / "userdata", name="activereg")
    save_config(active, config_path)
    monkeypatch.setattr(cli, "product_status", lambda config: {
        "ready": True, "input_device": config.input_device,
        "output_device": config.output_device, "fault_policy": "silence",
        "paths": {}, "device_errors": [], "system_default_input_unchanged": True})

    def run_status():
        args = cli.build_parser().parse_args(["status", "--config", str(config_path)])
        cli.command_status(args)
        return json.loads(capsys.readouterr().out)

    # No verdict yet: not ready, but the active voice is adoptable for a
    # no-reread retest — exactly the legacy-upgrade scenario.
    value = run_status()
    assert value["ready"] is False
    assert value["admission"] == {"decision": "deny", "reason": "unchecked"}
    assert value["retest_available"] is True

    # A passing verdict for the current build: ready and allowed.
    performance.write_candidate_verdict(active.enrollment.parent,
                                        pass_verdict(active, bundle))
    value = run_status()
    assert value["ready"] is True and value["admission"]["decision"] == "allow"

    # Same version, new build: verdict invalidated — ready flips to false
    # with the retest entry still available (no re-recording needed).
    (bundle / "bundle-manifest.json").write_text(
        json.dumps({"version": "0.2.3", "build": "9"}))
    value = run_status()
    assert value["ready"] is False
    assert value["admission"] == {"decision": "deny", "reason": "version_changed"}
    assert value["retest_available"] is True

    # An unapproved warning blocks ready but stays retestable.
    performance.write_candidate_verdict(
        active.enrollment.parent,
        pass_verdict(active, bundle, verdict="latency_warning", approved_trial=False))
    value = run_status()
    assert value["ready"] is False
    assert value["admission"]["decision"] == "warn_trial"
    assert value["retest_available"] is True
    _ = Device  # imported for parity with sibling fixtures
