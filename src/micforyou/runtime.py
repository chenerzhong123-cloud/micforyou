"""Pure runtime-configuration helpers shared by optional experiment tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

import numpy as np


def select_enrollment_window(enrollment, sample_rate: int, max_seconds: float):
    """Select a bounded, speech-dense enrollment window.

    Enrollment is recorded in a controlled quiet flow, so window RMS is a
    useful deterministic proxy for speech density. The source is not changed;
    callers can persist the returned selection metadata.
    """
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if max_seconds <= 0:
        raise ValueError("max_seconds must be positive")
    if enrollment.ndim != 2 or enrollment.shape[0] != 1:
        raise ValueError("enrollment must be mono with shape [1, samples]")

    window = max(1, int(round(sample_rate * max_seconds)))
    total = int(enrollment.shape[-1])
    if total <= window:
        return enrollment, {
            "source_seconds": total / sample_rate,
            "selected_start_seconds": 0.0,
            "selected_seconds": total / sample_rate,
            "selection": "full_recording",
        }

    stride = max(1, sample_rate // 4)
    values = np.asarray(enrollment)
    starts = range(0, total - window + 1, stride)
    start = max(
        starts,
        key=lambda offset: float(
            np.mean(np.square(values[0, offset : offset + window], dtype=np.float64))
        ),
    )
    selected = enrollment[:, start : start + window]
    selected = (
        selected.contiguous()
        if hasattr(selected, "contiguous")
        else np.ascontiguousarray(selected)
    )
    return selected, {
        "source_seconds": total / sample_rate,
        "selected_start_seconds": start / sample_rate,
        "selected_seconds": selected.shape[-1] / sample_rate,
        "selection": "highest_rms_window",
    }


@dataclass(frozen=True)
class OrtThreadSetting:
    """An ORT thread request and the exact label written to reports."""

    requested: int
    label: str
    intra_op_num_threads: int | None
    inter_op_num_threads: int | None


def ort_thread_settings(values: list[int]) -> list[OrtThreadSetting]:
    """Validate/deduplicate ORT thread requests without changing their order.

    Zero means leave ORT's thread counts unset (the runtime default). Positive
    values explicitly set intra-op threads and pin inter-op threads to one.
    """
    if not values:
        raise ValueError("at least one ORT thread setting is required")
    settings: list[OrtThreadSetting] = []
    seen: set[int] = set()
    for value in values:
        if value < 0:
            raise ValueError("ORT thread counts must be zero or positive")
        if value in seen:
            continue
        seen.add(value)
        settings.append(
            OrtThreadSetting(
                requested=value,
                label="auto" if value == 0 else str(value),
                intra_op_num_threads=None if value == 0 else value,
                inter_op_num_threads=None if value == 0 else 1,
            )
        )
    return settings


def build_ort_cpu_session(model_path: Path, threads: int):
    """Build the optional ONNX Runtime CPU backend with explicit threading."""
    import onnxruntime as ort

    setting = ort_thread_settings([threads])[0]
    options = ort.SessionOptions()
    if setting.intra_op_num_threads is not None:
        options.intra_op_num_threads = setting.intra_op_num_threads
        options.inter_op_num_threads = setting.inter_op_num_threads
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    started = time.perf_counter()
    session = ort.InferenceSession(
        str(model_path),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    return session, {
        "provider": "CPUExecutionProvider",
        "requested_threads": setting.label,
        "session_create_seconds": time.perf_counter() - started,
        "providers_registered": session.get_providers(),
    }


def validate_ort_conditioning_shapes(session, conditioning: dict) -> None:
    """Fail before audio capture when enrollment and personalized ONNX differ."""
    declared = {item.name: item.shape for item in session.get_inputs()}
    pairs = {
        "enroll_tfmap": conditioning["tfmap"],
        "enroll_context": conditioning["context"],
    }
    for input_name, value in pairs.items():
        if input_name not in declared:
            raise ValueError(f"ONNX model is missing required input {input_name}")
        expected = declared[input_name]
        actual = list(value.shape)
        if len(expected) != len(actual) or any(
            isinstance(wanted, int) and wanted != got
            for wanted, got in zip(expected, actual)
        ):
            raise ValueError(
                f"{input_name} shape {actual} does not match personalized "
                f"ONNX shape {expected}; re-export ONNX for this enrollment"
            )
