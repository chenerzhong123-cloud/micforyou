"""Device-independent core of the live bridge.

``AudioRing`` is the bounded output buffer previously defined inline in
``experiments/run_real_tse_bridge.py``. ``BridgeEngine`` owns the same
worker/callback split and fault-silence contract as the live script, but takes
the DSP chain as an injectable callable so tests can exercise overflow and
inference-failure behavior without torch or audio hardware. ``LatencyLedger``
audits per-block arrival and write timestamps without storing audio.
"""

from __future__ import annotations

import bisect
from collections import deque
from dataclasses import dataclass
import queue
import threading
import time
from typing import Callable

import numpy as np

Transform = Callable[[np.ndarray], np.ndarray]
FlushTransform = Callable[[], np.ndarray]


class AudioRing:
    """Bounded FIFO of mono float32 blocks; overflow clears instead of growing."""

    def __init__(self, maximum_frames: int):
        self.maximum_frames = maximum_frames
        self.blocks: deque[np.ndarray] = deque()
        self.offset = 0
        self.frames = 0
        self.maximum_observed = 0
        self.total_popped = 0
        self.lock = threading.Lock()

    def push(self, audio: np.ndarray) -> bool:
        value = np.asarray(audio, dtype=np.float32).reshape(-1)
        if not len(value):
            return True
        with self.lock:
            if self.frames + len(value) > self.maximum_frames:
                self.blocks.clear()
                self.offset = 0
                self.frames = 0
                return False
            self.blocks.append(value)
            self.frames += len(value)
            self.maximum_observed = max(self.maximum_observed, self.frames)
        return True

    def pop(self, count: int) -> tuple[np.ndarray, int]:
        result = np.zeros(count, dtype=np.float32)
        written = 0
        with self.lock:
            while written < count and self.blocks:
                block = self.blocks[0]
                take = min(count - written, len(block) - self.offset)
                result[written : written + take] = block[self.offset : self.offset + take]
                written += take
                self.offset += take
                self.frames -= take
                if self.offset == len(block):
                    self.blocks.popleft()
                    self.offset = 0
        self.total_popped += written
        return result, written

    def clear(self) -> None:
        with self.lock:
            # Samples removed by clear() never reach the output; keep the
            # popped counter aligned with emitted audio positions.
            self.total_popped += self.frames
            self.blocks.clear()
            self.offset = 0
            self.frames = 0

    def available(self) -> int:
        with self.lock:
            return self.frames


@dataclass(frozen=True)
class OutputBlockTiming:
    position: int
    frames: int
    arrival_seconds: float
    write_seconds: float

    @property
    def latency_ms(self) -> float:
        return (self.write_seconds - self.arrival_seconds) * 1000.0


class LatencyLedger:
    """Maps output writes back to input arrivals by sample position.

    Positions are frames at the bridge sample rate (48 kHz). Arrival is the
    monotonic clock reading when a block entered the bridge (the real duplex
    callback hands a block in); write is when the same audio position left the
    output ring toward BlackHole. Content is never stored, only timestamps and
    counts.
    """

    def __init__(self, maximum_entries: int = 400_000):
        self.maximum_entries = maximum_entries
        self._starts: list[int] = []
        self._arrivals: list[float] = []
        self._outputs: list[OutputBlockTiming] = []
        self.lock = threading.Lock()

    def record_input(self, position: int, frames: int, arrival_seconds: float) -> None:
        with self.lock:
            if self._starts and position <= self._starts[-1]:
                return
            self._starts.append(position)
            self._arrivals.append(arrival_seconds)

    def record_output(self, position: int, frames: int, write_seconds: float) -> None:
        with self.lock:
            if len(self._outputs) >= self.maximum_entries:
                return
            arrival = self._arrival_for(position)
            if arrival is None:
                return
            self._outputs.append(
                OutputBlockTiming(position, frames, arrival, write_seconds)
            )

    def _arrival_for(self, position: int) -> float | None:
        index = bisect.bisect_right(self._starts, position) - 1
        if index < 0:
            return None
        return self._arrivals[index]

    def blocks(self) -> list[OutputBlockTiming]:
        """Snapshot of recorded output blocks (timestamps only, no audio)."""
        with self.lock:
            return list(self._outputs)

    def summary(self) -> dict:
        with self.lock:
            outputs = list(self._outputs)
        if not outputs:
            return {"blocks": 0}
        latencies = np.asarray([block.latency_ms for block in outputs])
        return {
            "blocks": len(outputs),
            "latency_ms_p50": float(np.percentile(latencies, 50)),
            "latency_ms_p95": float(np.percentile(latencies, 95)),
            "latency_ms_max": float(latencies.max()),
            "latency_ms_mean": float(latencies.mean()),
            "position_first": outputs[0].position,
            "position_last": outputs[-1].position + outputs[-1].frames,
        }


class BridgeEngine:
    """Bounded queues plus a worker thread around an injectable DSP chain.

    Fault contract (identical to the live bridge): any worker exception, output
    overflow, or input queue overflow latches a fault, clears buffered audio,
    and makes every subsequent output block silence. Raw input is never passed
    through as a fallback.
    """

    def __init__(
        self,
        transform: Transform,
        flush_transform: FlushTransform,
        *,
        input_bound_blocks: int,
        ring_maximum_frames: int,
        name: str = "micforyou-bridge",
    ):
        if input_bound_blocks < 1:
            raise ValueError("input_bound_blocks must be positive")
        self.transform = transform
        self.flush_transform = flush_transform
        self.input_queue: queue.Queue[np.ndarray | None] = queue.Queue(
            maxsize=input_bound_blocks
        )
        self.output_ring = AudioRing(ring_maximum_frames)
        self.fault = threading.Event()
        self.worker_done = threading.Event()
        self.errors: list[str] = []
        self.input_queue_max = 0
        self.blocks_processed = 0
        self._thread = threading.Thread(target=self._worker, name=name, daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        try:
            while True:
                block = self.input_queue.get()
                if block is None:
                    break
                self.input_queue_max = max(self.input_queue_max, self.input_queue.qsize())
                self._emit(self.transform(block))
                self.blocks_processed += 1
            self._emit(self.flush_transform())
        except Exception as error:  # fault-silence: never propagate raw audio
            self.errors.append(repr(error))
            self.fault.set()
            self.output_ring.clear()
        finally:
            self.worker_done.set()

    def _emit(self, value: np.ndarray) -> None:
        if len(value) and not self.output_ring.push(value):
            raise RuntimeError("output queue exceeded its bound")

    def submit(self, block: np.ndarray) -> bool:
        """Hand one input block in from the capture callback context."""
        if self.fault.is_set():
            return False
        try:
            self.input_queue.put_nowait(block)
        except queue.Full:
            self.errors.append("input queue exceeded its bound")
            self.fault.set()
            self.output_ring.clear()
            return False
        return True

    def write_output(self, frames: int) -> tuple[np.ndarray, int]:
        """Fill one output callback block; silence on fault or empty ring."""
        if self.fault.is_set():
            return np.zeros(frames, dtype=np.float32), 0
        return self.output_ring.pop(frames)

    def finish(self, timeout: float = 30.0) -> bool:
        """Stop capture, drain the chain, and wait for the worker."""
        if not self.fault.is_set():
            try:
                self.input_queue.put_nowait(None)
            except queue.Full:
                self.input_queue.put(None, timeout=timeout)
        done = self.worker_done.wait(timeout=timeout)
        return bool(done)

    def stats(self) -> dict:
        return {
            "fault": self.fault.is_set(),
            "errors": list(self.errors),
            "input_queue_max_blocks": self.input_queue_max,
            "output_queue_max_frames": self.output_ring.maximum_observed,
            "blocks_processed": self.blocks_processed,
        }


def sleep_until(deadline_seconds: float) -> float:
    """Sleep until the monotonic deadline; return the signed pacing error."""
    remaining = deadline_seconds - time.perf_counter()
    if remaining > 0:
        time.sleep(remaining)
    return deadline_seconds - time.perf_counter()
