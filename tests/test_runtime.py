import pytest

from micforyou.runtime import ort_thread_settings


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
