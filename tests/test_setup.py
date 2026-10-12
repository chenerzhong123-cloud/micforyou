import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from micforyou.product import ProductConfig, load_config, save_config
from micforyou.setup import select_candidate, validate_latency, cancel_setup, save_job
from micforyou.cli import build_parser, command_status


def benchmark(**changes):
    item = dict(intra_op_threads="1", frames_per_chunk=8, processing_rtf=0.5,
                model_call_ms_p95=30, model_calls=100, input_samples=480000,
                output_samples=480000, nonfinite_samples=0, error=None)
    item.update(changes)
    return {"schema": "micforyou/onnx-cpu-benchmark/1", "candidates": [item]}


@pytest.mark.parametrize("changes", [
    {"processing_rtf": 0.81}, {"processing_rtf": math.nan},
    {"model_call_ms_p95": math.inf}, {"output_samples": 400},
    {"nonfinite_samples": 3}, {"error": "failed"},
])
def test_setup_refuses_unfit_or_corrupt_benchmark(changes):
    with pytest.raises(ValueError):
        select_candidate(benchmark(**changes))


def test_setup_selects_valid_candidate():
    assert select_candidate(benchmark())["frames_per_chunk"] == 8


@pytest.mark.parametrize("changes", [
    {"status": "FAULT"}, {"underrun_ms": 10}, {"length_match": False},
    {"nonfinite_samples": 1}, {"bridge_latency": {"latency_ms_p95": 400}},
])
def test_latency_gate_rejects_unstable_route(changes):
    data = dict(status="COMPLETED", underrun_ms=0, length_match=True,
                nonfinite_samples=0, bridge_latency={"latency_ms_p95": 260})
    data.update(changes)
    with pytest.raises(ValueError):
        validate_latency({"bridge_internal": data})


def test_new_user_status_does_not_require_config_or_audio_device(tmp_path, capsys):
    command_status(build_parser().parse_args(["status", "--config", str(tmp_path / "config.json")]))
    value = json.loads(capsys.readouterr().out)
    assert not value["ready"] and not value["configured"]
    assert value["runtime"]["status"] == "STOPPED"


@pytest.mark.parametrize("command", ["status", "start"])
def test_complete_app_requires_setup_instead_of_starting_old_developer_environment(
        tmp_path, monkeypatch, capsys, command):
    from micforyou import cli
    config = tmp_path / "config.json"
    legacy = ProductConfig(input_device="Mic", model_repo=tmp_path / "old/vendor",
        model_dir=tmp_path / "old/models", enrollment=tmp_path / "old/voice.wav",
        onnx_model=tmp_path / "old/core.onnx", runtime_python=tmp_path / "old/venv/python",
        project_root=tmp_path / "old")
    save_config(legacy, config)
    original = config.read_bytes()
    monkeypatch.setenv("MICFORYOU_BUNDLE_ROOT", str(tmp_path / "complete/Runtime"))
    monkeypatch.setattr(cli, "product_status", lambda *a: pytest.fail("developer resources queried"))
    monkeypatch.setattr(cli, "start_background", lambda *a: pytest.fail("developer runtime started"))
    args = build_parser().parse_args([command, "--config", str(config)])
    if command == "status":
        cli.command_status(args)
        status = json.loads(capsys.readouterr().out)
        assert not status["ready"] and status["needs_bundle_setup"]
        assert status["input_device"] == "Mic"
    else:
        with pytest.raises(ValueError, match="重新注册"):
            cli.command_start(args)
    assert config.read_bytes() == original


def test_moved_bundle_rebinds_resources_but_retains_personal_data(tmp_path, monkeypatch):
    original = ProductConfig(
        input_device="Mic", model_repo=tmp_path / "old/vendor",
        model_dir=tmp_path / "old/models", enrollment=tmp_path / "user/voice.wav",
        onnx_model=tmp_path / "user/core.onnx", runtime_python=tmp_path / "old/python",
        project_root=tmp_path / "old", bundle_managed=True)
    save_config(original, tmp_path / "config.json")
    moved = tmp_path / "moved app/Runtime"
    monkeypatch.setenv("MICFORYOU_BUNDLE_ROOT", str(moved))
    loaded = load_config(tmp_path / "config.json")
    assert loaded.project_root == moved
    assert loaded.runtime_python == moved / "python/bin/python3.12"
    assert loaded.enrollment == original.enrollment
    assert loaded.onnx_model == original.onnx_model
    assert original == load_config_legacy(tmp_path, monkeypatch, original)


def load_config_legacy(tmp_path, monkeypatch, original):
    save_config(replace(original, bundle_managed=False), tmp_path / "config.json")
    return replace(load_config(tmp_path / "config.json"), bundle_managed=True)


def test_cancel_does_not_signal_reused_pid(tmp_path, monkeypatch):
    from micforyou import setup
    config = tmp_path / "config.json"
    save_job(config, {"status": "RUNNING", "token": "wrong-token", "pid": 123})
    monkeypatch.setattr(setup, "same_worker", lambda job: False)
    monkeypatch.setattr(setup.os, "killpg", lambda *a: pytest.fail("unrelated PID signaled"))
    cancel_setup(config)


@pytest.mark.parametrize("failure", ["performance", "cancel", "latency", "retry", "quality", None])
def test_setup_transaction_preserves_previous_registration_until_all_checks_pass(
        tmp_path, monkeypatch, failure):
    import os
    import numpy as np
    import soundfile as sf
    from micforyou import setup
    from micforyou.audio import Device
    bundle = tmp_path / "Bundle/Runtime"
    bundle.mkdir(parents=True)
    (bundle / "bundle-manifest.json").write_text("{}")
    monkeypatch.setenv("MICFORYOU_BUNDLE_ROOT", str(bundle))
    config_path = tmp_path / "userdata/config.json"
    previous = ProductConfig(input_device="Mic", model_repo=bundle / "vendor",
        model_dir=bundle / "models", enrollment=tmp_path / "old.wav",
        onnx_model=tmp_path / "old.onnx", runtime_python=Path("/old/python"),
        project_root=bundle)
    save_config(previous, config_path)
    original = config_path.read_bytes()
    previous.enrollment.write_bytes(b"old voice")
    previous.onnx_model.write_bytes(b"old model")
    token = "test-registration"
    save_job(config_path, dict(status="RUNNING", stage="prepare", progress=0,
                              token=token, pid=os.getpid()))
    monkeypatch.setattr(setup, "same_worker", lambda job: True)
    monkeypatch.setattr(setup.signal, "signal", lambda *a: None)
    devices = [Device(0, "Mic", 0, 1, 0, 48000),
               Device(1, "BlackHole 2ch", 0, 2, 2, 48000)]
    monkeypatch.setattr(setup, "list_devices", lambda: devices)

    def synthetic_speech(seconds: float, rate: int = 48000) -> np.ndarray:
        # Harmonic stack with pauses: passes the enrollment quality gate the
        # same way continuous natural reading does.
        rng = np.random.default_rng(3)
        t = np.arange(int(seconds * rate)) / rate
        envelope = ((np.sin(2 * np.pi * 0.6 * t) > -0.2)
                    * (0.6 + 0.4 * np.sin(2 * np.pi * 3.1 * t)))
        voiced = np.zeros_like(t)
        for k in range(1, 22):
            if 140 * k > 3400:
                break
            voiced += np.sin(2 * np.pi * 140 * k * t + 0.3 * k) / k
        voiced /= np.max(np.abs(voiced))
        return (0.15 * envelope * voiced
                + rng.normal(0, 3e-4, t.size)).astype(np.float32)

    def record(device, destination, *args, **kwargs):
        if failure == "quality":
            sf.write(destination, np.zeros(int(15 * 48000), dtype=np.float32), 48000)
        else:
            sf.write(destination, synthetic_speech(15), 48000)
        if failure == "cancel":
            raise InterruptedError("cancel")
        if kwargs.get("on_progress") is not None and failure is None:
            kwargs["on_progress"]("recording", 1.0, 15.0)
    monkeypatch.setattr(setup, "record_input", record)

    latency_attempts = []

    def run(command, **kwargs):
        folder = config_path.parent / "registrations" / token
        name = Path(command[1]).name
        if name == "export_real_tse_onnx.py":
            (folder / "core.onnx").write_bytes(b"new model")
        elif name == "compare_torch_onnx.py":
            (folder / "correctness.json").write_text(json.dumps({"gate": {"verdict": "PASS"}}))
        elif name == "benchmark_onnx_tse.py":
            Path(command[command.index("--result") + 1]).write_text(json.dumps(
                benchmark(processing_rtf=1.1 if failure == "performance" else 0.5)))
        elif name == "measure_bridge_latency.py":
            prefill = int(command[command.index("--prefill-ms") + 1])
            latency_attempts.append(prefill)
            Path(command[command.index("--result") + 1]).write_text(json.dumps({"bridge_internal": dict(
                status="COMPLETED", length_match=True, nonfinite_samples=0,
                underrun_ms=10 if failure == "latency" or (failure == "retry" and prefill == 100) else 0,
                bridge_latency={"latency_ms_p95": 260})}))
        else:
            pytest.fail(str(command))
    monkeypatch.setattr(setup.subprocess, "run", run)
    if failure in {"performance", "latency"}:
        with pytest.raises(ValueError):
            setup.run_worker(config_path, "Mic", token)
    elif failure == "quality":
        from micforyou.enrollment_quality import EnrollmentQualityError
        with pytest.raises(EnrollmentQualityError):
            setup.run_worker(config_path, "Mic", token)
    else:
        setup.run_worker(config_path, "Mic", token)
    if failure in {"performance", "cancel", "latency", "quality"}:
        assert config_path.read_bytes() == original
        job = setup.read_job(config_path)
        assert job["status"] == ("CANCELLED" if failure == "cancel" else "FAILED")
        candidate_dir = config_path.parent / "registrations" / token
        if failure in {"quality", "cancel"}:
            # The recording never reached the saved point: candidate removed.
            assert not candidate_dir.exists()
            if failure == "quality":
                assert job["reason"] == "too_quiet"
                assert "没有录到足够清楚的声音" in job["stage"]
        else:
            # The voice was saved; performance failure keeps it for retesting.
            assert candidate_dir.is_dir()
            assert (candidate_dir / "enrollment.wav").exists()
            assert job.get("voice") == "saved"
            from micforyou import performance
            # The blocked verdict belongs to the pending candidate only; the
            # active registration's authorization is never overridden.
            verdict = performance.read_candidate_verdict(candidate_dir)
            assert verdict is not None and verdict["verdict"] == "blocked"
            assert verdict["candidate_token"] == token
            assert performance.read_verdict(config_path) is None
            assert setup.read_pending_candidate(config_path)["token"] == token
    else:
        updated = load_config(config_path)
        assert updated.bundle_managed
        assert updated.enrollment.read_bytes().startswith(b"RIFF")  # real capture kept
        assert updated.prefill_ms == (150 if failure == "retry" else 100)
        assert setup.read_job(config_path)["status"] == "READY"
    if failure == "retry":
        assert latency_attempts == [100, 150]
    elif failure == "latency":
        assert latency_attempts == [100, 150, 200]
    assert previous.enrollment.read_bytes() == b"old voice"
    assert previous.onnx_model.read_bytes() == b"old model"
