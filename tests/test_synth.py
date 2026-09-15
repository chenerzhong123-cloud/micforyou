import numpy as np

from micforyou.reporting import percentile_summary
from micforyou.synth import pulse_positions, synthetic_blocks, synthetic_mixture


def test_same_seed_reproduces_identical_blocks() -> None:
    first = list(synthetic_blocks(9_600, block_frames=480, seed=7))
    second = list(synthetic_blocks(9_600, block_frames=480, seed=7))
    assert len(first) == len(second) == 20
    for left, right in zip(first, second):
        np.testing.assert_array_equal(left, right)


def test_different_seed_changes_content() -> None:
    first = np.concatenate(list(synthetic_blocks(4_800, seed=1)))
    second = np.concatenate(list(synthetic_blocks(4_800, seed=2)))
    assert not np.array_equal(first, second)


def test_output_is_finite_float32_without_pulses() -> None:
    audio = synthetic_mixture(2.0, seed=3, pulse_every_seconds=None)
    assert audio.dtype == np.float32
    assert np.isfinite(audio).all()
    assert float(np.abs(audio).max()) < 1.0


def test_pulses_land_at_known_positions() -> None:
    positions = pulse_positions(48_000 * 3, 48_000, every_seconds=1.0, first_seconds=1.0)
    assert positions == [48_000, 96_000]  # 144_000 is past the last sample
    audio = synthetic_mixture(3.0, seed=5, pulse_every_seconds=1.0)
    assert len(audio) == 48_000 * 3
    for position in positions:
        window = audio[position - 24 : position + 24]
        assert float(np.abs(audio[position])) > 0.25  # pulse plus a local dip
        assert float(np.abs(audio[position])) >= 0.98 * float(np.abs(window).max())


def test_percentile_summary_handles_empty() -> None:
    assert percentile_summary([]) == {"count": 0}
    values = percentile_summary([1.0, 2.0, 3.0, 4.0])
    assert values["count"] == 4
    assert values["max"] == 4.0
