"""Replay deterministic inference-time envelopes through the bridge core.

This is a queue/latency/fault harness, not an M1 performance emulator.  It
uses a one-block-in/one-block-out synthetic DSP call and pads each call to a
selected service-time distribution.  No audio device, model, recording or ASR
is opened.  Later model adapters can wrap their real transform with the same
``DelayEnvelope`` class and preserve the measurement contract.

Examples:

    uv run python experiments/simulate_runtime_envelope.py \
      --profiles nominal boundary overload --duration 120 \
      --result /Users/deuce/claudeproject/codexworks/micforyou/runs/envelope.json

    # Thirty-minute conservative soak after short profiles are understood:
    uv run python experiments/simulate_runtime_envelope.py \
      --profiles boundary --duration 1800 \
      --result /Users/deuce/claudeproject/codexworks/micforyou/runs/envelope-30m.json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from micforyou.bridging import BridgeEngine, LatencyLedger, sleep_until
from micforyou.envelope import DelayEnvelope, PROFILES, build_delay_trace
from micforyou.reporting import collect_system_info, percentile_summary

SAMPLE_RATE = 48_000
DEFAULT_BLOCK = 480


class ResourceSampler(threading.Thread):
    """Sample RSS and host load without retaining audio or blocking pacing."""

    def __init__(self, interval_seconds: float):
        super().__init__(daemon=True)
        self.interval = interval_seconds
        self.started_at = time.monotonic()
        self.samples: list[dict] = []
        self.stop = threading.Event()

    def _rss_kb(self) -> int | None:
        try:
            output = subprocess.run(
                ["ps", "-o", "rss=", "-p", str(os.getpid())],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.strip()
            return int(output) if output else None
        except (OSError, ValueError, subprocess.SubprocessError):
            return None

    def run(self) -> None:
        while not self.stop.wait(self.interval):
            self.samples.append(
                {
                    "elapsed_s": round(time.monotonic() - self.started_at, 3),
                    "rss_kb": self._rss_kb(),
                    "loadavg1": os.getloadavg()[0],
                }
            )


def synthetic_transform(block: np.ndarray) -> np.ndarray:
    """Stand-in for a 10 ms streaming model call; preserves content and length."""
    return np.asarray(block, dtype=np.float32).copy()


def run_profile(
    name: str,
    *,
    duration_seconds: float,
    block_frames: int,
    queue_ms: float,
    prefill_ms: float,
    trace_samples: int,
    seed: int,
    resource_interval: float,
) -> dict:
    profile = PROFILES[name]
    trace = build_delay_trace(profile, count=trace_samples, seed=seed)
    envelope = DelayEnvelope(synthetic_transform, trace)
    maximum_frames = round(SAMPLE_RATE * queue_ms / 1000.0)
    prefill_frames = round(SAMPLE_RATE * prefill_ms / 1000.0)
    engine = BridgeEngine(
        envelope,
        lambda: np.empty(0, dtype=np.float32),
        input_bound_blocks=max(2, maximum_frames // block_frames),
        ring_maximum_frames=maximum_frames,
        output_prefill_frames=prefill_frames,
        name=f"micforyou-envelope-{name}",
    )
    ledger = LatencyLedger()
    sampler = ResourceSampler(resource_interval)
    sampler.start()

    total_ticks = int(round(duration_seconds * SAMPLE_RATE / block_frames))
    block_seconds = block_frames / SAMPLE_RATE
    pacing_errors_ms: list[float] = []
    position_in = 0
    output_samples = 0
    startup_silence_frames = 0
    underrun_frames = 0
    output_started = False
    nonfinite = 0
    peak = 0.0
    fault_tick: int | None = None
    started = time.perf_counter()

    for index in range(total_ticks):
        if engine.fault.is_set():
            fault_tick = index
            break
        pacing_errors_ms.append(sleep_until(started + index * block_seconds) * 1000.0)
        value = np.full(block_frames, ((index % 101) - 50) / 100.0, dtype=np.float32)
        arrival = time.perf_counter()
        if not engine.submit(value):
            fault_tick = index
            break
        ledger.record_input(position_in, block_frames, arrival)
        position_in += block_frames
        output, written = engine.write_output(block_frames)
        if written:
            output_started = True
            audio_start = engine.output_ring.total_popped - written
            ledger.record_output(audio_start, written, time.perf_counter())
            chunk = output[:written]
            output_samples += written
            finite = np.isfinite(chunk)
            nonfinite += int((~finite).sum())
            peak = max(peak, float(np.abs(np.where(finite, chunk, 0.0)).max()))
        elif output_started:
            underrun_frames += block_frames
        else:
            startup_silence_frames += block_frames

    worker_stopped = engine.finish(timeout=max(5.0, queue_ms / 1000.0 * 4.0))
    if not engine.fault.is_set():
        drain_deadline = time.perf_counter() + max(2.0, queue_ms / 1000.0 * 2.0)
        while engine.output_ring.available() and time.perf_counter() < drain_deadline:
            sleep_until(time.perf_counter() + block_seconds)
            output, written = engine.write_output(block_frames)
            if written:
                audio_start = engine.output_ring.total_popped - written
                ledger.record_output(audio_start, written, time.perf_counter())
                chunk = output[:written]
                output_samples += written
                finite = np.isfinite(chunk)
                nonfinite += int((~finite).sum())
                peak = max(peak, float(np.abs(np.where(finite, chunk, 0.0)).max()))

    sampler.stop.set()
    sampler.join(timeout=2)
    post_fault_output, post_fault_written = engine.write_output(block_frames)
    fault_silence = {
        "checked": engine.fault.is_set(),
        "written_frames": post_fault_written,
        "all_zero": bool(np.count_nonzero(post_fault_output) == 0),
    }
    status = "FAULT" if engine.fault.is_set() else "COMPLETED"
    integrity_pass = (
        status == "COMPLETED"
        and worker_stopped
        and output_samples == position_in
        and nonfinite == 0
    )

    return {
        "profile": {
            "name": profile.name,
            "minimum_ms": profile.minimum_ms,
            "p50_ms": profile.p50_ms,
            "p95_ms": profile.p95_ms,
            "maximum_ms": profile.maximum_ms,
            "trace_samples": trace_samples,
            "trace_seed": seed,
        },
        "scope": {
            "synthetic_dsp": True,
            "real_model": False,
            "audio_devices_opened": False,
            "asr_used": False,
            "claim": "queue/latency/fault behavior at this service-time envelope only",
            "not_a_claim": "model performance on M1 or any other target hardware",
        },
        "status": status,
        "integrity_pass": integrity_pass,
        "fault_tick": fault_tick,
        "worker_stopped": worker_stopped,
        "config": {
            "sample_rate": SAMPLE_RATE,
            "block_frames": block_frames,
            "block_ms": block_seconds * 1000.0,
            "duration_seconds": duration_seconds,
            "queue_ms": queue_ms,
            "prefill_ms": prefill_ms,
        },
        "input_samples": position_in,
        "output_samples": output_samples,
        "length_match": output_samples == position_in,
        "nonfinite_samples": nonfinite,
        "output_peak": peak,
        "startup_silence_ms": startup_silence_frames / SAMPLE_RATE * 1000.0,
        "underrun_ms": underrun_frames / SAMPLE_RATE * 1000.0,
        "bridge_latency": ledger.summary(),
        "pacing_error_ms": percentile_summary(pacing_errors_ms),
        "envelope": envelope.summary(),
        "engine": engine.stats(),
        "fault_silence": fault_silence,
        "wall_seconds": time.perf_counter() - started,
        "resource_samples": sampler.samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profiles",
        choices=sorted(PROFILES),
        nargs="+",
        default=["nominal", "boundary", "overload"],
    )
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--block-frames", type=int, default=DEFAULT_BLOCK)
    parser.add_argument("--queue-ms", type=float, default=500.0)
    parser.add_argument(
        "--prefill-ms",
        type=float,
        default=50.0,
        help="explicit startup jitter buffer; counted in bridge latency",
    )
    parser.add_argument("--trace-samples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20_260_919)
    parser.add_argument("--resource-interval", type=float, default=10.0)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()

    if args.duration <= 0:
        raise SystemExit("--duration must be positive")
    if args.block_frames <= 0 or args.queue_ms <= 0:
        raise SystemExit("--block-frames and --queue-ms must be positive")
    if args.prefill_ms < 0 or args.prefill_ms > args.queue_ms:
        raise SystemExit("--prefill-ms must be between zero and --queue-ms")
    if args.resource_interval <= 0:
        raise SystemExit("--resource-interval must be positive")

    payload = {
        "schema": "micforyou-runtime-envelope-1",
        "system": collect_system_info(),
        "command": [str(part) for part in sys.argv],
        "profiles": [],
        "interpretation": [
            "This harness validates bridge behavior under an imposed service-time envelope.",
            "It does not throttle or emulate M1 hardware and cannot replace a final Mac B benchmark.",
            "Run the real model on Mac A separately; later wrap its transform with DelayEnvelope.",
        ],
    }
    for index, name in enumerate(args.profiles):
        print(f"running envelope profile {name} for {args.duration:g}s", flush=True)
        result = run_profile(
            name,
            duration_seconds=args.duration,
            block_frames=args.block_frames,
            queue_ms=args.queue_ms,
            prefill_ms=args.prefill_ms,
            trace_samples=args.trace_samples,
            seed=args.seed + index,
            resource_interval=args.resource_interval,
        )
        payload["profiles"].append(result)
        print(
            json.dumps(
                {
                    "profile": name,
                    "status": result["status"],
                    "length_match": result["length_match"],
                    "bridge_latency": result["bridge_latency"],
                    "underrun_ms": result["underrun_ms"],
                    "engine": result["engine"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )

    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"result json: {args.result}")


if __name__ == "__main__":
    main()
