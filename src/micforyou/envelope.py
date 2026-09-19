"""Deterministic inference-delay envelopes for paced bridge testing.

This module does not emulate another CPU.  It wraps a real or synthetic DSP
call and, when that call finishes faster than the selected target, waits out
the remainder.  The result is useful for queue, latency and fault testing at a
known service-time distribution; it is never evidence of model speed on the
named target machine.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Generic, TypeVar

import numpy as np

from micforyou.reporting import percentile_summary

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


@dataclass(frozen=True)
class DelayProfile:
    """Desired per-call service-time quantiles in milliseconds."""

    name: str
    minimum_ms: float
    p50_ms: float
    p95_ms: float
    maximum_ms: float

    def validate(self) -> None:
        values = (self.minimum_ms, self.p50_ms, self.p95_ms, self.maximum_ms)
        if any(value < 0 for value in values):
            raise ValueError("delay profile values must be non-negative")
        if list(values) != sorted(values):
            raise ValueError("delay profile must satisfy min <= p50 <= p95 <= max")


PROFILES = {
    "nominal": DelayProfile("nominal", 2.0, 4.0, 7.0, 10.0),
    "boundary": DelayProfile("boundary", 4.0, 7.0, 10.0, 20.0),
    "overload": DelayProfile("overload", 9.0, 12.0, 16.0, 25.0),
}


def build_delay_trace(
    profile: DelayProfile,
    *,
    count: int = 1000,
    seed: int = 20_260_919,
) -> np.ndarray:
    """Build a reproducible, shuffled trace matching the requested quantiles."""
    profile.validate()
    if count < 20:
        raise ValueError("delay trace needs at least 20 samples")
    quantiles = (np.arange(count, dtype=np.float64) + 0.5) / count
    values = np.interp(
        quantiles,
        [0.0, 0.50, 0.95, 1.0],
        [profile.minimum_ms, profile.p50_ms, profile.p95_ms, profile.maximum_ms],
    )
    values[-1] = profile.maximum_ms
    return np.random.default_rng(seed).permutation(values)


class DelayEnvelope(Generic[InputT, OutputT]):
    """Pad calls to a deterministic minimum duration and record observations."""

    def __init__(
        self,
        transform: Callable[[InputT], OutputT],
        trace_ms: np.ndarray | list[float],
        *,
        clock: Callable[[], float] = time.perf_counter,
        sleeper: Callable[[float], None] = time.sleep,
        spin_margin_seconds: float = 0.002,
    ):
        trace = np.asarray(trace_ms, dtype=np.float64).reshape(-1)
        if not len(trace) or not np.isfinite(trace).all() or (trace < 0).any():
            raise ValueError("trace_ms must contain finite non-negative values")
        self.transform = transform
        self.trace_ms = trace
        self.clock = clock
        self.sleeper = sleeper
        if spin_margin_seconds < 0:
            raise ValueError("spin_margin_seconds must be non-negative")
        self.spin_margin_seconds = spin_margin_seconds
        self.calls = 0
        self.target_ms: list[float] = []
        self.underlying_ms: list[float] = []
        self.requested_padding_ms: list[float] = []
        self.injected_ms: list[float] = []
        self.observed_ms: list[float] = []

    def __call__(self, value: InputT) -> OutputT:
        target_ms = float(self.trace_ms[self.calls % len(self.trace_ms)])
        started = self.clock()
        result = self.transform(value)
        underlying_ms = (self.clock() - started) * 1000.0
        deadline = started + target_ms / 1000.0
        remaining = deadline - self.clock()
        requested_padding = max(0.0, remaining)
        if remaining > self.spin_margin_seconds:
            self.sleeper(remaining - self.spin_margin_seconds)
        while self.clock() < deadline:
            pass
        observed_ms = (self.clock() - started) * 1000.0

        self.calls += 1
        self.target_ms.append(target_ms)
        self.underlying_ms.append(underlying_ms)
        self.requested_padding_ms.append(requested_padding * 1000.0)
        self.injected_ms.append(max(0.0, observed_ms - underlying_ms))
        self.observed_ms.append(observed_ms)
        return result

    def summary(self) -> dict:
        over_target = sum(
            actual > target + 0.25
            for actual, target in zip(self.underlying_ms, self.target_ms)
        )
        return {
            "calls": self.calls,
            "target_ms": percentile_summary(self.target_ms),
            "underlying_ms": percentile_summary(self.underlying_ms),
            "requested_padding_ms": percentile_summary(self.requested_padding_ms),
            "injected_ms": percentile_summary(self.injected_ms),
            "observed_ms": percentile_summary(self.observed_ms),
            "underlying_over_target_calls": over_target,
        }
