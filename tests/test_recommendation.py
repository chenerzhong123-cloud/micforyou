import pytest

from micforyou.recommendation import (
    BALANCED,
    CONSERVATIVE,
    FAST,
    UNSUPPORTED,
    BenchmarkCandidate,
    estimate_core_latency_ms,
    recommend,
)


def candidate(frames: int, rtf: float, p95: float, **overrides) -> BenchmarkCandidate:
    chunk_ms = frames * 8
    values = dict(
        frames_per_chunk=frames,
        rtf=rtf,
        model_call_ms_p95=p95,
        model_call_ms_p50=p95 * 0.6,
        model_call_ms_max=p95 * 1.5,
        model_calls=200,
        input_samples=480_000,
        output_samples=480_000,
        nonfinite_samples=0,
        error=None,
    )
    values.update(overrides)
    return BenchmarkCandidate(**values)


def test_core_latency_formula_matches_stage_c() -> None:
    assert estimate_core_latency_ms(8, 36.0) == pytest.approx(124.0)


def test_strong_host_recommends_fast_lowest_frames() -> None:
    result = recommend(
        [
            candidate(8, 0.55, 25.0),
            candidate(16, 0.35, 30.0),
            candidate(24, 0.28, 45.0),
        ]
    )
    assert result.level == FAST
    assert result.frames_per_chunk == 8


def test_marginal_host_falls_back_to_balanced() -> None:
    # 24 frames misses the fast/balanced core budget (24 + 192 + 150 = 366 ms)
    # but stays inside the conservative budget, so balanced picks 16 frames.
    result = recommend(
        [
            candidate(8, 0.95, 90.0),
            candidate(16, 0.75, 95.0),
            candidate(24, 0.60, 150.0),
        ]
    )
    assert result.level == BALANCED
    assert result.frames_per_chunk == 16


def test_weak_host_falls_back_to_conservative_largest_chunk() -> None:
    result = recommend(
        [
            candidate(8, 1.42, 92.5),
            candidate(16, 0.92, 120.0),
            candidate(24, 0.70, 141.2),
        ]
    )
    assert result.level == CONSERVATIVE
    assert result.frames_per_chunk == 24


def test_no_safe_candidate_is_unsupported() -> None:
    result = recommend(
        [
            candidate(8, 1.42, 92.5),
            candidate(16, 0.98, 150.0),
            candidate(24, 0.95, 220.0),
        ]
    )
    assert result.level == UNSUPPORTED
    assert result.frames_per_chunk is None
    assert result.reasons


def test_core_latency_over_budget_rejects_even_with_good_rtf() -> None:
    # 48 frames -> 384 ms batch wait alone; core estimate busts the budget.
    result = recommend([candidate(48, 0.30, 200.0)])
    assert result.level == UNSUPPORTED


def test_fast_requires_call_inside_chunk_interval() -> None:
    # p95 call of 70 ms cannot finish inside a 64 ms chunk, so the 8-frame
    # candidate is at best balanced even with a strong RTF.
    result = recommend([candidate(8, 0.50, 70.0)])
    assert result.level == BALANCED
    assert result.frames_per_chunk == 8


def test_invalid_candidates_are_excluded_with_reasons() -> None:
    broken = candidate(
        16,
        0.5,
        50.0,
        error="non-finite output",
        nonfinite_samples=3,
    )
    mismatch = candidate(24, 0.5, 50.0, output_samples=1)
    result = recommend([broken, mismatch, candidate(8, 0.5, 25.0)])
    assert result.level == FAST
    assert result.frames_per_chunk == 8
    verdicts = {v.frames_per_chunk: v for v in result.verdicts}
    assert not verdicts[16].valid
    assert not verdicts[24].valid
    assert any("non-finite" in reason for reason in verdicts[16].reasons)
    assert any("length" in reason for reason in verdicts[24].reasons)


def test_too_few_model_calls_is_not_a_measurement() -> None:
    result = recommend([candidate(16, 0.5, 50.0, model_calls=3)])
    assert result.level == UNSUPPORTED
    assert any("model calls" in reason for reason in result.verdicts[0].reasons)


def test_empty_candidates_is_unsupported() -> None:
    result = recommend([])
    assert result.level == UNSUPPORTED


def test_duplicate_frames_are_deduplicated() -> None:
    result = recommend([candidate(16, 0.5, 50.0), candidate(16, 0.9, 80.0)])
    assert [v.frames_per_chunk for v in result.verdicts] == [16]
    assert result.level is not UNSUPPORTED
