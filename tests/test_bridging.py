import time

import numpy as np
import pytest

from micforyou.bridging import (
    AudioRing,
    BridgeEngine,
    LatencyLedger,
    sleep_until,
)


def identity_transform(block: np.ndarray) -> np.ndarray:
    return np.asarray(block, dtype=np.float32).copy()


def test_ring_preserves_order_and_bounded_overflow_clears() -> None:
    ring = AudioRing(maximum_frames=100)
    assert ring.push(np.ones(60, dtype=np.float32))
    assert ring.push(np.ones(60, dtype=np.float32)) is False  # 120 > 100
    assert ring.available() == 0
    assert ring.push(np.full(30, 0.5, dtype=np.float32))
    samples, written = ring.pop(50)
    assert written == 30
    np.testing.assert_allclose(samples[:30], 0.5)
    np.testing.assert_allclose(samples[30:], 0.0)
    # The popped counter tracks emitted audio positions even across clears.
    assert ring.total_popped == 30
    ring.push(np.ones(10, dtype=np.float32))
    ring.clear()
    assert ring.total_popped == 40
    ring.push(np.ones(5, dtype=np.float32))
    ring.pop(5)
    assert ring.total_popped == 45


def test_engine_streams_identity_and_flushes_tail() -> None:
    engine = BridgeEngine(
        identity_transform,
        lambda: np.full(7, 0.25, dtype=np.float32),
        input_bound_blocks=64,
        ring_maximum_frames=48_000,
    )
    total = np.zeros(0, dtype=np.float32)
    for index in range(100):
        block = np.full(48, index / 100, dtype=np.float32)
        assert engine.submit(block)
        samples, written = engine.write_output(48)
        if written:
            total = np.concatenate([total, samples[:written]])
        time.sleep(0.001)
    engine.finish(timeout=10)
    while engine.output_ring.available():
        samples, written = engine.write_output(48)
        total = np.concatenate([total, samples[:written]])
    assert not engine.fault.is_set()
    assert engine.errors == []
    # 100 blocks * 48 samples plus the 7-sample flush tail all arrive.
    assert len(total) == 100 * 48 + 7
    assert np.isfinite(total).all()


def test_engine_model_exception_latches_fault_and_outputs_silence() -> None:
    def exploding(block: np.ndarray) -> np.ndarray:
        if np.max(block) > 0.5:
            raise RuntimeError("inference failed")
        return np.zeros_like(block)

    engine = BridgeEngine(
        exploding,
        lambda: np.empty(0, dtype=np.float32),
        input_bound_blocks=64,
        ring_maximum_frames=48_000,
    )
    engine.submit(np.full(48, 0.1, dtype=np.float32))
    time.sleep(0.05)
    assert not engine.fault.is_set()

    engine.submit(np.full(48, 0.9, dtype=np.float32))  # triggers the exception
    deadline = time.monotonic() + 5
    while not engine.fault.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert engine.fault.is_set()

    # Raw input must never leak: keep feeding loud audio, output stays zeros.
    for _ in range(20):
        engine.submit(np.full(48, 0.99, dtype=np.float32))
        samples, written = engine.write_output(48)
        assert written == 0
        np.testing.assert_array_equal(samples, np.zeros(48, dtype=np.float32))
    assert engine.output_ring.available() == 0
    assert any("inference failed" in error for error in engine.errors)


def test_engine_input_overflow_latches_fault_not_passthrough() -> None:
    def slow(block: np.ndarray) -> np.ndarray:
        time.sleep(0.02)
        return block * 0  # even a "working" chain must not leak after fault

    engine = BridgeEngine(
        slow,
        lambda: np.empty(0, dtype=np.float32),
        input_bound_blocks=4,
        ring_maximum_frames=48,
    )
    loud = np.full(48, 0.9, dtype=np.float32)
    deadline = time.monotonic() + 5
    while not engine.fault.is_set() and time.monotonic() < deadline:
        engine.submit(loud)
        time.sleep(0.001)
    assert engine.fault.is_set()
    samples, written = engine.write_output(48)
    assert written == 0
    np.testing.assert_array_equal(samples, np.zeros(48, dtype=np.float32))
    assert engine.errors  # overflow reported, whichever bound tripped first


def test_engine_output_overflow_faults_silently() -> None:
    engine = BridgeEngine(
        lambda block: np.full(960, 0.7, dtype=np.float32),
        lambda: np.empty(0, dtype=np.float32),
        input_bound_blocks=64,
        ring_maximum_frames=480,  # one 960-sample burst overflows the ring
    )
    engine.submit(np.ones(48, dtype=np.float32))
    deadline = time.monotonic() + 5
    while not engine.fault.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert engine.fault.is_set()
    samples, written = engine.write_output(48)
    assert written == 0
    np.testing.assert_array_equal(samples, np.zeros(48, dtype=np.float32))


def test_ledger_computes_block_latency_distribution() -> None:
    ledger = LatencyLedger()
    base = 1000.0
    ledger.record_input(0, 10, base)
    ledger.record_input(10, 10, base + 0.010)
    ledger.record_output(0, 10, base + 0.030)
    ledger.record_output(10, 10, base + 0.050)
    summary = ledger.summary()
    assert summary["blocks"] == 2
    assert summary["latency_ms_p50"] == pytest.approx(35.0)
    assert summary["latency_ms_max"] == pytest.approx(40.0)


def test_ledger_ignores_positions_before_first_input() -> None:
    ledger = LatencyLedger()
    ledger.record_output(5, 10, 1.0)
    ledger.record_input(10, 10, 2.0)
    ledger.record_output(10, 10, 2.020)
    summary = ledger.summary()
    assert summary["blocks"] == 1
    assert summary["latency_ms_p50"] == pytest.approx(20.0)


def test_sleep_until_returns_remaining_error() -> None:
    deadline = time.perf_counter() + 0.02
    remaining = sleep_until(deadline)
    # Waking early would break pacing; waking late is allowed under load.
    assert remaining <= 0.005
    late = sleep_until(time.perf_counter() - 1.0)
    assert late < 0
