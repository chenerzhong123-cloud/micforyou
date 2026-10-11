"""Device-independent core of the live bridge.

``AudioRing`` is the bounded output buffer previously defined inline in
``tools/inference/run_real_tse_bridge.py``. ``BridgeEngine`` owns the same
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


def mono_to_stereo_passthrough(audio: np.ndarray, frames: int) -> np.ndarray:
    """Render an explicit raw-microphone fallback block for BlackHole 2ch."""
    value = np.asarray(audio, dtype=np.float32)
    if value.ndim == 2:
        if value.shape[1] < 1:
            raise ValueError("passthrough input must have at least one channel")
        mono = value[:frames, 0]
    else:
        mono = value.reshape(-1)[:frames]
    if len(mono) != frames:
        raise ValueError("passthrough input does not contain the requested frames")
    return np.repeat(mono[:, None], 2, axis=1)


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
        self._space_available = threading.Condition(self.lock)

    def push(self, audio: np.ndarray) -> bool:
        value = np.asarray(audio, dtype=np.float32).reshape(-1)
        if not len(value):
            return True
        with self._space_available:
            if self.frames + len(value) > self.maximum_frames:
                self.blocks.clear()
                self.offset = 0
                self.frames = 0
                self._space_available.notify_all()
                return False
            self.blocks.append(value)
            self.frames += len(value)
            self.maximum_observed = max(self.maximum_observed, self.frames)
        return True

    def push_wait(
        self,
        audio: np.ndarray,
        *,
        timeout: float,
        abort: threading.Event | None = None,
    ) -> bool:
        """Push after bounded backpressure without exceeding the ring bound."""
        value = np.asarray(audio, dtype=np.float32).reshape(-1)
        if not len(value):
            return True
        if len(value) > self.maximum_frames:
            return False
        deadline = time.monotonic() + timeout
        with self._space_available:
            while self.frames + len(value) > self.maximum_frames:
                if abort is not None and abort.is_set():
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._space_available.wait(timeout=remaining)
            self.blocks.append(value)
            self.frames += len(value)
            self.maximum_observed = max(self.maximum_observed, self.frames)
            return True

    def pop(self, count: int) -> tuple[np.ndarray, int]:
        result = np.zeros(count, dtype=np.float32)
        written = 0
        with self._space_available:
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
            if written:
                self._space_available.notify_all()
        self.total_popped += written
        return result, written

    def clear(self) -> None:
        with self._space_available:
            # Samples removed by clear() never reach the output; keep the
            # popped counter aligned with emitted audio positions.
            self.total_popped += self.frames
            self.blocks.clear()
            self.offset = 0
            self.frames = 0
            self._space_available.notify_all()

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


class CallbackLivenessMonitor:
    """Detect a device stream whose audio callbacks stop advancing.

    ``observe`` is intentionally tiny so it can run in the audio callback.
    The controller calls ``check`` from its normal supervision loop; this
    class does not own a thread and never tries to reopen a device itself.
    """

    def __init__(self, timeout_seconds: float, *, started_at: float | None = None):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self.started_at = time.monotonic() if started_at is None else started_at
        self.last_callback_at: float | None = None
        self.callback_count = 0
        self.stall_count = 0
        self._stalled = False
        self._lock = threading.Lock()

    def observe(self, now: float | None = None) -> None:
        observed_at = time.monotonic() if now is None else now
        with self._lock:
            self.last_callback_at = observed_at
            self.callback_count += 1
            self._stalled = False

    def check(self, now: float | None = None) -> float | None:
        """Return callback age when newly stalled, otherwise ``None``."""
        checked_at = time.monotonic() if now is None else now
        with self._lock:
            reference = self.last_callback_at
            if reference is None:
                reference = self.started_at
            age = checked_at - reference
            if age <= self.timeout_seconds or self._stalled:
                return None
            self._stalled = True
            self.stall_count += 1
            return age

    def stats(self, now: float | None = None) -> dict:
        checked_at = time.monotonic() if now is None else now
        with self._lock:
            reference = self.last_callback_at
            age = None if reference is None else max(0.0, checked_at - reference)
            return {
                "timeout_seconds": self.timeout_seconds,
                "callback_count": self.callback_count,
                "stall_count": self.stall_count,
                "last_callback_age_seconds": age,
            }


class RecoveryCircuitBreaker:
    """Bound automatic recovery attempts within a rolling time window."""

    def __init__(self, maximum_recoveries: int, window_seconds: float):
        if maximum_recoveries < 0:
            raise ValueError("maximum_recoveries must be non-negative")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.maximum_recoveries = maximum_recoveries
        self.window_seconds = window_seconds
        self._recoveries: deque[float] = deque()
        self.total_allowed = 0
        self.total_rejected = 0

    def allow(self, now: float | None = None) -> bool:
        checked_at = time.monotonic() if now is None else now
        cutoff = checked_at - self.window_seconds
        while self._recoveries and self._recoveries[0] <= cutoff:
            self._recoveries.popleft()
        if len(self._recoveries) >= self.maximum_recoveries:
            self.total_rejected += 1
            return False
        self._recoveries.append(checked_at)
        self.total_allowed += 1
        return True

    def stats(self, now: float | None = None) -> dict:
        checked_at = time.monotonic() if now is None else now
        cutoff = checked_at - self.window_seconds
        active = sum(timestamp > cutoff for timestamp in self._recoveries)
        return {
            "maximum_recoveries": self.maximum_recoveries,
            "window_seconds": self.window_seconds,
            "recoveries_in_window": active,
            "total_allowed": self.total_allowed,
            "total_rejected": self.total_rejected,
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
        output_prefill_frames: int = 0,
        name: str = "micforyou-bridge",
    ):
        if input_bound_blocks < 1:
            raise ValueError("input_bound_blocks must be positive")
        if output_prefill_frames < 0 or output_prefill_frames > ring_maximum_frames:
            raise ValueError(
                "output_prefill_frames must be between zero and ring_maximum_frames"
            )
        self.transform = transform
        self.flush_transform = flush_transform
        self.input_queue: queue.Queue[np.ndarray | None] = queue.Queue(
            maxsize=input_bound_blocks
        )
        self.output_ring = AudioRing(ring_maximum_frames)
        self.output_prefill_frames = output_prefill_frames
        self.output_started = output_prefill_frames == 0
        self.fault = threading.Event()
        self.worker_done = threading.Event()
        self.errors: list[str] = []
        self.input_queue_max = 0
        self.blocks_processed = 0
        self._fault_lock = threading.Lock()
        self._finishing = threading.Event()
        self._thread = threading.Thread(target=self._worker, name=name, daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        try:
            while True:
                block = self.input_queue.get()
                if block is None:
                    break
                if self.fault.is_set():
                    break
                self.input_queue_max = max(self.input_queue_max, self.input_queue.qsize())
                output = self.transform(block)
                if self.fault.is_set():
                    break
                self._emit(output)
                self.blocks_processed += 1
            if not self.fault.is_set():
                self._emit(self.flush_transform())
        except Exception as error:  # fault-silence: never propagate raw audio
            self.latch_fault(repr(error))
        finally:
            self.worker_done.set()

    def _emit(self, value: np.ndarray) -> None:
        if not len(value):
            return
        if self._finishing.is_set():
            accepted = self.output_ring.push_wait(
                value, timeout=2.0, abort=self.fault
            )
        else:
            accepted = self.output_ring.push(value)
        if not accepted:
            raise RuntimeError("output queue exceeded its bound")

    def submit(self, block: np.ndarray) -> bool:
        """Hand one input block in from the capture callback context."""
        if self.fault.is_set():
            return False
        try:
            self.input_queue.put_nowait(block)
        except queue.Full:
            self.latch_fault("input queue exceeded its bound")
            return False
        return True

    def latch_fault(self, reason: str) -> bool:
        """Latch fault-silence and wake an idle worker.

        Returns ``True`` only for the first caller that transitions the engine
        into FAULT. This is also the safe entry point for controller/device
        failures such as a stalled CoreAudio callback.
        """
        with self._fault_lock:
            if self.fault.is_set():
                return False
            self.errors.append(reason)
            self.fault.set()
            self.output_ring.clear()
            try:
                self.input_queue.put_nowait(None)
            except queue.Full:
                # A busy worker will observe ``fault`` after its current block.
                pass
            return True

    def write_output(self, frames: int) -> tuple[np.ndarray, int]:
        """Fill one output callback block; silence on fault or empty ring."""
        if self.fault.is_set():
            return np.zeros(frames, dtype=np.float32), 0
        if not self.output_started:
            if self.output_ring.available() < self.output_prefill_frames:
                return np.zeros(frames, dtype=np.float32), 0
            self.output_started = True
        return self.output_ring.pop(frames)

    def finish(self, timeout: float = 30.0) -> bool:
        """Stop capture, drain the chain, and wait for the worker."""
        if self.worker_done.is_set():
            return True
        if self.fault.is_set():
            return bool(self.worker_done.wait(timeout=timeout))
        self._finishing.set()
        try:
            self.input_queue.put_nowait(None)
        except queue.Full:
            try:
                self.input_queue.put(None, timeout=timeout)
            except queue.Full:
                return self.worker_done.is_set()
        done = self.worker_done.wait(timeout=timeout)
        return bool(done)

    def discard(self) -> None:
        """Retire this generation without flushing pending model audio."""
        self.latch_fault("streaming generation retired")
        while True:
            try:
                self.input_queue.get_nowait()
            except queue.Empty:
                break
        # A worker already awaiting get() still needs a wake-up sentinel.
        try:
            self.input_queue.put_nowait(None)
        except queue.Full:
            pass  # another retire caller already supplied the sentinel

    def stats(self) -> dict:
        return {
            "fault": self.fault.is_set(),
            "errors": list(self.errors),
            "input_queue_max_blocks": self.input_queue_max,
            "output_queue_max_frames": self.output_ring.maximum_observed,
            "output_prefill_frames": self.output_prefill_frames,
            "output_started": self.output_started,
            "blocks_processed": self.blocks_processed,
        }


def sleep_until(deadline_seconds: float) -> float:
    """Sleep until the monotonic deadline; return the signed pacing error."""
    remaining = deadline_seconds - time.perf_counter()
    if remaining > 0:
        time.sleep(remaining)
    return deadline_seconds - time.perf_counter()
