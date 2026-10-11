"""Experimental physical-mic -> causal REAL-TSE -> BlackHole bridge.

Audio callbacks only move bounded PCM blocks. Resampling and model inference run
on a worker thread. Queue overflow or worker exceptions first trigger bounded
same-route recovery. The default terminal policy is fault-silence; an explicit
continuity-first policy may instead degrade to clearly reported raw passthrough.

The queue/ring/fault core lives in ``micforyou.bridging.BridgeEngine`` so unit
tests can replay overflow and inference failures without audio hardware.
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soxr
import torch
import torchaudio

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from micforyou.audio import (
    InputRouteMonitor,
    ensure_safe_route,
    list_devices,
    list_devices_fresh,
    resolve_device,
)
from micforyou.bridging import (
    BridgeEngine,
    CallbackLivenessMonitor,
    LatencyLedger,
    RecoveryCircuitBreaker,
    mono_to_stereo_passthrough,
)
from micforyou.modes import SwitchableBridge
from micforyou.runtime_control import ControlServer
from micforyou.recommendation import estimate_core_latency_ms
from micforyou.runtime import (
    build_ort_cpu_session,
    validate_ort_conditioning_shapes,
)

from probe_real_tse_stateful import (
    StreamingOLA,
    StreamingSTFT,
    condition_features,
    mask_frames,
    precompute_conditioning,
    separator_chunk,
    sha256,
)


class CausalTseStream:
    def __init__(self, model, conditioning, frames_per_chunk: int, device: torch.device):
        self.model = model
        self.conditioning = conditioning
        self.frames_per_chunk = frames_per_chunk
        self.stft = StreamingSTFT(model.sep_model.win, model.sep_model.stride, device)
        self.ola = StreamingOLA(model.sep_model.win, model.sep_model.stride, device)
        self.pending: list[torch.Tensor] = []
        self.states = [None] * len(model.sep_model.separator.separation)
        self.call_ms: list[float] = []
        self.call_times: list[float] = []

    def _process(self, force: bool = False) -> list[torch.Tensor]:
        outputs = []
        while len(self.pending) >= self.frames_per_chunk or (force and self.pending):
            count = min(self.frames_per_chunk, len(self.pending))
            spec = torch.cat(self.pending[:count], dim=-1)
            self.pending = self.pending[count:]
            started = time.perf_counter()
            features, mixture = condition_features(self.model, spec, self.conditioning)
            separated, self.states = separator_chunk(
                self.model.sep_model.separator, features, self.states
            )
            estimated = mask_frames(self.model, separated, mixture)
            outputs.extend(self.ola.push(estimated))
            finished = time.perf_counter()
            self.call_ms.append((finished - started) * 1000)
            self.call_times.append(finished)
        return outputs

    def feed(self, samples: np.ndarray) -> np.ndarray:
        tensor = torch.from_numpy(np.asarray(samples, dtype=np.float32)).to(
            next(self.model.parameters()).device
        )
        self.pending.extend(self.stft.push(tensor))
        outputs = self._process()
        if not outputs:
            return np.empty(0, dtype=np.float32)
        return torch.cat(outputs, dim=-1).reshape(-1).cpu().numpy()

    def flush(self) -> np.ndarray:
        self.pending.extend(self.stft.flush())
        outputs = self._process(force=True)
        outputs.extend(self.ola.flush())
        if not outputs:
            return np.empty(0, dtype=np.float32)
        return torch.cat(outputs, dim=-1).reshape(-1).cpu().numpy()


def make_real_tse_transform(tse: CausalTseStream, sample_rate: int = 48_000):
    """Build the live 48 kHz -> 16 kHz -> TSE -> 16 kHz -> 48 kHz chain.

    Returns ``(transform, flush_transform)`` callables for ``BridgeEngine``.
    Inference mode is entered inside the callables because it is thread-local:
    the engine worker thread does not inherit the caller's context.
    """

    down = soxr.ResampleStream(sample_rate, 16_000, 1, dtype="float32", quality="HQ")
    up = soxr.ResampleStream(16_000, sample_rate, 1, dtype="float32", quality="HQ")

    def transform(block: np.ndarray) -> np.ndarray:
        low = down.resample_chunk(block, last=False)
        if not len(low):
            return np.empty(0, dtype=np.float32)
        with torch.inference_mode():
            enhanced = tse.feed(low)
        if not len(enhanced):
            return np.empty(0, dtype=np.float32)
        return up.resample_chunk(enhanced, last=False)

    def flush_transform() -> np.ndarray:
        pieces: list[np.ndarray] = []
        low_tail = down.resample_chunk(np.empty(0, dtype=np.float32), last=True)
        with torch.inference_mode():
            if len(low_tail):
                middle = tse.feed(low_tail)
                if len(middle):
                    pieces.append(up.resample_chunk(middle, last=False))
            tail = tse.flush()
        if len(tail):
            pieces.append(up.resample_chunk(tail, last=False))
        pieces.append(up.resample_chunk(np.empty(0, dtype=np.float32), last=True))
        return np.concatenate(pieces) if len(pieces) else np.empty(0, dtype=np.float32)

    return transform, flush_transform


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--enrollment", type=Path, required=True)
    parser.add_argument("--enrollment-seconds", type=float, default=6.0)
    parser.add_argument("--input-device", required=True)
    parser.add_argument("--output-device", default="BlackHole 2ch")
    parser.add_argument("--backend", choices=("torch", "onnx"), default="torch")
    parser.add_argument("--onnx", type=Path, default=None)
    parser.add_argument(
        "--onnx-threads",
        type=int,
        default=1,
        help="ONNX Runtime intra-op threads; zero leaves ORT defaults unset",
    )
    parser.add_argument("--duration", type=float, default=0)
    parser.add_argument(
        "--frames-per-chunk",
        type=int,
        required=True,
        help="must be selected from a local benchmark; do not assume a safe default",
    )
    parser.add_argument("--audio-block", type=int, default=480)
    parser.add_argument(
        "--torch-threads",
        type=int,
        default=None,
        help="override the thread count after wesep import (upstream sets it to 1)",
    )
    parser.add_argument(
        "--torch-interop-threads",
        type=int,
        default=None,
        help="limit PyTorch operator-level scheduling threads before model load",
    )
    parser.add_argument("--queue-ms", type=float, default=500)
    parser.add_argument(
        "--prefill-ms",
        type=float,
        default=0,
        help="explicit startup output prefill; measured as bridge latency",
    )
    parser.add_argument(
        "--callback-timeout-ms",
        type=float,
        default=1000,
        help="enter fault-silence when CoreAudio callbacks stop for this long",
    )
    parser.add_argument(
        "--auto-recoveries",
        "--callback-restarts",
        dest="auto_recoveries",
        type=int,
        default=2,
        help="recoverable runtime faults allowed within the rolling recovery window",
    )
    parser.add_argument(
        "--recovery-window-seconds",
        type=float,
        default=300,
        help="rolling window used by the automatic-recovery circuit breaker",
    )
    parser.add_argument(
        "--restart-delay-ms",
        type=float,
        default=500,
        help="quiet interval before reopening the same explicit device pair",
    )
    parser.add_argument(
        "--fault-policy",
        choices=("silence", "passthrough"),
        default="silence",
        help="after recovery is exhausted, latch silence or explicitly pass raw mic",
    )
    parser.add_argument(
        "--route-change-policy",
        choices=("continue_tse", "silence_on_route_change"),
        default="continue_tse",
        help=(
            "when the selected physical input disappears, either wait silently "
            "and reopen that explicit TSE route, or enter terminal fault-silence"
        ),
    )
    parser.add_argument(
        "--route-reconnect-timeout-seconds",
        type=float,
        default=120.0,
        help="maximum silent wait for the selected input to reappear",
    )
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument(
        "--health-file",
        type=Path,
        help="optional atomic lifecycle status for the product controller",
    )
    parser.add_argument("--control-socket", type=Path)
    parser.add_argument("--control-token")
    args = parser.parse_args()
    if bool(args.control_socket) != bool(args.control_token):
        raise SystemExit("control socket and token must be provided together")

    def write_health(status: str, detail: str, **values) -> None:
        if args.health_file is None:
            return
        payload = {
            "schema": "micforyou/bridge-health/1",
            "status": status,
            "detail": detail,
            "updated_at_epoch": time.time(),
            **values,
        }
        args.health_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.health_file.with_suffix(args.health_file.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(args.health_file)

    write_health("STARTING", "validating devices and loading the TSE runtime")

    if args.torch_threads is not None and args.torch_threads < 1:
        raise SystemExit("--torch-threads must be >= 1")
    if args.onnx_threads < 0:
        raise SystemExit("--onnx-threads must be >= 0")
    if args.backend == "onnx" and args.onnx is None:
        raise SystemExit("--onnx is required when --backend onnx")
    if args.torch_interop_threads is not None and args.torch_interop_threads < 1:
        raise SystemExit("--torch-interop-threads must be >= 1")
    if args.callback_timeout_ms <= 0:
        raise SystemExit("--callback-timeout-ms must be positive")
    if args.auto_recoveries < 0:
        raise SystemExit("--auto-recoveries must be >= 0")
    if args.recovery_window_seconds <= 0:
        raise SystemExit("--recovery-window-seconds must be positive")
    if args.restart_delay_ms < 0:
        raise SystemExit("--restart-delay-ms must be >= 0")
    if args.route_reconnect_timeout_seconds <= 0:
        raise SystemExit("--route-reconnect-timeout-seconds must be positive")
    if args.prefill_ms < 0 or args.prefill_ms > args.queue_ms:
        raise SystemExit("--prefill-ms must be between zero and --queue-ms")

    devices = list_devices()
    input_device = resolve_device(devices, args.input_device, "input")
    output_device = resolve_device(devices, args.output_device, "output")
    ensure_safe_route(input_device, output_device)

    sys.path.insert(0, str(args.repo))
    import wesep  # noqa: PLC0415

    upstream_torch_threads = torch.get_num_threads()
    upstream_torch_interop_threads = torch.get_num_interop_threads()
    if args.torch_threads is not None:
        torch.set_num_threads(args.torch_threads)
    if args.torch_interop_threads is not None:
        torch.set_num_interop_threads(args.torch_interop_threads)

    extractor = wesep.load_model_local(str(args.model_dir))
    model = extractor.model.eval()
    enrollment, enrollment_rate = torchaudio.load(args.enrollment)
    if enrollment.shape[0] > 1:
        enrollment = enrollment.mean(dim=0, keepdim=True)
    from micforyou.runtime import prepare_enrollment_reference

    reference = prepare_enrollment_reference(
        enrollment, enrollment_rate, args.enrollment_seconds, int(extractor.resample_rate))
    enrollment, enrollment_selection = reference.selected, reference.selection
    with torch.inference_mode():
        conditioning = precompute_conditioning(model, enrollment)
    runtime_metadata: dict = {"backend": args.backend}
    ort_session = None
    onnx_layer_count = None
    if args.backend == "onnx":
        ort_session, ort_metadata = build_ort_cpu_session(
            args.onnx, args.onnx_threads
        )
        try:
            validate_ort_conditioning_shapes(ort_session, conditioning)
        except ValueError as error:
            raise SystemExit(str(error)) from error
        runtime_metadata.update(ort_metadata)
        onnx_layer_count = len(model.sep_model.separator.separation)
        from benchmark_onnx_tse import (  # noqa: PLC0415
            OnnxTseStream,
            make_onnx_transform,
        )
    sample_rate = 48_000
    maximum_frames = round(sample_rate * args.queue_ms / 1000)
    prefill_frames = round(sample_rate * args.prefill_ms / 1000)
    started = time.monotonic()
    usage_started = resource.getrusage(resource.RUSAGE_SELF)
    cpu_seconds_started = usage_started.ru_utime + usage_started.ru_stime
    deadline = started + args.duration if args.duration > 0 else None
    attempts: list[dict] = []
    all_call_ms: list[float] = []
    interrupted = False
    fallback_reason: str | None = None
    recovery_breaker = RecoveryCircuitBreaker(
        args.auto_recoveries, args.recovery_window_seconds
    )
    route_events: list[dict] = []
    route_reconnections = 0
    route_reconnect_wait_seconds = 0.0

    desired_mode = "tse"
    last_revision = 0
    route_ready = threading.Event()
    engine = None

    def handle_mode(mode: str, timeout: float) -> dict:
        nonlocal desired_mode, last_revision
        current = engine
        if current is None or not route_ready.is_set():
            raise ValueError("audio route is not ready; wait for RUNNING/PAUSED")
        result = current.switch(mode, timeout)
        if not route_ready.is_set() or current.fault.is_set():
            raise ValueError("audio route failed during mode switch")
        desired_mode = result["processing_mode"]
        last_revision = result["mode_revision"]
        return result

    server = ControlServer(args.control_socket, args.control_token, handle_mode) if args.control_socket else None

    while True:
        attempt_started = time.monotonic()
        # Device indexes can change when a headset is unplugged. Resolve the
        # configured names before every open; never reuse an index that may
        # now designate the built-in microphone.
        route_open_error: str | None = None
        active_input_device = input_device
        active_output_device = output_device
        try:
            active_devices = list_devices()
            active_input_device = resolve_device(
                active_devices, args.input_device, "input"
            )
            active_output_device = resolve_device(
                active_devices, args.output_device, "output"
            )
            ensure_safe_route(active_input_device, active_output_device)
        except ValueError as error:
            route_open_error = f"selected route unavailable before open: {error}"
        # A recovery starts from fresh resamplers, STFT/OLA buffers, recurrent
        # state, queues and timestamps. No pre-stall audio can reach BlackHole.
        tse_generations = []
        metrics_lock = threading.Lock()
        attempt_calls = []

        def harvest_metrics(final=False):
            with metrics_lock:
                retained = []
                for tse, generation in tse_generations:
                    if final or generation.worker_done.is_set():
                        attempt_calls.extend(tse.call_ms)
                    else:
                        retained.append((tse, generation))
                tse_generations[:] = retained
                return len(attempt_calls) + sum(len(item.call_ms) for item, _ in retained)

        def new_engine():
            if args.backend == "onnx":
                tse = OnnxTseStream(
                    ort_session,
                    conditioning,
                    args.frames_per_chunk,
                    onnx_layer_count,
                )
                transform, flush_transform = make_onnx_transform(tse)
            else:
                tse = CausalTseStream(
                    model, conditioning, args.frames_per_chunk, torch.device("cpu")
                )
                transform, flush_transform = make_real_tse_transform(tse)
            generation = BridgeEngine(
                transform,
                flush_transform,
                input_bound_blocks=max(2, maximum_frames // args.audio_block),
                ring_maximum_frames=maximum_frames,
                output_prefill_frames=prefill_frames,
            )
            with metrics_lock:
                tse_generations.append((tse, generation))
            return generation
        engine = SwitchableBridge(new_engine, desired_mode, last_revision + len(attempts))
        observed_revision = engine.revision
        ledger = LatencyLedger()
        capture_enabled = threading.Event()
        capture_enabled.set()
        statuses: list[str] = []
        callback_count = 0
        input_underflow_count = 0
        input_interrupted = threading.Event()
        startup_silence_frames = 0
        underrun_frames = 0
        output_started = False
        position_in = 0
        liveness = CallbackLivenessMonitor(args.callback_timeout_ms / 1000)
        route_monitor = InputRouteMonitor(active_input_device)
        next_fresh_route_check = time.monotonic()
        pressure_samples: list[dict] = []
        next_pressure_sample = time.monotonic()
        stalled = False
        route_lost = False
        stream_latency = None

        def callback(indata, outdata, frames, time_info, status) -> None:
            nonlocal callback_count, input_underflow_count
            nonlocal startup_silence_frames, underrun_frames
            nonlocal output_started, position_in, ledger, observed_revision
            liveness.observe()
            callback_count += 1
            if status:
                statuses.append(str(status))
                if getattr(status, "input_underflow", False):
                    input_underflow_count += 1
                    input_interrupted.set()
                    capture_enabled.clear()
                    engine.latch_fault("input device interrupted; output is silent")
            outdata.fill(0)
            arrival = time.perf_counter()
            block = indata[:frames, 0].copy() if capture_enabled.is_set() else None
            mono, written = engine.process(block, frames)
            if observed_revision != engine.revision:
                ledger = LatencyLedger()
                position_in = 0
                output_started = False
                observed_revision = engine.revision
            if block is not None:
                ledger.record_input(position_in, frames, arrival)
                position_in += frames
            if written:
                ring = engine.output_ring
                audio_start = position_in - frames if engine.mode == "passthrough" else ring.total_popped - written
                ledger.record_output(audio_start, written, time.perf_counter())
                output_started = True
                outdata[:, 0] = mono
                outdata[:, 1] = mono
            if written < frames:
                if output_started:
                    underrun_frames += frames - written
                else:
                    startup_silence_frames += frames - written

        try:
            if route_open_error is not None:
                raise RuntimeError(route_open_error)
            with sd.Stream(
                device=(active_input_device.index, active_output_device.index),
                samplerate=sample_rate,
                blocksize=args.audio_block,
                channels=(1, 2),
                dtype="float32",
                callback=callback,
            ) as stream:
                stream_latency = stream.latency
                route_ready.set()
                def publish_mode():
                    snapshot = engine.snapshot()
                    write_health(
                        "FAULT" if snapshot["processing_mode"] == "none" else "PAUSED" if snapshot["processing_mode"] == "passthrough" else "RUNNING",
                        "raw microphone audio continues" if snapshot["processing_mode"] == "passthrough" else "TSE filtering is active",
                        input_device=active_input_device.name,
                        output_device=active_output_device.name,
                        final_mode=snapshot["processing_mode"], degraded=snapshot["processing_mode"] == "none", **snapshot,
                    )
                publish_mode()
                while not engine.fault.is_set():
                    if deadline is not None and time.monotonic() >= deadline:
                        break
                    sd.sleep(100)
                    if not engine.fault.is_set():
                        publish_mode()
                    now = time.monotonic()
                    model_calls = harvest_metrics()
                    if now >= next_pressure_sample:
                        pressure_samples.append(
                            {
                                "elapsed_seconds": now - started,
                                "input_queue_blocks": engine.engine.input_queue.qsize() if engine.engine else 0,
                                "output_ring_frames": engine.output_ring.available() if engine.output_ring else 0,
                                "model_calls": model_calls,
                                **engine.snapshot(),
                            }
                        )
                        next_pressure_sample = now + 5
                    callback_age = liveness.check()
                    if callback_age is not None:
                        stalled = True
                        engine.latch_fault(
                            f"audio callbacks stalled for {callback_age:.3f} seconds"
                        )
                    if input_interrupted.is_set() and not route_lost:
                        route_lost = True
                        capture_enabled.clear()
                        route_events.append(
                            {
                                "elapsed_seconds": now - started,
                                "state": "input_interrupted",
                                "expected_input_device": args.input_device,
                                "device": None,
                                "detail": (
                                    "PortAudio reported input underflow; "
                                    "silencing before an implicit route fallback"
                                ),
                            }
                        )
                        engine.latch_fault(
                            "input device interrupted; silencing until "
                            "the explicit route can be reopened"
                        )
                        write_health(
                            "RECOVERING",
                            "input route interrupted; output is silent",
                            final_mode="tse",
                            degraded=True,
                        )
                    if now >= next_fresh_route_check and not route_lost:
                        next_fresh_route_check = now + 1.0
                        try:
                            route_devices = list_devices_fresh()
                        except RuntimeError as error:
                            route_lost = True
                            capture_enabled.clear()
                            route_events.append(
                                {
                                    "elapsed_seconds": now - started,
                                    "state": "inventory_error",
                                    "expected_input_device": args.input_device,
                                    "device": None,
                                    "detail": str(error),
                                }
                            )
                            engine.latch_fault(
                                "cannot verify selected input route; silencing until "
                                "a fresh inventory confirms it can be reopened"
                            )
                        else:
                            route_event = route_monitor.observe(route_devices, now=now)
                            if route_event is not None:
                                route_event["elapsed_seconds"] = now - started
                                route_events.append(route_event)
                                print(
                                    "INPUT ROUTE "
                                    f"{route_event['state']}: "
                                    f"{route_event['expected_input_device']}",
                                    flush=True,
                                )
                                if route_event["state"] == "unavailable":
                                    route_lost = True
                                    capture_enabled.clear()
                                    engine.latch_fault(
                                        "selected input route disappeared; silencing until "
                                        "the explicit route can be reopened"
                                    )
                                    write_health(
                                        "RECOVERING",
                                        "selected input disappeared; output is silent",
                                        final_mode="tse",
                                        degraded=True,
                                    )
                route_ready.clear()
                capture_enabled.clear()
                engine.finish(timeout=10)
                drain_deadline = time.monotonic() + 2
                while engine.output_ring is not None and engine.output_ring.available() and time.monotonic() < drain_deadline:
                    sd.sleep(10)
        except KeyboardInterrupt:
            interrupted = True
            capture_enabled.clear()
            engine.finish(timeout=10)
        except Exception as error:
            engine.latch_fault(f"audio stream failed: {error!r}")
            engine.finish(timeout=10)
        finally:
            route_ready.clear()
            capture_enabled.clear()

        harvest_metrics(final=True)
        all_call_ms.extend(attempt_calls)
        attempt = {
            "attempt": len(attempts) + 1,
            "status": "FAULT" if engine.fault.is_set() else "STOPPED",
            "callback_stall": stalled,
            "portaudio_stream_latency_seconds": stream_latency,
            "callback_count": callback_count,
            "model_call_count": len(attempt_calls),
            "engine": engine.stats(),
            "bridge_latency": ledger.summary(),
            "startup_silence_ms": startup_silence_frames / sample_rate * 1000,
            "underrun_ms": underrun_frames / sample_rate * 1000,
            "stream_statuses": statuses,
            "input_underflow_count": input_underflow_count,
            "callback_liveness": liveness.stats(),
            "input_route": route_monitor.stats(),
            "active_input_device": active_input_device.to_dict(),
            "active_output_device": active_output_device.to_dict(),
            "route_lost": route_lost,
            "route_reconnect_planned": False,
            "queue_pressure_5s": pressure_samples,
            "errors": list(engine.errors),
            "started_elapsed_seconds": attempt_started - started,
            "ended_elapsed_seconds": time.monotonic() - started,
            "recovery_planned": False,
        }
        attempts.append(attempt)
        faulted = engine.fault.is_set()
        engine.close()
        if faulted:
            write_health("RECOVERING", "audio route failed; output is silent", processing_mode="none", mode_revision=last_revision, degraded=True)

        duration_finished = deadline is not None and time.monotonic() >= deadline
        if (
            route_lost
            and args.route_change_policy == "silence_on_route_change"
            and not interrupted
        ):
            # A route-loss policy must not fall through to the generic fault
            # recovery path, which could reopen a stale device index.
            break
        if route_lost and args.route_change_policy == "continue_tse" and not interrupted:
            reconnect_started = time.monotonic()
            reconnect_deadline = reconnect_started + args.route_reconnect_timeout_seconds
            if deadline is not None:
                reconnect_deadline = min(reconnect_deadline, deadline)
            next_inventory_refresh = reconnect_started
            while time.monotonic() < reconnect_deadline:
                try:
                    now = time.monotonic()
                    # PortAudio's in-process device list was stale after a
                    # hot unplug on this Mac. A short-lived process receives
                    # a fresh CoreAudio inventory; do not reopen until it
                    # confirms the same explicitly selected device exists.
                    if now >= next_inventory_refresh:
                        sd._terminate()
                        sd._initialize()
                        next_inventory_refresh = now + 1.0
                    reconnect_devices = list_devices_fresh()
                    restored_input = resolve_device(
                        reconnect_devices, args.input_device, "input"
                    )
                    restored_output = resolve_device(
                        reconnect_devices, args.output_device, "output"
                    )
                    ensure_safe_route(restored_input, restored_output)
                except (ValueError, RuntimeError, sd.PortAudioError):
                    sd.sleep(1000)
                    continue
                waited = time.monotonic() - reconnect_started
                route_reconnect_wait_seconds += waited
                route_reconnections += 1
                route_events.append(
                    {
                        "elapsed_seconds": time.monotonic() - started,
                        "state": "reconnected",
                        "expected_input_device": args.input_device,
                        "device": restored_input.to_dict(),
                        "detail": f"reopened explicit TSE route after {waited:.3f}s",
                    }
                )
                attempt["route_reconnect_planned"] = True
                print(
                    f"INPUT ROUTE reconnected: {args.input_device}; reopening TSE.",
                    flush=True,
                )
                break
            if attempt["route_reconnect_planned"]:
                continue
            route_reconnect_wait_seconds += time.monotonic() - reconnect_started
            # Do not consume the ordinary inference-fault recovery budget or
            # open a stale input index while the selected device is absent.
            break
        if interrupted or duration_finished or not faulted:
            break
        if not recovery_breaker.allow():
            if args.fault_policy == "passthrough":
                fallback_reason = "; ".join(engine.errors) or "runtime fault"
            break
        attempt["recovery_planned"] = True
        sd.sleep(round(args.restart_delay_ms))

    if server is not None:
        server.close()
    passthrough_report: dict | None = None
    if fallback_reason is not None and not interrupted:
        passthrough_started = time.monotonic()
        print(
            "WARNING: TSE filtering is unavailable; continuity-first mode is "
            "passing UNFILTERED microphone audio to BlackHole.",
            flush=True,
        )
        write_health(
            "DEGRADED",
            "UNFILTERED microphone passthrough is active",
            final_mode="passthrough",
            degraded=True,
        )
        next_passthrough_warning = passthrough_started + 30
        passthrough_liveness = CallbackLivenessMonitor(
            args.callback_timeout_ms / 1000
        )
        passthrough_statuses: list[str] = []
        passthrough_callbacks = 0
        passthrough_fault: str | None = None

        def passthrough_callback(indata, outdata, frames, time_info, status) -> None:
            nonlocal passthrough_callbacks
            passthrough_liveness.observe()
            passthrough_callbacks += 1
            if status:
                passthrough_statuses.append(str(status))
            outdata[:] = mono_to_stereo_passthrough(indata, frames)

        try:
            with sd.Stream(
                device=(input_device.index, output_device.index),
                samplerate=sample_rate,
                blocksize=args.audio_block,
                channels=(1, 2),
                dtype="float32",
                callback=passthrough_callback,
            ):
                while True:
                    if deadline is not None and time.monotonic() >= deadline:
                        break
                    sd.sleep(100)
                    if time.monotonic() >= next_passthrough_warning:
                        print(
                            "WARNING: still passing UNFILTERED microphone audio "
                            "to BlackHole.",
                            flush=True,
                        )
                        next_passthrough_warning = time.monotonic() + 30
                    callback_age = passthrough_liveness.check()
                    if callback_age is not None:
                        passthrough_fault = (
                            "passthrough callbacks stalled for "
                            f"{callback_age:.3f} seconds"
                        )
                        break
        except KeyboardInterrupt:
            interrupted = True
        except Exception as error:
            passthrough_fault = f"passthrough stream failed: {error!r}"

        passthrough_report = {
            "activated": True,
            "reason": fallback_reason,
            "status": "FAULT" if passthrough_fault else "STOPPED",
            "elapsed_seconds": time.monotonic() - passthrough_started,
            "callback_count": passthrough_callbacks,
            "stream_statuses": passthrough_statuses,
            "callback_liveness": passthrough_liveness.stats(),
            "error": passthrough_fault,
            "audio_written": False,
        }

    elapsed = time.monotonic() - started
    usage_ended = resource.getrusage(resource.RUSAGE_SELF)
    cpu_seconds = (
        usage_ended.ru_utime + usage_ended.ru_stime - cpu_seconds_started
    )
    values = np.asarray(all_call_ms, dtype=np.float64)
    final_attempt = attempts[-1]
    recovered_faults = sum(attempt["recovery_planned"] for attempt in attempts)
    recovered_stalls = sum(
        attempt["callback_stall"] and attempt["recovery_planned"]
        for attempt in attempts
    )
    final_status = (
        passthrough_report["status"]
        if passthrough_report is not None
        else final_attempt["status"]
    )
    final_mode = "passthrough" if passthrough_report is not None else desired_mode
    result = {
        "status": final_status,
        "final_mode": final_mode,
        "fault_policy": args.fault_policy,
        "route_change_policy": args.route_change_policy,
        "runtime": runtime_metadata,
        "enrollment_selection": enrollment_selection,
        "input_device": input_device.name,
        "output_device": output_device.name,
        "sample_rate": sample_rate,
        "audio_block": args.audio_block,
        "queue_ms": args.queue_ms,
        "prefill_ms": args.prefill_ms,
        "frames_per_model_chunk": args.frames_per_chunk,
        "torch_threads": torch.get_num_threads(),
        "torch_interop_threads": torch.get_num_interop_threads(),
        "upstream_torch_threads": upstream_torch_threads,
        "upstream_torch_interop_threads": upstream_torch_interop_threads,
        "model_chunk_ms": args.frames_per_chunk * 8,
        "algorithmic_latency_ms": 24,
        "estimated_core_latency_ms": estimate_core_latency_ms(
            args.frames_per_chunk,
            float(np.percentile(values, 95)) if len(values) else 0.0,
        ),
        "portaudio_stream_latency_seconds": final_attempt[
            "portaudio_stream_latency_seconds"
        ],
        "model_sha256": sha256(args.model_dir / "avg_model.pt"),
        "onnx_sha256": sha256(args.onnx) if args.onnx is not None else None,
        "elapsed_seconds": elapsed,
        "process_resources": {
            "cpu_seconds": cpu_seconds,
            "mean_cpu_percent_one_core": (
                cpu_seconds / elapsed * 100 if elapsed > 0 else None
            ),
            "peak_rss_bytes": usage_ended.ru_maxrss,
        },
        "callback_count": sum(attempt["callback_count"] for attempt in attempts)
        + (passthrough_report["callback_count"] if passthrough_report else 0),
        "model_call_count": len(all_call_ms),
        "model_call_ms_p50": float(np.percentile(values, 50)) if len(values) else None,
        "model_call_ms_p95": float(np.percentile(values, 95)) if len(values) else None,
        "model_call_ms_max": float(values.max()) if len(values) else None,
        "engine": final_attempt["engine"],
        "bridge_latency": final_attempt["bridge_latency"],
        "startup_silence_ms": sum(
            attempt["startup_silence_ms"] for attempt in attempts
        ),
        "underrun_ms": sum(attempt["underrun_ms"] for attempt in attempts),
        "stream_statuses": [
            status for attempt in attempts for status in attempt["stream_statuses"]
        ],
        "callback_liveness": final_attempt["callback_liveness"],
        "input_route": {
            "expected_input_device": args.input_device,
            "events": route_events,
            "reconnections": route_reconnections,
            "reconnect_wait_seconds": route_reconnect_wait_seconds,
        },
        "automatic_recovery": recovery_breaker.stats(),
        "faults_recovered": recovered_faults,
        "callback_stalls_recovered": recovered_stalls,
        "degraded": recovered_faults > 0 or passthrough_report is not None,
        "passthrough": passthrough_report,
        "attempts": attempts,
        "errors": [error for attempt in attempts for error in attempt["errors"]],
    }
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    write_health(
        "FAULT" if final_status == "FAULT" else "STOPPED",
        "bridge finished",
        final_mode=final_mode,
        degraded=result["degraded"],
        result=str(args.result),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if final_status == "FAULT":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
