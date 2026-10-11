"""Pre-export quality gate for enrollment candidate recordings.

The gate decides only whether a candidate recording is usable as voice
enrollment: it checks level, clipping, and whether the recording contains a
usable speech-dense reference window. It does not judge text content and makes
no claim about later filtering quality.

Coordinate contract: capture is resampled to the model's 16 kHz using the
shared runtime preparation path before selection. Model metrics use the exact
selected input; distortion is also checked in the corresponding source span.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

# Analysis frame for level/speech statistics.
FRAME_SECONDS = 0.03
# The reference window mirrors ProductConfig.enrollment_seconds (6 s); the
# caller passes the configured value so a future schema change stays coherent.
DEFAULT_WINDOW_SECONDS = 6.0

# Calibrated limits (float32 samples, 1.0 = full scale). The absolute floors
# sit far below typical speech because quiet-but-usable recordings were
# measured at window RMS around 0.002; separation between "sparse speech" and
# "continuous quiet reading" is done by speech seconds, not by level alone.
MAX_NEAR_CLIP_RATIO = 0.01  # share of a frame's samples at |x| >= 0.99
CLIPPED_FRAME_LIMIT = 0.02  # share of frames allowed to be clipped
MIN_RECORDING_RMS = 0.0008  # whole-recording level floor (~ -62 dBFS)
MIN_WINDOW_RMS = 0.0012  # level floor inside the selected window
SPEECH_FLOOR_RMS = 0.0012  # absolute frame-RMS floor to count as speech
NOISE_FLOOR_FACTOR = 1.5  # frame is speech above max(floor*factor, floor)
MIN_TOTAL_SPEECH_SECONDS = 6.0  # effective speech: enough to fill the window
MIN_WINDOW_SPEECH_SECONDS = 2.5  # effective speech inside the selected window
# Speech is harmonic and spectrally sparse; measured windows of real speech
# score <= 0.01 while white or amplitude-modulated noise scores ~0.56. Low-
# frequency rumble can still slip through and stays a documented limitation.
MAX_WINDOW_SPECTRAL_FLATNESS = 0.25
FLATNESS_FFT = 4096


class EnrollmentQualityError(ValueError):
    """Raised by callers to carry a machine-readable failure code."""

    def __init__(self, message: str, reason: str, metrics: dict):
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.metrics = metrics


@dataclass(frozen=True)
class EnrollmentQualityReport:
    ok: bool
    reason: str | None
    message: str | None
    metrics: dict


def select_reference_window(values: np.ndarray, sample_rate: int,
                            window_seconds: float) -> tuple[int, int]:
    """Source coordinates of the actual model reference (compatibility helper)."""
    from .runtime import prepare_enrollment_reference
    metadata = prepare_enrollment_reference(values, sample_rate, window_seconds).selection
    start, end = metadata["source_start_samples"], metadata["source_end_samples"]
    return start, end - start


def _frame_rms(values: np.ndarray, sample_rate: int) -> np.ndarray:
    frame = max(1, int(round(sample_rate * FRAME_SECONDS)))
    usable = (values.size // frame) * frame
    if usable == 0:
        return np.asarray([float(np.sqrt(np.mean(np.square(values, dtype=np.float64))))])
    trimmed = values[:usable].reshape(-1, frame)
    return np.sqrt(np.mean(np.square(trimmed, dtype=np.float64), axis=1))


def _clipped_frame_mask(values: np.ndarray, sample_rate: int) -> np.ndarray:
    frame = max(1, int(round(sample_rate * FRAME_SECONDS)))
    usable = (values.size // frame) * frame
    if usable == 0:
        return np.asarray([bool(np.mean(np.abs(values) >= 0.99) > MAX_NEAR_CLIP_RATIO)])
    trimmed = values[:usable].reshape(-1, frame)
    return np.mean(np.abs(trimmed) >= 0.99, axis=1) > MAX_NEAR_CLIP_RATIO


def _map_speech_mask_to_fft(
    speech_mask: np.ndarray,
    sample_rate: int,
    segment_offset: int,
    segment_length: int,
    fft_count: int,
) -> np.ndarray:
    """Map 30 ms speech frames onto FFT frames by actual sample coverage.

    Each FFT frame covers ``[segment_offset + i*FLATNESS_FFT, ... + FLATNESS_FFT)``
    samples of the recording; a frame counts as speech when at least half of
    its covered analysis frames are speech. Truncating arrays to equal length
    is not alignment — coverage is computed per frame.
    """
    mask_frame = max(1, int(round(sample_rate * FRAME_SECONDS)))
    result = np.zeros(fft_count, dtype=bool)
    for index in range(fft_count):
        start = segment_offset + index * FLATNESS_FFT
        stop = start + FLATNESS_FFT
        first = start // mask_frame
        last = max(first + 1, (stop + mask_frame - 1) // mask_frame)
        covered = speech_mask[first:last]
        if covered.size and np.mean(covered) >= 0.5:
            result[index] = True
    return result


def _window_spectral_flatness(
    values: np.ndarray,
    sample_rate: int,
    start: int,
    window_length: int,
    speech_mask: np.ndarray,
) -> float:
    """Geometric/arithmetic mean ratio over the window's speech FFT frames."""
    segment = values[start : start + window_length]
    usable = (segment.size // FLATNESS_FFT) * FLATNESS_FFT
    if usable == 0:
        return 1.0
    windowed = segment[:usable].reshape(-1, FLATNESS_FFT) * np.hanning(FLATNESS_FFT)
    spectrum = np.square(np.abs(np.fft.rfft(windowed, axis=1)), dtype=np.float64) + 1e-20
    flatness = np.exp(np.mean(np.log(spectrum), axis=1)) / np.mean(spectrum, axis=1)
    selected = _map_speech_mask_to_fft(
        speech_mask, sample_rate, start, usable, flatness.size
    )
    if not np.any(selected):
        return 1.0
    return float(np.mean(flatness[selected]))


def check_enrollment_audio(
    audio: np.ndarray,
    sample_rate: int,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
) -> EnrollmentQualityReport:
    """Judge a candidate enrollment recording before any model export.

    ``audio`` is the mono float capture at its native rate. The selected
    reference is selected after the runtime's exact 16k conversion. Level and
    speech metrics use that model input; clipping is also checked over the
    whole source recording and the corresponding source reference span.
    """
    values = np.asarray(audio, dtype=np.float32).reshape(-1)
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    if values.size == 0:
        raise ValueError("empty recording cannot be checked")
    absolute = np.abs(values)
    overall_rms = float(np.sqrt(np.mean(np.square(values, dtype=np.float64))))
    peak = float(np.max(absolute))
    duration = values.size / sample_rate

    from .runtime import prepare_enrollment_reference
    reference = prepare_enrollment_reference(values, sample_rate, window_seconds)
    selection = reference.selection
    source_start, source_end = selection["source_start_samples"], selection["source_end_samples"]
    model_values = reference.model_audio.numpy().reshape(-1)
    model_segment = reference.selected.numpy().reshape(-1)
    model_rate = selection["model_sample_rate"]
    start, window_length = selection["selected_start_samples"], model_segment.size

    clipped = _clipped_frame_mask(values, sample_rate)
    window_clipped_ratio = float(np.mean(_clipped_frame_mask(values[source_start:source_end], sample_rate)))
    model_clipped_ratio = float(np.mean(_clipped_frame_mask(model_segment, model_rate)))
    rms_frames = _frame_rms(model_values, model_rate)
    window_frame = max(1, int(round(model_rate * FRAME_SECONDS)))
    window_first = start // window_frame
    window_last = max(window_first + 1, (start + window_length + window_frame - 1) // window_frame)
    window_rms = float(np.sqrt(np.mean(np.square(model_segment, dtype=np.float64))))

    def fail(reason: str, message: str) -> EnrollmentQualityReport:
        return EnrollmentQualityReport(False, reason, message, metrics)

    metrics: dict = {
        "duration_seconds": duration,
        "rms": overall_rms,
        "peak": peak,
        "clipped_frame_ratio": float(np.mean(clipped)),
        "window_clipped_frame_ratio": window_clipped_ratio,
        "window_seconds_requested": window_seconds,
        **selection,
        "model_window_clipped_frame_ratio": model_clipped_ratio,
        "sample_rate": sample_rate,
        "window_rms": window_rms,
    }

    # Clipping is judged on the window the model will consume first, then on
    # the recording as a whole; either being sustained distortion fails.
    if max(window_clipped_ratio, model_clipped_ratio, metrics["clipped_frame_ratio"]) > CLIPPED_FRAME_LIMIT:
        return fail("clipping", "声音失真，请离麦克风稍远或降低音量后重录")

    if overall_rms < MIN_RECORDING_RMS and window_rms < MIN_WINDOW_RMS:
        return fail("too_quiet", "没有录到足够清楚的声音，请确认麦克风后重录")

    noise_floor = float(np.percentile(rms_frames, 20))
    speech_threshold = max(noise_floor * NOISE_FLOOR_FACTOR, SPEECH_FLOOR_RMS)
    speech_mask = rms_frames > speech_threshold
    total_speech_seconds = float(np.mean(speech_mask)) * duration
    window_speech_seconds = float(np.mean(speech_mask[window_first:window_last])) * (
        (window_last - window_first) * FRAME_SECONDS
    )
    flatness = _window_spectral_flatness(model_values, model_rate, start, window_length, speech_mask)
    metrics["noise_floor_rms"] = noise_floor
    metrics["speech_threshold_rms"] = speech_threshold
    metrics["total_speech_seconds"] = total_speech_seconds
    metrics["window_speech_seconds"] = window_speech_seconds
    metrics["window_spectral_flatness"] = flatness

    if total_speech_seconds < MIN_TOTAL_SPEECH_SECONDS or window_speech_seconds < MIN_WINDOW_SPEECH_SECONDS:
        return fail("insufficient_speech", "有效讲话不足，请自然连续朗读后重录")

    if flatness > MAX_WINDOW_SPECTRAL_FLATNESS:
        return fail("insufficient_speech", "有效讲话不足，请自然连续朗读后重录")

    if window_rms < MIN_WINDOW_RMS:
        return fail("too_quiet", "没有录到足够清楚的声音，请确认麦克风后重录")

    return EnrollmentQualityReport(True, None, None, metrics)
