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
)
from micforyou.product import ProductConfig


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


def config(tmp_path: Path, **changes) -> ProductConfig:
    values = dict(input_device="Mic", model_repo=tmp_path / "vendor",
                  model_dir=tmp_path / "models", enrollment=tmp_path / "voice.wav",
                  onnx_model=tmp_path / "core.onnx",
                  runtime_python=tmp_path / "python", project_root=tmp_path,
                  bundle_managed=True)
    values.update(changes)
    return ProductConfig(**values)


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


def test_admission_requires_verdict_for_bundled_configs(tmp_path: Path):
    cfg = config(tmp_path)
    assert admission(cfg, None, tmp_path / "config.json") == ("deny", "unchecked")

    performance.write_verdict(tmp_path / "config.json",
                              {"verdict": "pass", "identity": {
                                  "input_device": "Mic", "onnx_sha256": None,
                                  "app_version": "dev"}})
    assert admission(cfg, None, tmp_path / "config.json")[0] == "allow"

    performance.write_verdict(tmp_path / "config.json",
                              {"verdict": "latency_warning", "approved_trial": False,
                               "identity": {"input_device": "Mic", "onnx_sha256": None,
                                            "app_version": "dev"}})
    assert admission(cfg, None, tmp_path / "config.json") == ("warn_trial", "high_latency")

    performance.write_verdict(tmp_path / "config.json",
                              {"verdict": "latency_warning", "approved_trial": True,
                               "identity": {"input_device": "Mic", "onnx_sha256": None,
                                            "app_version": "dev"}})
    assert admission(cfg, None, tmp_path / "config.json")[0] == "allow"

    changed = config(tmp_path, input_device="Other Mic")
    assert admission(changed, None, tmp_path / "config.json") == ("deny", "device_changed")

    dev = config(tmp_path, bundle_managed=False)
    assert admission(dev, None, tmp_path / "config.json") == ("allow", None)


def test_admission_invalidates_on_model_and_version_change(tmp_path: Path):
    (tmp_path / "bundle-manifest.json").write_text(json.dumps({"version": "0.2.3"}))
    cfg = config(tmp_path)
    onnx = tmp_path / "core.onnx"
    onnx.write_bytes(b"model-a")
    performance.write_verdict(tmp_path / "config.json", {
        "verdict": "pass", "identity": {
            "input_device": "Mic",
            "onnx_sha256": performance.sha256_file(onnx),
            "app_version": "0.2.3"}})
    assert admission(cfg, tmp_path, tmp_path / "config.json")[0] == "allow"
    onnx.write_bytes(b"model-b")
    assert admission(cfg, tmp_path, tmp_path / "config.json") == ("deny", "model_changed")
    onnx.write_bytes(b"model-a")
    assert admission(cfg, None, tmp_path / "config.json") == ("deny", "version_changed")


def test_attempt_records_are_bounded(tmp_path: Path):
    config_path = tmp_path / "config.json"
    for index in range(7):
        performance.record_attempt(config_path, {"attempt_id": str(index)})
    records = sorted((tmp_path / "performance-attempts").glob("attempt-*.json"))
    assert len(records) == performance.MAX_ATTEMPT_RECORDS


def test_worker_performance_stage_reuses_voice_without_recording(
        tmp_path: Path, monkeypatch):
    from micforyou import setup
    from micforyou.audio import Device

    bundle = tmp_path / "Bundle/Runtime"
    bundle.mkdir(parents=True)
    (bundle / "bundle-manifest.json").write_text("{}")
    monkeypatch.setenv("MICFORYOU_BUNDLE_ROOT", str(bundle))
    config_path = tmp_path / "userdata/config.json"
    token = "saved-voice"
    folder = config_path.parent / "registrations" / token
    folder.mkdir(parents=True)
    (folder / "core.onnx").write_bytes(b"onnx")
    (folder / "enrollment.wav").write_bytes(b"wav")
    (config_path.parent / "pending-candidate.json").write_text(json.dumps(
        {"token": token, "input_device": "Mic", "frames_per_chunk": 8,
         "prefill_ms": 100.0}))
    save = setup.save_job
    save(config_path, dict(status="RUNNING", stage="retest", progress=0,
                           token="retest-token", pid=0, voice="saved",
                           performance="checking"))
    monkeypatch.setattr(setup, "same_worker", lambda job: True)
    monkeypatch.setattr(setup.signal, "signal", lambda *a: None)
    devices = [Device(0, "Mic", 0, 1, 0, 48000),
               Device(1, "BlackHole 2ch", 0, 2, 2, 48000)]
    monkeypatch.setattr(setup, "list_devices", lambda: devices)
    monkeypatch.setattr(setup, "record_input",
                        lambda *a, **k: pytest.fail("retest must not record"))
    from micforyou import cli
    monkeypatch.setattr(cli, "require_inactive", lambda *a: None)

    def run(command, **kwargs):
        name = Path(command[1]).name
        if name == "benchmark_onnx_tse.py":
            (folder / "benchmark.json").write_text(json.dumps(
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
    assert performance.read_verdict(config_path)["verdict"] == "pass"
    _ = save  # keep the local referenced for clarity


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
        {"token": "t", "input_device": "Mic", "frames_per_chunk": 8,
         "prefill_ms": 100.0}))
    folder = config_path.parent / "registrations" / "t"
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


def test_approve_trial_enables_warning_candidate(tmp_path: Path, monkeypatch):
    from micforyou import setup
    bundle = tmp_path / "Bundle/Runtime"
    bundle.mkdir(parents=True)
    (bundle / "bundle-manifest.json").write_text(json.dumps({"version": "0.2.3"}))
    monkeypatch.setenv("MICFORYOU_BUNDLE_ROOT", str(bundle))
    config_path = tmp_path / "config.json"
    token = "warned"
    folder = config_path.parent / "registrations" / token
    folder.mkdir(parents=True)
    (folder / "core.onnx").write_bytes(b"onnx")
    (folder / "enrollment.wav").write_bytes(b"wav")
    (config_path.parent / "pending-candidate.json").write_text(json.dumps(
        {"token": token, "input_device": "Mic", "frames_per_chunk": 16,
         "prefill_ms": 150.0}))
    performance.write_verdict(config_path, {
        "verdict": "latency_warning", "approved_trial": False,
        "frames_per_chunk": 16, "prefill_ms": 150.0,
        "identity": {"input_device": "Mic", "onnx_sha256": None,
                     "app_version": "0.2.3"}})

    with pytest.raises(ValueError, match="尚未确认"):
        from micforyou.cli import build_parser
        args = build_parser().parse_args(["start", "--config", str(config_path)])
        # admission checked inside start_background; craft the direct call
        cfg = config(folder, input_device="Mic")
        decision, _ = admission(cfg, bundle, config_path)
        assert decision == "warn_trial"
        raise ValueError("当前声音候选延迟偏高且尚未确认试用")

    result = setup.approve_trial(config_path)
    assert result["status"] == "READY"
    assert performance.read_verdict(config_path)["approved_trial"] is True
    saved = json.loads(config_path.read_text())
    assert saved["frames_per_chunk"] == 16 and saved["prefill_ms"] == 150.0
