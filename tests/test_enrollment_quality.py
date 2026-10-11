"""Behavioral contract for the pre-export enrollment quality gate."""
import numpy as np
import pytest

import micforyou.audio as audio_module
from micforyou.audio import Device, record_input
from micforyou.enrollment_quality import (
    EnrollmentQualityError,
    check_enrollment_audio,
)

RATE = 48000


def speech(seconds: float, *, gain: float = 1.0, seed: int = 3, rate: int = RATE) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * rate)) / rate
    envelope = ((np.sin(2 * np.pi * 0.6 * t) > -0.2)
                * (0.6 + 0.4 * np.sin(2 * np.pi * 3.1 * t)))
    voiced = np.zeros_like(t)
    for k in range(1, 22):
        if 140 * k > 3400:
            break
        voiced += np.sin(2 * np.pi * 140 * k * t + 0.3 * k) / k
    voiced /= np.max(np.abs(voiced))
    return (gain * 0.15 * envelope * voiced
            + rng.normal(0, 3e-4, t.size)).astype(np.float32)


def check(x: np.ndarray, rate: int = RATE, **kwargs):
    return check_enrollment_audio(x.astype(np.float32), rate, **kwargs)


def test_natural_reading_passes_and_reports_metrics():
    report = check(speech(15))
    assert report.ok and report.reason is None
    assert report.metrics["total_speech_seconds"] >= 6.0
    assert report.metrics["window_speech_seconds"] >= 3.0


def test_quiet_natural_reading_still_passes():
    assert check(speech(15, gain=0.2)).ok


def test_normal_pauses_do_not_reject():
    values = speech(15)
    for start in (4, 8, 12):
        values[start * RATE : (start + 1) * RATE] = 0.0
    assert check(values).ok


def test_long_gap_with_sparse_speech_is_rejected():
    values = speech(15)
    values[4 * RATE : 10 * RATE] = 0.0  # half the recording silent
    report = check(values)
    assert report.reason == "insufficient_speech"


def test_silence_is_rejected_as_too_quiet():
    report = check(np.zeros(15 * RATE) + np.random.default_rng(1).normal(0, 1e-4, 15 * RATE))
    assert not report.ok and report.reason == "too_quiet"


def test_extremely_quiet_speech_is_rejected_as_too_quiet():
    assert check(speech(15, gain=0.01)).reason == "too_quiet"


@pytest.mark.parametrize("sigma", [0.002, 0.05])
def test_stationary_noise_is_rejected(sigma):
    values = np.random.default_rng(2).normal(0, sigma, 15 * RATE)
    assert check(values).reason == "insufficient_speech"


def test_amplitude_modulated_noise_is_rejected_by_spectral_flatness():
    t = np.arange(15 * RATE) / RATE
    values = (np.random.default_rng(4).normal(0, 0.05, t.size)
              * (0.5 + 0.5 * np.sin(2 * np.pi * 0.4 * t)))
    report = check(values.astype(np.float32))
    assert report.reason == "insufficient_speech"
    assert report.metrics["window_spectral_flatness"] > 0.25


def test_sustained_clipping_is_rejected():
    values = speech(15)
    values /= np.max(np.abs(values)) / 0.8
    report = check(np.clip(values * 2.5, -1.0, 1.0))
    assert report.reason == "clipping"
    assert report.metrics["clipped_frame_ratio"] > 0.02


def test_isolated_transient_peaks_do_not_reject():
    values = speech(15)
    values[:: RATE * 3] = 1.0  # one full-scale sample per 3 s
    assert check(values).ok


def test_two_seconds_of_speech_cannot_fill_the_reference_window():
    values = np.zeros(15 * RATE, dtype=np.float32)
    values[: 2 * RATE] = speech(15)[: 2 * RATE]
    report = check(values)
    assert report.reason == "insufficient_speech"
    assert report.metrics["total_speech_seconds"] < 6.0


def test_window_selection_targets_the_loudest_segment():
    values = speech(15, gain=0.15)
    values[6 * RATE : 12 * RATE] = speech(15, gain=1.0)[6 * RATE : 12 * RATE]
    report = check(values)
    assert report.ok
    # Selection is on the sample-exact 0.25 s grid, mirroring the runtime.
    start = report.metrics["selected_start_seconds"]
    assert start % 0.25 == pytest.approx(0.0, abs=1e-9)
    assert 6.0 <= start + 3.0 <= 12.0


def test_selection_matches_actual_model_reference():
    from micforyou.enrollment_quality import select_reference_window
    from micforyou.runtime import prepare_enrollment_reference
    values = speech(15)
    start, length = select_reference_window(values, RATE, 6.0)
    reference = prepare_enrollment_reference(values, RATE, 6.0)
    assert start == reference.selection["source_start_samples"]
    assert length == reference.selection["source_end_samples"] - start
    assert length == int(round(RATE * 6.0))


@pytest.mark.parametrize("rate", [16000, 44100, 48000])
def test_gate_behaves_identically_across_sample_rates(rate):
    assert check(speech(15, rate=rate), rate).ok
    assert check(speech(15, gain=0.01, rate=rate), rate).reason == "too_quiet"
    values = np.random.default_rng(5).normal(0, 0.05, 15 * rate)
    assert check(values.astype(np.float32), rate).reason == "insufficient_speech"


def test_localized_clipping_inside_reference_window_is_not_diluted():
    values = speech(15)
    values[int(5.0 * RATE) : int(5.21 * RATE)] = 1.0
    report = check(values)
    assert report.reason == "clipping"
    # The whole-recording average stays below the limit; the window catches it.
    assert report.metrics["clipped_frame_ratio"] <= 0.02
    assert report.metrics["window_clipped_frame_ratio"] > 0.02


def test_spectral_flatness_follows_speech_position():
    # 6 s window: silence, then a 200 Hz tone for the last 3 s, placed at
    # front/middle/back by varying where speech starts.
    for voiced_start in (0.0, 1.5, 3.0):
        total = 6 * RATE
        values = np.zeros(total, dtype=np.float32)
        t = np.arange(total) / RATE
        tone = (0.1 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
        on = (t >= voiced_start) & (t < voiced_start + 3.0)
        values[on] = tone[on]
        from micforyou.enrollment_quality import _frame_rms, _map_speech_mask_to_fft, _window_spectral_flatness
        mask = _frame_rms(values, RATE) > 0.001
        flat = _window_spectral_flatness(values, RATE, 0, total, mask)
        assert flat < 0.01, (voiced_start, flat)


def test_flatness_ignores_silent_prefix_of_window():
    values = np.zeros(6 * RATE, dtype=np.float32)
    t = np.arange(3 * RATE) / RATE
    values[3 * RATE:] = (0.1 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    from micforyou.enrollment_quality import _frame_rms, _window_spectral_flatness
    mask = _frame_rms(values, RATE) > 0.001
    masked = _window_spectral_flatness(values, RATE, 0, 6 * RATE, mask)
    assert masked < 0.01  # aligned mask must measure the voiced half, not 1.0


def test_error_carries_reason_and_metrics():
    report = check(np.zeros(15 * RATE))
    error = EnrollmentQualityError(report.message, report.reason, report.metrics)
    assert error.reason == "too_quiet"
    assert "没有录到足够清楚的声音" in error.message
    with pytest.raises(ValueError):
        raise error


def test_record_input_reports_real_progress_phases(monkeypatch, tmp_path):
    events = []
    filled = {"started": False}

    class FakeSD:
        @staticmethod
        def rec(frames, samplerate, channels, dtype, device, out, blocking):
            assert blocking is False
            filled["started"] = True
            # Fill the buffer like real capture; asserting on uninitialized
            # memory would validate garbage, not recording results.
            out[:] = 0.05

        @staticmethod
        def wait():
            pass

    monkeypatch.setattr(audio_module, "sd", FakeSD)
    result = record_input(
        Device(0, "Mic", 0, 1, 0, RATE),
        tmp_path / "capture.wav",
        duration=0.9,
        countdown=0.4,
        on_progress=lambda phase, elapsed, total: events.append((phase, elapsed, total)),
    )
    phases = [phase for phase, _, _ in events]
    assert "countdown" in phases and "recording" in phases
    assert events[-1][0] == "recording"
    assert events[-1][1] <= events[-1][2]
    assert result["duration_seconds"] == pytest.approx(0.9, abs=0.05)
    assert (tmp_path / "capture.wav").stat().st_size > 44  # real wav header


def test_record_input_still_works_without_callback(monkeypatch, tmp_path):
    class FakeSD:
        @staticmethod
        def rec(frames, samplerate, channels, dtype, device, out, blocking):
            out[:] = 0.05

        @staticmethod
        def wait():
            pass

    monkeypatch.setattr(audio_module, "sd", FakeSD)
    result = record_input(Device(0, "Mic", 0, 1, 0, RATE), tmp_path / "c.wav", 0.3, 0.0)
    assert result["rms"] > 0
