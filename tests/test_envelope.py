import numpy as np
import pytest

from micforyou.envelope import DelayEnvelope, DelayProfile, PROFILES, build_delay_trace


class FakeTime:
    def __init__(self) -> None:
        self.value = 100.0

    def clock(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def test_delay_trace_matches_declared_quantiles_and_is_reproducible() -> None:
    profile = PROFILES["boundary"]
    first = build_delay_trace(profile, count=10_000, seed=7)
    second = build_delay_trace(profile, count=10_000, seed=7)
    np.testing.assert_array_equal(first, second)
    assert np.percentile(first, 50) == pytest.approx(profile.p50_ms, abs=0.02)
    assert np.percentile(first, 95) == pytest.approx(profile.p95_ms, abs=0.03)
    assert first.max() == profile.maximum_ms


def test_delay_envelope_only_adds_missing_time() -> None:
    fake = FakeTime()

    def transform(value: int) -> int:
        fake.value += 0.003
        return value * 2

    envelope = DelayEnvelope(
        transform,
        [5.0, 2.0],
        clock=fake.clock,
        sleeper=fake.sleep,
        spin_margin_seconds=0,
    )
    assert envelope(4) == 8
    assert envelope(5) == 10
    assert envelope.underlying_ms == pytest.approx([3.0, 3.0])
    assert envelope.injected_ms == pytest.approx([2.0, 0.0])
    assert envelope.observed_ms == pytest.approx([5.0, 3.0])
    assert envelope.summary()["underlying_over_target_calls"] == 1


def test_invalid_profile_and_trace_are_rejected() -> None:
    with pytest.raises(ValueError, match="min <= p50"):
        build_delay_trace(DelayProfile("bad", 3, 2, 4, 5))
    with pytest.raises(ValueError, match="finite non-negative"):
        DelayEnvelope(lambda value: value, [float("nan")])
