"""Pre-export quality gate for enrollment candidate recordings.

The gate decides only whether a candidate recording is usable as voice
enrollment: it checks level, clipping, and whether the recording contains a
usable speech-dense window. It does not judge text content and makes no claim
about later filtering quality.

Thresholds are calibrated against authorized local recordings (normal and
quiet speech) plus synthetic silence, noise, and clipping degradations; see
tests/test_enrollment_quality.py for the behavioral contract.
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
MIN_TOTAL_SPEECH_SECONDS = 6.0  # effective speech: enough to fill the 6 s model window
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


def _frame_rms(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    frame = max(1, int(round(sample_rate * FRAME_SECONDS)))
    usable = (len(audio) // frame) * frame
    if usable == 0:
        return np.asarray([float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))])
    trimmed = audio[:usable].reshape(-1, frame)
    return np.sqrt(np.mean(np.square(trimmed, dtype=np.float64), axis=1))


def _select_window(frame_rms: np.ndarray, frame_seconds: float, window_seconds: float) -> tuple[int, int]:
    """Highest-RMS contiguous window, mirroring select_enrollment_window."""
    window = max(1, int(round(window_seconds / frame_seconds)))
    total = len(frame_rms)
    if total <= window:
        return 0, total
    stride = max(1, int(round(0.25 / frame_seconds)))
    starts = range(0, total - window + 1, stride)
    cumulative = np.concatenate(([0.0], np.cumsum(np.square(frame_rms))))
    sums = cumulative[np.asarray(starts) + window] - cumulative[np.asarray(starts)]
    start = int(starts[int(np.argmax(sums))])
    return start, start + window


def _window_spectral_flatness(audio: np.ndarray, sample_rate: int, start_frame: int, end_frame: int, speech_mask: np.ndarray) -> float:
    """Geometric/arithmetic mean ratio over the window's speech frames.

    Paused frames inside the window carry no harmonic structure and must not
    drag the average toward noise; only frames classified as speech count.
    """
    frame = max(1, int(round(sample_rate * FRAME_SECONDS)))
    segment = audio[start_frame * frame : end_frame * frame]
    usable = (segment.size // FLATNESS_FFT) * FLATNESS_FFT
    if usable == 0:
        return 1.0
    windowed = segment[:usable].reshape(-1, FLATNESS_FFT) * np.hanning(FLATNESS_FFT)
    spectrum = np.square(np.abs(np.fft.rfft(windowed, axis=1)), dtype=np.float64) + 1e-20
    flatness = np.exp(np.mean(np.log(spectrum), axis=1)) / np.mean(spectrum, axis=1)
    selected = speech_mask[start_frame:end_frame][: flatness.size]
    if not np.any(selected):
        return 1.0
    return float(np.mean(flatness[selected]))


def check_enrollment_audio(
    audio: np.ndarray,
    sample_rate: int,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
) -> EnrollmentQualityReport:
    """Judge a candidate enrollment recording before any model export.

    ``audio`` is the mono float capture at its native rate; the selected
    window replicates the runtime's deterministic highest-RMS choice so the
    gate covers the exact segment the model will use, not just the average.
    """
    values = np.asarray(audio, dtype=np.float32).reshape(-1)
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if values.size == 0:
        raise ValueError("empty recording cannot be checked")
    absolute = np.abs(values)
    overall_rms = float(np.sqrt(np.mean(np.square(values, dtype=np.float64))))
    peak = float(np.max(absolute))

    frame = max(1, int(round(sample_rate * FRAME_SECONDS)))
    usable = (values.size // frame) * frame
    frames = values[:usable].reshape(-1, frame)
    near_clip_ratio = np.mean(np.abs(frames) >= 0.99, axis=1)
    clipped_frames = float(np.mean(near_clip_ratio > MAX_NEAR_CLIP_RATIO))
    rms_frames = _frame_rms(values, sample_rate)

    def fail(reason: str, message: str) -> EnrollmentQualityReport:
        return EnrollmentQualityReport(False, reason, message, metrics)

    metrics: dict = {
        "duration_seconds": values.size / sample_rate,
        "rms": overall_rms,
        "peak": peak,
        "clipped_frame_ratio": clipped_frames,
        "window_seconds_requested": window_seconds,
    }

    if clipped_frames > CLIPPED_FRAME_LIMIT:
        return fail("clipping", "声音失真，请离麦克风稍远或降低音量后重录")

    start, end = _select_window(rms_frames, FRAME_SECONDS, window_seconds)
    window_rms = float(np.sqrt(np.mean(np.square(rms_frames[start:end], dtype=np.float64))))
    metrics["selected_start_seconds"] = start * FRAME_SECONDS
    metrics["window_rms"] = window_rms

    if overall_rms < MIN_RECORDING_RMS and window_rms < MIN_WINDOW_RMS:
        return fail("too_quiet", "没有录到足够清楚的声音，请确认麦克风后重录")

    noise_floor = float(np.percentile(rms_frames, 20))
    speech_threshold = max(noise_floor * NOISE_FLOOR_FACTOR, SPEECH_FLOOR_RMS)
    speech_mask = rms_frames > speech_threshold
    total_speech_seconds = float(np.mean(speech_mask)) * (values.size / sample_rate)
    window_speech_seconds = float(np.mean(speech_mask[start:end])) * (end - start) * FRAME_SECONDS
    metrics["noise_floor_rms"] = noise_floor
    metrics["speech_threshold_rms"] = speech_threshold
    metrics["total_speech_seconds"] = total_speech_seconds
    metrics["window_speech_seconds"] = window_speech_seconds

    if total_speech_seconds < MIN_TOTAL_SPEECH_SECONDS or window_speech_seconds < MIN_WINDOW_SPEECH_SECONDS:
        return fail("insufficient_speech", "有效讲话不足，请自然连续朗读后重录")

    flatness = _window_spectral_flatness(values, sample_rate, start, end, speech_mask)
    metrics["window_spectral_flatness"] = flatness
    if flatness > MAX_WINDOW_SPECTRAL_FLATNESS:
        return fail("insufficient_speech", "有效讲话不足，请自然连续朗读后重录")

    if window_rms < MIN_WINDOW_RMS:
        return fail("too_quiet", "没有录到足够清楚的声音，请确认麦克风后重录")

    return EnrollmentQualityReport(True, None, None, metrics)
