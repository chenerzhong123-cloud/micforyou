"""Explicit filtering/raw mode switch, committed only by an audio callback.

Models and conditioning remain owned by the factory. Each resume constructs a
fresh DSP chain outside the callback. Retired workers have private rings, so a
late inference result cannot enter the current output generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Callable

import numpy as np

from .bridging import BridgeEngine


@dataclass
class ModeRequest:
    mode: str
    engine: BridgeEngine | None
    done: threading.Event = field(default_factory=threading.Event)
    error: str | None = None


class SwitchableBridge:
    def __init__(self, factory: Callable[[], BridgeEngine], initial_mode: str = "tse", revision: int = 0):
        if initial_mode not in {"tse", "passthrough"}:
            raise ValueError("invalid initial mode")
        self.factory = factory
        self.engine = factory() if initial_mode == "tse" else None
        self.mode = initial_mode
        self.revision = revision
        self.fault = threading.Event()
        self.errors: list[str] = []
        self._lock = threading.Lock()
        self._commands = threading.Lock()
        self._pending: ModeRequest | None = None
        self._retired: list[BridgeEngine] = []
        self._closed = False

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "processing_mode": "none" if self.fault.is_set() else self.mode,
                "mode_reason": "user_pause" if self.mode == "passthrough" else None,
                "mode_revision": self.revision,
                "requested_mode": self._pending.mode if self._pending else None,
            }

    def switch(self, mode: str, timeout: float = 5.0) -> dict:
        if mode not in {"tse", "passthrough"} or timeout <= 0:
            raise ValueError("invalid mode or timeout")
        deadline = time.monotonic() + timeout
        if not self._commands.acquire(timeout=timeout):
            raise TimeoutError("another mode request is in progress")
        candidate = None
        try:
            with self._lock:
                self._require_live()
                if mode == self.mode:
                    return self._snapshot_unlocked()
                retired = list(self._retired)
            for previous in retired:
                if not previous.worker_done.wait(max(0, deadline - time.monotonic())):
                    raise TimeoutError("previous inference has not finished; raw audio continues")
            with self._lock:
                self._retired = [item for item in self._retired if not item.worker_done.is_set()]
            # No audio callback waits for model/resampler/state construction.
            candidate = self.factory() if mode == "tse" else None
            request = ModeRequest(mode, candidate)
            with self._lock:
                self._require_live()
                if time.monotonic() >= deadline:
                    raise TimeoutError("mode preparation timed out")
                self._pending = request
            request.done.wait(max(0, deadline - time.monotonic()))
            with self._lock:
                if not request.done.is_set():
                    if self._pending is request:
                        self._pending = None
                    raise TimeoutError("audio callback did not confirm mode switch")
                if request.error:
                    raise RuntimeError(request.error)
                candidate = None  # now owned by this bridge
                return self._snapshot_unlocked()
        finally:
            if candidate is not None:
                candidate.discard()
            self._commands.release()

    def _snapshot_unlocked(self) -> dict:
        return {
            "processing_mode": "none" if self.fault.is_set() else self.mode,
            "mode_reason": "user_pause" if self.mode == "passthrough" else None,
            "mode_revision": self.revision,
            "requested_mode": None,
        }

    def _require_live(self) -> None:
        if self._closed or self.fault.is_set() or (
            self.engine is not None and self.engine.fault.is_set()
        ):
            raise RuntimeError("audio route is stopped or faulted")

    def _fault_unlocked(self, reason: str) -> None:
        if not self.fault.is_set():
            self.errors.append(reason)
            self.fault.set()
        if self.engine is not None:
            self.engine.latch_fault(reason)
        if self._pending:
            self._pending.error = reason
            self._pending.done.set()
            self._pending = None

    def latch_fault(self, reason: str) -> None:
        with self._lock:
            self._fault_unlocked(reason)

    def process(self, block: np.ndarray | None, frames: int) -> tuple[np.ndarray, int]:
        """Called once per duplex callback; mono output, exact raw samples."""
        with self._lock:
            if self.engine is not None and self.engine.fault.is_set():
                self._fault_unlocked("; ".join(self.engine.errors))
            if self.fault.is_set() or self._closed:
                return np.zeros(frames, dtype=np.float32), 0
            if self._pending is not None:
                request = self._pending
                if self.engine is not None:
                    self.engine.discard()
                    self._retired.append(self.engine)
                self.engine = request.engine
                self.mode = request.mode
                self.revision += 1
                self._pending = None
                request.done.set()
            if self.mode == "passthrough":
                if block is None:
                    return np.zeros(frames, dtype=np.float32), 0
                return np.asarray(block, dtype=np.float32).reshape(-1)[:frames], frames
            assert self.engine is not None
            if block is not None:
                self.engine.submit(block)
            value, written = self.engine.write_output(frames)
            if self.engine.fault.is_set():
                self._fault_unlocked("; ".join(self.engine.errors))
                return np.zeros(frames, dtype=np.float32), 0
            return value, written

    def finish(self, timeout: float = 30.0) -> bool:
        with self._lock:
            if self._pending:
                request = self._pending
                if request.engine is not None:
                    request.engine.discard()
                request.error = "audio route is ending"
                request.done.set()
                self._pending = None
            current = self.engine
        return current.finish(timeout) if current is not None else True

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._fault_unlocked("audio route closed")

    @property
    def output_ring(self):
        return self.engine.output_ring if self.engine is not None else None

    def stats(self) -> dict:
        with self._lock:
            return {
                **(self.engine.stats() if self.engine is not None else {}),
                **self._snapshot_unlocked(),
                "fault": self.fault.is_set(),
                "errors": list(self.errors),
            }
