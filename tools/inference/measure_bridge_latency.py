"""Auditable audio-path latency and stability measurement for the bridge.

Measures the distribution of "audio entered the bridge" to "the bridge handed
that audio to the output side" using only synthetic pulses and noise — no user
audio is recorded or stored, and no ASR is involved. Two clearly separated
components:

1. ``bridge_internal`` (default, always run): the exact live DSP chain
   (48 kHz -> 16 kHz -> causal TSE -> 16 kHz -> 48 kHz) inside
   ``BridgeEngine``, driven by a wall-clock-paced simulated duplex callback at
   the same 10 ms block cadence the live stream uses. Timestamps come from the
   ``LatencyLedger``; audio never leaves the process.
2. ``blackhole_roundtrip`` (optional ``--blackhole-roundtrip``): a synthetic
   pulse train played into and captured back from BlackHole 2ch to size the
   CoreAudio/BlackHole device path separately.

NOT measured here, by design: CoreAudio capture buffering before the input
callback, the BlackHole-to-Doubao hand-off, and Doubao decode/UI latency. Those
must be recorded manually by the user as a separate end-to-end experience
metric; Doubao text-appearance time must never be reported as audio latency.

Long runs double as a simulated soak: pass ``--duration 1800`` for a 30-minute
wall-clock-paced stability run (still simulated — no audio devices are opened,
so it does not replace a physical 30-minute AT-09 live run).
"""

from __future__ import annotations

import argparse
from collections import deque
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import numpy as np
import torch
import torchaudio

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from micforyou.bridging import BridgeEngine, LatencyLedger, sleep_until
from micforyou.reporting import collect_system_info, percentile_summary
from micforyou.synth import DEFAULT_SEED, pulse_positions, synthetic_blocks

from probe_real_tse_stateful import precompute_conditioning, sha256
from run_real_tse_bridge import CausalTseStream, make_real_tse_transform

SAMPLE_RATE = 48_000
PULSE_WINDOW_SAMPLES = 9_600  # +/- 100 ms around each expected pulse


class ResourceSampler(threading.Thread):
    """Samples current RSS and load average without stalling the paced loop."""

    def __init__(self, interval_seconds: float = 10.0):
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
                    "elapsed_s": round(time.monotonic() - self.started_at, 1),
                    "rss_kb": self._rss_kb(),
                    "loadavg1": os.getloadavg()[0],
                }
            )


def blackhole_roundtrip() -> dict:
    """Play synthetic pulses into BlackHole and capture them back."""
    import sounddevice as sd
    from scipy.signal import correlate, correlation_lags

    devices = [dict(item) for item in sd.query_devices()]
    matches = [
        item
        for item in devices
        if "blackhole 2ch" in item["name"].casefold()
        and item["max_input_channels"] > 0
        and item["max_output_channels"] > 0
    ]
    if len(matches) != 1:
        return {"error": f"expected exactly one BlackHole 2ch duplex device, got {matches}"}

    every = 0.5
    count = 8
    total = int((1.0 + count * every) * SAMPLE_RATE)
    signal = np.zeros(total, dtype=np.float32)
    pulse_positions_local = [int(0.5 * SAMPLE_RATE) + int(k * every * SAMPLE_RATE) for k in range(count)]
    for position in pulse_positions_local:
        signal[position] += 0.5
    stereo = np.repeat(signal[:, None], 2, axis=1)
    try:
        captured = sd.playrec(
            stereo,
            samplerate=SAMPLE_RATE,
            device=matches[0]["index"],
            channels=2,
            dtype="float32",
            blocking=True,
        )
    except Exception as failure:
        return {"error": repr(failure)}

    observed = captured[:, 0]
    captured_peak = float(np.abs(observed).max())
    if captured_peak < 0.05:
        return {
            "error": (
                f"BlackHole loopback captured silence (peak {captured_peak:.4f}); "
                "the play->driver->capture path is not delivering on this host "
                "right now. A clean 256 ms loop was measured on 2026-09-13 on "
                "the reference machine, so this is an environmental change, not "
                "a bridge property. Do not alter system audio settings to force "
                "a measurement; re-verify manually later (reboot or check Audio "
                "MIDI Setup)."
            ),
            "captured_peak": captured_peak,
            "prior_loopback_baseline_20260913": {
                "lag_ms": 256.0,
                "gain": 0.9999,
                "normalized_correlation": 0.9999,
                "snr_db": 99.68,
            },
        }
    values = correlate(observed, signal, mode="full", method="fft")
    lags = correlation_lags(len(observed), len(signal), mode="full")
    lag = int(lags[int(np.argmax(np.abs(values)))])
    offsets = []
    amplitudes = []
    for position in pulse_positions_local:
        center = position + lag
        window = observed[max(0, center - 48) : center + 48]
        if len(window):
            offsets.append(int(np.argmax(np.abs(window))) - min(48, center))
            amplitudes.append(float(np.abs(window).max()))
    return {
        "device": matches[0]["name"],
        "method": "synthetic pulse train playrec on BlackHole; xcorr lag",
        "lag_frames": lag,
        "lag_ms": lag / SAMPLE_RATE * 1000,
        "per_pulse_onset_offset_samples_std": (
            float(np.std(offsets)) if offsets else None
        ),
        "per_pulse_peak_min": float(min(amplitudes)) if amplitudes else None,
        "measures": "CoreAudio output buffer + BlackHole driver + CoreAudio capture "
        "of a played signal; NOT the bridge and NOT Doubao",
    }


def run_simulated(
    model,
    conditioning,
    *,
    frames: int,
    duration_seconds: float,
    audio_block: int,
    queue_ms: float,
    seed: int,
    tir_db: float,
    pulse_every: float,
    segment_seconds: float,
    progress_every: float,
    drain_grace_seconds: float,
    onnx_session=None,
    prefill_ms: float | None = None,
) -> dict:
    total_frames = int(round(duration_seconds * SAMPLE_RATE))
    ticks = total_frames // audio_block
    block_seconds = audio_block / SAMPLE_RATE
    maximum_frames = round(SAMPLE_RATE * queue_ms / 1000)

    pulses = pulse_positions(total_frames, SAMPLE_RATE, pulse_every)
    # Streamed block-by-block so 30-minute soaks never buffer the full input.
    blocks = synthetic_blocks(
        total_frames,
        seed=seed,
        tir_db=tir_db,
        pulse_every_seconds=pulse_every,
        block_frames=audio_block,
    )

    if onnx_session is None:
        stream = CausalTseStream(model, conditioning, frames, torch.device("cpu"))
        transform, flush_transform = make_real_tse_transform(stream)
    else:
        from benchmark_onnx_tse import OnnxTseStream, make_onnx_transform
        stream = OnnxTseStream(onnx_session, conditioning, frames,
                              len(model.sep_model.separator.separation))
        transform, flush_transform = make_onnx_transform(stream)
    engine = BridgeEngine(
        transform,
        flush_transform,
        input_bound_blocks=max(2, maximum_frames // audio_block),
        ring_maximum_frames=maximum_frames,
        output_prefill_frames=round(SAMPLE_RATE * (prefill_ms or 0) / 1000),
    )
    ledger = LatencyLedger()
    sampler = ResourceSampler()
    sampler.start()

    pacing_errors_ms: list[float] = []
    nonfinite = 0
    peak = 0.0
    output_samples = 0
    underrun_frames = 0
    startup_silence_frames = 0
    output_started = False
    position_in = 0
    fault_tick = None
    rolling = deque(maxlen=PULSE_WINDOW_SAMPLES + audio_block)
    pulse_windows: dict[int, np.ndarray] = {}
    next_pulse = 0

    def collect_output(samples: np.ndarray, written: int) -> None:
        """Stream integrity stats plus windows around expected pulse positions."""
        nonlocal nonfinite, peak, output_samples, next_pulse
        chunk = samples[:written]
        output_samples += len(chunk)
        finite = np.isfinite(chunk)
        nonfinite += int((~finite).sum())
        if len(chunk):
            peak = max(
                peak, float(np.abs(np.where(finite, chunk, 0.0)).max())
            )
        rolling.extend(chunk.tolist())
        half = PULSE_WINDOW_SAMPLES // 2
        # The ring's popped counter is the output audio position; capture the
        # +/-half window once it has fully passed the ring output.
        audio_end = engine.output_ring.total_popped
        while next_pulse < len(pulses) and audio_end >= pulses[next_pulse] + half:
            if len(rolling) >= PULSE_WINDOW_SAMPLES:
                window = np.fromiter(
                    rolling, dtype=np.float32, count=len(rolling)
                )[-PULSE_WINDOW_SAMPLES:]
                pulse_windows[next_pulse] = window
            next_pulse += 1

    started = time.perf_counter()
    progress_deadline = 0.0
    for index in range(ticks):
        if engine.fault.is_set():
            fault_tick = index
            break
        pacing_errors_ms.append(sleep_until(started + index * block_seconds) * 1000)
        if index * block_seconds >= progress_deadline:
            elapsed = index * block_seconds
            print(
                f"  t={elapsed:7.1f}s queue={engine.input_queue.qsize():3d} "
                f"ring={engine.output_ring.available():6d} "
                f"calls={len(stream.call_ms):6d}",
                flush=True,
            )
            progress_deadline = elapsed + progress_every
        tick = time.perf_counter()
        engine.submit(next(blocks))
        ledger.record_input(position_in, audio_block, tick)
        position_in += audio_block
        samples, written = engine.write_output(audio_block)
        if written:
            if not output_started:
                output_started = True
            # Map by ring audio position; output slots can run ahead of the
            # audio still buffered after startup silence or underruns.
            audio_start = engine.output_ring.total_popped - written
            ledger.record_output(audio_start, written, time.perf_counter())
            collect_output(samples, written)
        if written < audio_block:
            if output_started:
                underrun_frames += audio_block - written
            else:
                startup_silence_frames += audio_block - written

    input_ended_at = time.perf_counter()
    engine.finish(timeout=max(30, drain_grace_seconds * 3))
    drain_deadline = time.perf_counter() + drain_grace_seconds
    while engine.output_ring.available() and time.perf_counter() < drain_deadline:
        sleep_until(time.perf_counter() + block_seconds)
        samples, written = engine.write_output(audio_block)
        if written:
            audio_start = engine.output_ring.total_popped - written
            ledger.record_output(audio_start, written, time.perf_counter())
            collect_output(samples, written)
    wall_seconds = time.perf_counter() - started
    sampler.stop.set()
    sampler.join(timeout=2)

    calls = np.asarray(stream.call_ms, dtype=np.float64)
    call_times = np.asarray(stream.call_times)
    model_seconds = float(calls.sum() / 1000) if len(calls) else 0.0
    audio_seconds = position_in / SAMPLE_RATE

    segments = []
    ledger_blocks = ledger.blocks()
    for start in np.arange(0, audio_seconds, segment_seconds):
        end = min(start + segment_seconds, audio_seconds)
        mask = (call_times - started >= start) & (call_times - started < end)
        segment_calls = calls[mask] if len(calls) else np.zeros(0)
        outputs_in_segment = [
            block
            for block in ledger_blocks
            if start <= (block.write_seconds - started) < end
        ]
        segment_latencies = (
            np.asarray([block.latency_ms for block in outputs_in_segment])
            if outputs_in_segment
            else np.zeros(0)
        )
        segments.append(
            {
                "start_s": float(start),
                "end_s": float(end),
                "model_rtf": (
                    float(segment_calls.sum() / 1000 / (end - start))
                    if len(segment_calls)
                    else None
                ),
                "latency_ms_p95": (
                    float(np.percentile(segment_latencies, 95))
                    if len(segment_latencies)
                    else None
                ),
                "model_calls": int(len(segment_calls)),
            }
        )

    pulse_report = {"checked": len(pulse_windows), "expected": len(pulses)}
    if pulse_windows:
        offsets = []
        peaks = []
        half = PULSE_WINDOW_SAMPLES // 2
        for index, window in pulse_windows.items():
            # The window spans [pulse - half, pulse + half); the pulse itself
            # should peak at index ``half`` if input and output stay aligned.
            offsets.append(int(np.argmax(np.abs(window))) - half)
            peaks.append(float(np.abs(window).max()))
        pulse_report["offset_ms_mean"] = float(np.mean(offsets)) / SAMPLE_RATE * 1000
        pulse_report["offset_ms_max_abs"] = (
            float(np.max(np.abs(offsets))) / SAMPLE_RATE * 1000
        )
        pulse_report["window_peak_min"] = float(min(peaks))

    return {
        "simulated": True,
        "realtime_paced": True,
        "devices_opened": False,
        "config": {
            "frames_per_chunk": frames,
            "duration_seconds": duration_seconds,
            "audio_block": audio_block,
            "queue_ms": queue_ms,
            "seed": seed,
            "tir_db": tir_db,
            "pulse_every_seconds": pulse_every,
            "segment_seconds": segment_seconds,
        },
        "status": "FAULT" if engine.fault.is_set() else "COMPLETED",
        "fault_tick": fault_tick,
        "engine": engine.stats(),
        "wall_seconds": wall_seconds,
        "audio_seconds": audio_seconds,
        "input_samples": position_in,
        "output_samples": output_samples,
        "length_match": output_samples == position_in,
        "nonfinite_samples": int(nonfinite),
        "output_peak": float(peak),
        "model_call": percentile_summary(calls.tolist()),
        "model_compute_seconds": model_seconds,
        "model_compute_rtf": model_seconds / audio_seconds if audio_seconds else None,
        "bridge_latency": ledger.summary(),
        "underrun_ms": underrun_frames / SAMPLE_RATE * 1000,
        "startup_silence_ms": startup_silence_frames / SAMPLE_RATE * 1000,
        "pacing_error_ms": percentile_summary(pacing_errors_ms),
        "drain_seconds": wall_seconds - (input_ended_at - started),
        "segments": segments,
        "pulse_alignment": pulse_report,
        "resource_samples": sampler.samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--enrollment", type=Path, required=True)
    parser.add_argument("--enrollment-seconds", type=float, default=6.0)
    parser.add_argument("--frames-per-chunk", type=int, required=True)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--audio-block", type=int, default=480)
    parser.add_argument(
        "--torch-threads",
        type=int,
        default=None,
        help="override the thread count after wesep import (upstream sets it to 1)",
    )
    parser.add_argument("--queue-ms", type=float, default=500.0)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--tir-db", type=float, default=-6.0)
    parser.add_argument("--pulse-every", type=float, default=2.0)
    parser.add_argument("--segment-seconds", type=float, default=300.0)
    parser.add_argument("--progress-every", type=float, default=60.0)
    parser.add_argument("--drain-grace", type=float, default=2.0)
    parser.add_argument("--blackhole-roundtrip", action="store_true")
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--backend", choices=["torch", "onnx"], default="torch")
    parser.add_argument("--onnx", type=Path)
    parser.add_argument("--onnx-threads", type=int, default=1)
    parser.add_argument("--prefill-ms", type=float)
    args = parser.parse_args()

    if args.torch_threads is not None and args.torch_threads < 1:
        raise SystemExit("--torch-threads must be >= 1")

    sys.path.insert(0, str(args.repo))
    import wesep  # noqa: PLC0415

    upstream_torch_threads = torch.get_num_threads()
    if args.torch_threads is not None:
        torch.set_num_threads(args.torch_threads)

    extractor = wesep.load_model_local(str(args.model_dir))
    model = extractor.model.eval()
    enrollment, enrollment_rate = torchaudio.load(args.enrollment)
    if enrollment.shape[0] > 1:
        enrollment = enrollment.mean(dim=0, keepdim=True)
    if enrollment_rate != extractor.resample_rate:
        enrollment = torchaudio.functional.resample(
            enrollment, enrollment_rate, extractor.resample_rate
        )
    from micforyou.runtime import select_enrollment_window
    enrollment, _ = select_enrollment_window(
        enrollment, int(extractor.resample_rate), args.enrollment_seconds)
    with torch.inference_mode():
        conditioning = precompute_conditioning(model, enrollment)
    session = None
    if args.backend == "onnx":
        from micforyou.runtime import build_ort_cpu_session, validate_ort_conditioning_shapes
        if args.onnx is None:
            raise SystemExit("--onnx is required for the ONNX backend")
        session, _ = build_ort_cpu_session(args.onnx, args.onnx_threads)
        validate_ort_conditioning_shapes(session, conditioning)

    system = collect_system_info(
        {
            "torch": torch.__version__,
            "torch_threads": torch.get_num_threads(),
            "upstream_torch_threads": upstream_torch_threads,
        }
    )
    print(
        f"simulated bridge latency run: frames={args.frames_per_chunk}, "
        f"duration={args.duration:g}s",
        flush=True,
    )
    with torch.inference_mode():
        measurement = run_simulated(
            model,
            conditioning,
            frames=args.frames_per_chunk,
            duration_seconds=args.duration,
            audio_block=args.audio_block,
            queue_ms=args.queue_ms,
            seed=args.seed,
            tir_db=args.tir_db,
            pulse_every=args.pulse_every,
            segment_seconds=args.segment_seconds,
            progress_every=args.progress_every,
            drain_grace_seconds=args.drain_grace,
            onnx_session=session,
            prefill_ms=args.prefill_ms,
        )

    payload = {
        "schema": "micforyou-latency-1",
        "backend": args.backend,
        "generated_at": system["captured_at"],
        "system": system,
        "model": {
            "repo_commit": "2a540977a348fbaa92e623210505430e2cec608d",
            "weights_sha256": sha256(args.model_dir / "avg_model.pt"),
            "model_id": "tfmap_context_causal_100",
        },
        "bridge_internal": measurement,
        "not_measured": [
            "CoreAudio capture buffering between physical microphone hardware "
            "and the bridge input callback",
            "BlackHole driver to Doubao capture hand-off",
            "Doubao decode, IME and UI latency; Doubao text-appearance time is "
            "a separate manual end-to-end experience metric, never audio latency",
        ],
        "caveats": [
            "single-host monotonic clock; pacing jitter is reported separately",
            "simulated callbacks run in one Python thread, not the PortAudio "
            "callback thread; absolute latencies can differ from a live device run",
            "results describe this Mac A host only and are not transferable",
        ],
        "command": [str(part) for part in sys.argv],
    }
    if args.blackhole_roundtrip:
        print("measuring BlackHole round-trip with synthetic pulses ...", flush=True)
        payload["blackhole_roundtrip"] = blackhole_roundtrip()

    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    summary = {
        "status": measurement["status"],
        "bridge_latency": measurement["bridge_latency"],
        "underrun_ms": measurement["underrun_ms"],
        "model_compute_rtf": measurement["model_compute_rtf"],
        "length_match": measurement["length_match"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"result json: {args.result}")
    sys.stdout.flush()
    # The official venv's C++ audio/torch teardown path can abort after the
    # result is already written; exit deterministically once done.
    os._exit(0)


if __name__ == "__main__":
    main()
