import pytest
import numpy as np

from micforyou.runtime import (
    ort_thread_settings,
    select_enrollment_window,
    validate_ort_conditioning_shapes,
)


def test_coreml_fallback_matrix_preserves_auto_and_four_threads() -> None:
    auto, four = ort_thread_settings([0, 4])
    assert auto.label == "auto"
    assert auto.intra_op_num_threads is None
    assert auto.inter_op_num_threads is None
    assert four.label == "4"
    assert four.intra_op_num_threads == 4
    assert four.inter_op_num_threads == 1


def test_thread_settings_deduplicate_without_relabeling() -> None:
    settings = ort_thread_settings([4, 0, 4])
    assert [(item.requested, item.label) for item in settings] == [
        (4, "4"),
        (0, "auto"),
    ]


def test_thread_settings_reject_invalid_input() -> None:
    with pytest.raises(ValueError):
        ort_thread_settings([])
    with pytest.raises(ValueError):
        ort_thread_settings([-1])


def test_select_enrollment_window_uses_highest_energy_region() -> None:
    enrollment = np.zeros((1, 30), dtype=np.float32)
    enrollment[:, 10:20] = 2

    selected, metadata = select_enrollment_window(enrollment, 10, 1.0)

    np.testing.assert_array_equal(selected, np.full((1, 10), 2.0))
    assert metadata == {
        "source_seconds": 3.0,
        "selected_start_seconds": 1.0,
        "selected_seconds": 1.0,
        "selection": "highest_rms_window",
    }


def test_select_enrollment_window_keeps_short_recording() -> None:
    enrollment = np.ones((1, 8), dtype=np.float32)

    selected, metadata = select_enrollment_window(enrollment, 10, 1.0)

    assert selected is enrollment
    assert metadata["selection"] == "full_recording"


class _Input:
    def __init__(self, name, shape):
        self.name = name
        self.shape = shape


class _Session:
    def __init__(self, tfmap_shape, context_shape):
        self.inputs = [
            _Input("enroll_tfmap", tfmap_shape),
            _Input("enroll_context", context_shape),
        ]

    def get_inputs(self):
        return self.inputs


def test_validate_ort_conditioning_accepts_matching_or_dynamic_shapes() -> None:
    session = _Session([1, 257, 751], [1, 512, "frames"])
    conditioning = {
        "tfmap": np.zeros((1, 257, 751)),
        "context": np.zeros((1, 512, 598)),
    }

    validate_ort_conditioning_shapes(session, conditioning)


def test_validate_ort_conditioning_rejects_stale_personalized_model() -> None:
    session = _Session([1, 257, 732], [1, 512, 584])
    conditioning = {
        "tfmap": np.zeros((1, 257, 751)),
        "context": np.zeros((1, 512, 598)),
    }

    with pytest.raises(ValueError, match="re-export ONNX"):
        validate_ort_conditioning_shapes(session, conditioning)
