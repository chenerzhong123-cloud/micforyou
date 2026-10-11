"""Compare the shared path against actual torchaudio/model baseline, not a mirror."""
import numpy as np
import pytest
import torch
import torchaudio
from micforyou.runtime import prepare_enrollment_reference, select_enrollment_window
from micforyou.enrollment_quality import check_enrollment_audio


@pytest.mark.parametrize("rate", [16000, 44100, 48000])
@pytest.mark.parametrize("style", ["band_energy", "tie", "near_tie", "short_boundary"])
def test_reference_and_gate_exactly_match_model_baseline(rate, style):
    duration = 4.123 if style == "short_boundary" else 15.013
    t = np.arange(int(rate * duration)) / rate
    values = (0.1 * np.sin(2*np.pi*200*t)).astype(np.float32)
    if style == "band_energy":
        values[:int(rate*6)] += (0.3*np.sin(2*np.pi*12000*t[:int(rate*6)])).astype(np.float32)
    elif style == "tie":
        values.fill(.01)
    elif style == "near_tie":
        values[int(rate*9):] *= 1.000001
    capture = torch.from_numpy(values).unsqueeze(0)
    model = capture if rate == 16000 else torchaudio.functional.resample(capture, rate, 16000)
    selected, expected = select_enrollment_window(model, 16000, 6)
    reference = prepare_enrollment_reference(capture, rate, 6)
    assert torch.equal(reference.selected, selected)
    assert torch.equal(reference.model_audio, model)
    assert reference.selection["selected_start_seconds"] == expected["selected_start_seconds"]
    report = check_enrollment_audio(values, rate)
    for key in ("selected_start_samples", "selected_end_samples", "source_start_samples", "source_end_samples"):
        assert report.metrics[key] == reference.selection[key]
    source_start = int(expected["selected_start_seconds"] * rate)
    assert abs(reference.selection["source_start_samples"] - source_start) <= 1
    assert reference.selection["source_end_samples"] <= len(values)


def test_out_of_band_energy_cannot_hide_actual_reference_clipping():
    rate = 48000
    t = np.arange(rate*15)/rate
    values = np.zeros(t.size, np.float32)
    values[:rate*6] = .3*np.sin(2*np.pi*12000*t[:rate*6])
    values[rate*9:] = .1*np.sin(2*np.pi*200*t[rate*9:])
    values[rate*12:int(rate*12.21)] = 1.0
    report = check_enrollment_audio(values, rate)
    assert report.reason == "clipping"
    assert report.metrics["selected_start_seconds"] == 9.0
    assert report.metrics["source_start_samples"] == rate*9
    assert report.metrics["clipped_frame_ratio"] <= .02
    assert report.metrics["window_clipped_frame_ratio"] > .02


def test_every_model_consumer_uses_shared_preparation():
    # Integration guard for the five executable model entrypoints. Numerical
    # behavior is tested above against actual torchaudio, including exact ties.
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "tools/inference"
    for name in ["export_real_tse_onnx.py", "compare_torch_onnx.py", "run_real_tse_bridge.py",
                 "benchmark_onnx_tse.py", "measure_bridge_latency.py"]:
        tree = ast.parse((root/name).read_text())
        calls = [n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        assert "prepare_enrollment_reference" in calls, name
        assert "select_enrollment_window" not in calls, name
