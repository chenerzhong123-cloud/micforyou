"""Deterministic synthetic mixture and pulse generation for benchmarks.

Everything here is reproducible from a seed, contains no human speech, and can
be produced block-by-block so 30-minute simulations do not buffer hundreds of
megabytes. The mixture mimics two speech-shaped sources at a chosen target-to-
interferer RMS ratio plus a noise floor; broadband pulses are embedded at known
positions so tools can verify input/output alignment without recording anyone.
"""

from __future__ import annotations

from collections.abc import Iterator
import numpy as np
from scipy.signal import lfilter


DEFAULT_SEED = 20_260_915


class _ArVoice:
    """Lowpass noise with a slow envelope follower: speech-shaped, not speech."""

    def __init__(
        self,
        rng: np.random.Generator,
        color: float,
        mod_rate_hz: float,
        sample_rate: int,
    ):
        self._rng = rng
        self._color = color
        self._a = float(np.exp(-2.0 * np.pi * mod_rate_hz / sample_rate))
        self._z_noise = np.zeros(1)
        self._z_env1 = np.zeros(1)
        self._z_env2 = np.zeros(1)

    def block(self, count: int) -> np.ndarray:
        white = self._rng.standard_normal(count)
        colored, self._z_noise = lfilter(
            [1.0 - self._color], [1.0, -self._color], white, zi=self._z_noise
        )
        envelope = np.abs(colored)
        envelope, self._z_env1 = lfilter(
            [1.0 - self._a], [1.0, -self._a], envelope, zi=self._z_env1
        )
        envelope, self._z_env2 = lfilter(
            [1.0 - self._a], [1.0, -self._a], envelope, zi=self._z_env2
        )
        peak = max(float(envelope.max()), 1e-9)
        return colored * (envelope / peak)


def pulse_positions(
    total_frames: int,
    sample_rate: int,
    every_seconds: float,
    first_seconds: float = 1.0,
) -> list[int]:
    positions: list[int] = []
    position = int(round(first_seconds * sample_rate))
    while position < total_frames:
        positions.append(position)
        position += int(round(every_seconds * sample_rate))
    return positions


def synthetic_blocks(
    total_frames: int,
    *,
    sample_rate: int = 48_000,
    seed: int = DEFAULT_SEED,
    tir_db: float = -6.0,
    pulse_every_seconds: float | None = 2.0,
    pulse_amplitude: float = 0.35,
    block_frames: int = 480,
    target_gain: float = 0.05,
) -> Iterator[np.ndarray]:
    """Yield deterministic mono float32 blocks with optional alignment pulses.

    The same seed, block size, and parameters always produce the same sample
    sequence, so benchmark candidates and repeated soaks see identical input.
    (Samples still depend on ``block_frames`` because the noise draws are
    consumed per block.)
    """
    if block_frames < 1:
        raise ValueError("block_frames must be positive")
    rng = np.random.default_rng(seed)
    target = _ArVoice(rng, color=0.92, mod_rate_hz=3.5, sample_rate=sample_rate)
    interferer = _ArVoice(rng, color=0.85, mod_rate_hz=5.0, sample_rate=sample_rate)
    interferer_gain = target_gain * 10 ** (-tir_db / 20.0)
    pulses = (
        pulse_positions(total_frames, sample_rate, pulse_every_seconds)
        if pulse_every_seconds
        else []
    )
    next_pulse = 0

    produced = 0
    while produced < total_frames:
        count = min(block_frames, total_frames - produced)
        block = (
            target.block(count) * target_gain
            + interferer.block(count) * interferer_gain
            + rng.standard_normal(count) * 0.001
        ).astype(np.float32)
        while next_pulse < len(pulses) and pulses[next_pulse] < produced + count:
            pulse = pulses[next_pulse]
            if pulse >= produced:
                block[pulse - produced] += pulse_amplitude
            next_pulse += 1
        yield block
        produced += count


def synthetic_mixture(
    seconds: float,
    *,
    sample_rate: int = 48_000,
    seed: int = DEFAULT_SEED,
    tir_db: float = -6.0,
    pulse_every_seconds: float | None = None,
) -> np.ndarray:
    """Materialize ``synthetic_blocks`` as one array (for short inputs)."""
    total = int(round(seconds * sample_rate))
    return np.concatenate(
        list(
            synthetic_blocks(
                total,
                sample_rate=sample_rate,
                seed=seed,
                tir_db=tir_db,
                pulse_every_seconds=pulse_every_seconds,
                block_frames=48_000,
            )
        )
    )
