"""Offline first-use setup. Commit a new registration only after all gates pass."""
from __future__ import annotations

from dataclasses import replace
import json
import math
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
import uuid

from . import performance
from .audio import list_devices, record_input, resolve_device
from .enrollment_quality import EnrollmentQualityError, check_enrollment_audio
from .product import ProductConfig, load_config, save_config
from .recommendation import BenchmarkCandidate, recommend
from .runtime_control import state_lock
from .uninstall import coordinated_start

# Single source for the registration capture length shown in the UI, used by
# the worker and the CLI enroll default. The 6 s model reference window
# (ProductConfig.enrollment_seconds) is intentionally independent of this.
REGISTRATION_SECONDS = 15.0
REGISTRATION_COUNTDOWN_SECONDS = 3.0


def bundle_root() -> Path:
    value = os.environ.get("MICFORYOU_BUNDLE_ROOT")
    if not value:
        raise ValueError("首次设置需要完整 App；开发者请使用 configure")
    root = Path(value)
    if not (root / "bundle-manifest.json").is_file():
        raise ValueError("App 内置资源不完整，请重新下载")
    return root


def job_path(config_path: Path) -> Path:
    return config_path.parent / "setup-job.json"


def save_job(config_path: Path, payload: dict) -> None:
    path = job_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def read_job(config_path: Path) -> dict:
    path = job_path(config_path)
    if not path.exists():
        return {"status": "IDLE", "stage": "尚未注册声音", "progress": 0}
    return json.loads(path.read_text())


def same_worker(job: dict) -> bool:
    pid, token = job.get("pid"), job.get("token")
    if not isinstance(pid, int) or not isinstance(token, str):
        return False
    result = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                            text=True, capture_output=True, check=False)
    return result.returncode == 0 and "setup-worker" in result.stdout and token in result.stdout


def setup_status(config_path: Path) -> dict:
    job = read_job(config_path)
    if job["status"] == "RUNNING" and not same_worker(job):
        job.update(status="FAILED", stage="设置已中断，请重试")
    return job


@coordinated_start
def start_setup(config_path: Path, input_device: str) -> dict:
    from .uninstall import uninstall_in_progress
    if uninstall_in_progress(config_path.parent):
        raise ValueError("MicForYou 正在卸载，不能开始新的声音注册")
    root = bundle_root()
    from .cli import require_inactive
    with state_lock(job_path(config_path)):
        if setup_status(config_path)["status"] == "RUNNING":
            raise ValueError("声音设置正在进行")
        require_inactive(config_path)
        devices = list_devices()
        resolve_device(devices, input_device, "input")
        resolve_device(devices, "BlackHole 2ch", "output")
        token = uuid.uuid4().hex
        command = [sys.executable, str(root / "bootstrap.py"), "setup-worker",
                   "--config", str(config_path), "--input-device", input_device,
                   "--token", token]
        config_path.parent.mkdir(parents=True, exist_ok=True)
        log_path = config_path.parent / "setup.log"
        with log_path.open("w") as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True, cwd=root)
        # The worker waits for this initial record before writing its progress.
        job = {"status": "RUNNING", "stage": "准备录音", "progress": 0,
               "pid": process.pid, "token": token, "log_path": str(log_path),
               "process_marker": str(root / "bootstrap.py"), "config_path": str(config_path)}
        save_job(config_path, job)
        return job


def cancel_setup(config_path: Path) -> dict:
    with state_lock(job_path(config_path)):
        job = read_job(config_path)
        if job.get("status") == "RUNNING" and same_worker(job):
            # Only the identified setup process group, including its exporter.
            os.killpg(job["pid"], signal.SIGTERM)
        return job


def select_candidate(payload: dict) -> dict:
    if payload.get("schema") != "micforyou/onnx-cpu-benchmark/1":
        raise ValueError("性能报告格式不正确")
    candidates = []
    by_frames = {}
    for item in payload["candidates"]:
        if item["intra_op_threads"] != "1":
            continue
        rtf, p95 = item["processing_rtf"], item["model_call_ms_p95"]
        if not isinstance(rtf, (int, float)) or not isinstance(p95, (int, float)):
            continue
        if not math.isfinite(rtf) or not math.isfinite(p95) or rtf > 0.80:
            continue
        candidates.append(BenchmarkCandidate(
            frames_per_chunk=item["frames_per_chunk"], rtf=rtf,
            model_call_ms_p95=p95, model_calls=item["model_calls"],
            input_samples=item["input_samples"], output_samples=item["output_samples"],
            nonfinite_samples=max(item["nonfinite_samples"], 0), error=item["error"]))
        by_frames[item["frames_per_chunk"]] = item
    choice = recommend(candidates)
    if choice.frames_per_chunk is None:
        raise ValueError("当前设备或负载未通过实时性能检查，请接通电源、关闭高负载应用后重试")
    return by_frames[choice.frames_per_chunk]


def validate_latency(payload: dict) -> None:
    verdict, reason, _ = performance.classify_latency(payload)
    if verdict != "pass":
        raise ValueError(f"音频链路未通过延迟或稳定性检查（{reason}）")


def pending_candidate_path(config_path: Path) -> Path:
    return config_path.parent / "pending-candidate.json"


def read_pending_candidate(config_path: Path) -> dict | None:
    try:
        payload = json.loads(pending_candidate_path(config_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if payload.get("token") else None


def start_retest(config_path: Path) -> dict:
    """Re-run the performance search for the saved voice. No recording."""
    from .uninstall import uninstall_in_progress
    if uninstall_in_progress(config_path.parent):
        raise ValueError("MicForYou 正在卸载，不能开始性能重测")
    root = bundle_root()
    candidate = read_pending_candidate(config_path)
    if candidate is None:
        raise ValueError("没有已保存的声音候选；请先完成一次注册")
    folder = config_path.parent / "registrations" / candidate["token"]
    if not (folder / "core.onnx").is_file() or not (folder / "enrollment.wav").is_file():
        raise ValueError("已保存的声音候选不完整，请重新注册")
    from .cli import require_inactive
    with state_lock(job_path(config_path)):
        if setup_status(config_path)["status"] == "RUNNING":
            raise ValueError("声音设置正在进行")
        require_inactive(config_path)
        devices = list_devices()
        resolve_device(devices, candidate["input_device"], "input")
        token = uuid.uuid4().hex
        command = [sys.executable, str(root / "bootstrap.py"), "setup-worker",
                   "--config", str(config_path), "--input-device", candidate["input_device"],
                   "--token", token, "--stage", "performance"]
        config_path.parent.mkdir(parents=True, exist_ok=True)
        log_path = config_path.parent / "setup.log"
        with log_path.open("w") as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True, cwd=root)
        job = {"status": "RUNNING", "stage": "正在重新检查本机性能", "progress": 0,
               "pid": process.pid, "token": token, "log_path": str(log_path),
               "voice": "saved", "performance": "checking"}
        save_job(config_path, job)
        return job


def approve_trial(config_path: Path) -> dict:
    """Explicitly enable a stable-but-slower candidate after user consent."""
    root = bundle_root()
    verdict = performance.read_verdict(config_path)
    if verdict is None or verdict.get("verdict") != "latency_warning":
        raise ValueError("当前没有等待确认的延迟警告候选")
    candidate = read_pending_candidate(config_path)
    if candidate is None:
        raise ValueError("找不到延迟警告对应的声音候选")
    verdict["approved_trial"] = True
    performance.write_verdict(config_path, verdict)
    folder = config_path.parent / "registrations" / candidate["token"]
    config = ProductConfig(
        input_device=candidate["input_device"], model_repo=root / "vendor",
        model_dir=root / "models" / "tfmap_context_causal_100",
        enrollment=folder / "enrollment.wav", onnx_model=folder / "core.onnx",
        runtime_python=Path(sys.executable), project_root=root, bundle_managed=True,
        frames_per_chunk=int(candidate.get("frames_per_chunk", 8)),
        prefill_ms=float(candidate.get("prefill_ms", 100)))
    save_config(config, config_path)
    return {"status": "READY", "approved_trial": True,
            "frames_per_chunk": config.frames_per_chunk}


def run_worker(config_path: Path, input_device: str, token: str,
               stage: str = "all") -> None:
    os.umask(0o077)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = read_job(config_path)
        if job.get("token") == token:
            break
        time.sleep(0.05)
    else:
        raise ValueError("声音设置任务未初始化")

    committed = False
    voice_saved = False
    folder = None

    def interrupted(signum, frame):
        if not committed:
            raise InterruptedError("已取消声音设置")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)

    def stage_label(text, progress, phase=None, recording=None, reason=None):
        job.update(stage=text, progress=progress)
        if phase is not None:
            job["phase"] = phase
        if recording is not None:
            job["recording"] = recording
        else:
            job.pop("recording", None)
        if reason is not None:
            job["reason"] = reason
        save_job(config_path, job)

    def observe_progress(last_notice):
        def on_progress(phase_name, elapsed, total):
            now = time.monotonic()
            if now - last_notice[0] < 0.5 and elapsed < total:
                return
            last_notice[0] = now
            if phase_name == "countdown":
                stage_label("准备录音，等倒计时结束再开始朗读", 0.02, phase="countdown",
                            recording={"countdown_seconds": REGISTRATION_COUNTDOWN_SECONDS,
                                       "elapsed_seconds": elapsed,
                                       "duration_seconds": REGISTRATION_SECONDS})
            else:
                stage_label("正在录音，自然朗读即可", 0.05 + 0.15 * min(elapsed / total, 1.0),
                            phase="recording",
                            recording={"duration_seconds": total, "elapsed_seconds": elapsed})
        return on_progress

    def finish_terminal(status, text, reason=None):
        job.update(status=status, phase=None, stage=text)
        job.pop("recording", None)
        if reason is not None:
            job["reason"] = reason
        else:
            job.pop("reason", None)
        save_job(config_path, job)

    try:
        root = bundle_root()
        from .cli import require_inactive
        with state_lock(config_path.parent / "setup-worker"):
            require_inactive(config_path)
            attempt = {"attempt_id": token, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                       "stage": stage, "candidates": []}

            if stage == "all":
                folder = config_path.parent / "registrations" / token
                folder.mkdir(parents=True)
                candidate = ProductConfig(
                    input_device=input_device, model_repo=root / "vendor",
                    model_dir=root / "models" / "tfmap_context_causal_100",
                    enrollment=folder / "enrollment.wav", onnx_model=folder / "core.onnx",
                    runtime_python=Path(sys.executable), project_root=root, bundle_managed=True)
                source = resolve_device(list_devices(), input_device, "input")
                resolve_device(list_devices(), candidate.output_device, "output")
                stage_label("准备录音，等倒计时结束再开始朗读", 0.02, phase="countdown",
                            recording={"countdown_seconds": REGISTRATION_COUNTDOWN_SECONDS,
                                       "elapsed_seconds": 0.0,
                                       "duration_seconds": REGISTRATION_SECONDS})
                record_input(source, candidate.enrollment, REGISTRATION_SECONDS,
                             REGISTRATION_COUNTDOWN_SECONDS,
                             on_progress=observe_progress([0.0]))
                stage_label("录音完成，可以停止朗读；正在检查录音", 0.2, phase="checking")
                import soundfile as sf
                captured, capture_rate = sf.read(candidate.enrollment, dtype="float32", always_2d=True)
                quality = check_enrollment_audio(captured[:, 0], int(capture_rate),
                                                 window_seconds=candidate.enrollment_seconds)
                (folder / "recording-check.json").write_text(
                    json.dumps({"ok": quality.ok, "reason": quality.reason,
                                **quality.metrics}, ensure_ascii=False, indent=2) + "\n")
                if not quality.ok:
                    raise EnrollmentQualityError(quality.message, quality.reason, quality.metrics)
                stage_label("正在为你的声音准备模型，请稍候", 0.3, phase="preparing_model",
                            reason=None)
                common = ["--repo", str(candidate.model_repo), "--model-dir", str(candidate.model_dir),
                          "--enrollment", str(candidate.enrollment),
                          "--enrollment-seconds", str(candidate.enrollment_seconds)]

                def run(script, arguments):
                    subprocess.run([sys.executable, str(root / "tools" / "inference" / script),
                                    *common, *arguments], cwd=root, check=True)

                run("export_real_tse_onnx.py", ["--output", str(candidate.onnx_model),
                                               "--report", str(folder / "export.json")])
                stage_label("正在校验模型", 0.45, phase="preparing_model")
                run("compare_torch_onnx.py", ["--onnx", str(candidate.onnx_model),
                    "--frames-per-chunk", "8", "--chunks", "100",
                    "--result", str(folder / "correctness.json")])
                if json.loads((folder / "correctness.json").read_text()).get("gate", {}).get("verdict") != "PASS":
                    raise ValueError("模型校验未通过；已有注册保持不变")
                # Voice is saved from here on: performance failures must not
                # discard it, and the pending pointer is replacing any older
                # pending candidate (never the active registration's files).
                voice_saved = True
                previous_pending = read_pending_candidate(config_path)
                (folder / "candidate.json").write_text(json.dumps({
                    "token": token, "input_device": input_device,
                    "saved_at": attempt["started_at"],
                    "voice_saved": True}, ensure_ascii=False, indent=2) + "\n")
                pending_candidate_path(config_path).write_text(json.dumps({
                    "token": token, "input_device": input_device,
                    "frames_per_chunk": 8, "prefill_ms": 100.0,
                    "saved_at": attempt["started_at"]}, ensure_ascii=False, indent=2) + "\n")
                if previous_pending and previous_pending.get("token") != token:
                    old_folder = config_path.parent / "registrations" / previous_pending["token"]
                    active = config_path.parent / "config.json"
                    keep = False
                    try:
                        if active.exists():
                            current = load_config(active)
                            keep = current.enrollment.parent == old_folder
                    except (OSError, ValueError):
                        keep = True  # cannot prove it is unused; keep the data
                    if not keep:
                        shutil.rmtree(old_folder, ignore_errors=True)
            else:
                pending = read_pending_candidate(config_path)
                if pending is None:
                    raise ValueError("没有已保存的声音候选；请先完成一次注册")
                folder = config_path.parent / "registrations" / pending["token"]
                if not (folder / "core.onnx").is_file():
                    raise ValueError("已保存的声音候选不完整，请重新注册")
                token = pending["token"]
                candidate = ProductConfig(
                    input_device=pending["input_device"], model_repo=root / "vendor",
                    model_dir=root / "models" / "tfmap_context_causal_100",
                    enrollment=folder / "enrollment.wav", onnx_model=folder / "core.onnx",
                    runtime_python=Path(sys.executable), project_root=root, bundle_managed=True)
                voice_saved = True
                input_device = pending["input_device"]

            job["voice"] = "saved"
            job["candidate_token"] = token
            stage_label("正在检查本机性能，请保持正常工作负载", 0.6,
                        phase="checking_performance")
            perf_common = ["--repo", str(candidate.model_repo), "--model-dir", str(candidate.model_dir),
                           "--enrollment", str(candidate.enrollment),
                           "--enrollment-seconds", str(candidate.enrollment_seconds)]
            subprocess.run([sys.executable,
                            str(root / "tools" / "inference" / "benchmark_onnx_tse.py"),
                            *perf_common,
                            "--onnx", str(candidate.onnx_model),
                            "--threads", "1", "--frames", "8", "16", "24",
                            "--audio-seconds", "10",
                            "--result", str(folder / "benchmark.json")],
                           cwd=root, check=True)
            frames_choices = performance.eligible_frames(
                json.loads((folder / "benchmark.json").read_text()))
            if not frames_choices:
                performance.write_verdict(config_path, {
                    "verdict": "blocked", "reason": "insufficient_speed",
                    "approved_trial": False,
                    "identity": performance.identity(input_device, candidate.onnx_model,
                                                     performance.app_version(root)),
                    "attempt_id": token})
                job["performance"] = "blocked"
                job["performance_reason"] = "insufficient_speed"
                finish_terminal("FAILED",
                                "声音已保存。当前设备或负载的处理速度不足，"
                                "请接通电源、关闭高负载应用后重新检查性能")
                raise ValueError("no eligible frames candidate; voice candidate kept")

            def run_latency(script, arguments):
                subprocess.run([sys.executable, str(root / "tools" / "inference" / script),
                                *perf_common, *arguments], cwd=root, check=True)

            explored = []
            best = None
            for index, frames in enumerate(frames_choices, start=1):
                for prefill in (100, 150, 200):
                    stage_label(f"正在复核连续输出与延迟（候选 {index}/{len(frames_choices)}）",
                                0.6 + 0.3 * (len(explored) + 1) / (len(frames_choices) * 3),
                                phase="checking_performance")
                    report = folder / f"latency-{frames}-{prefill}.json"
                    run_latency("measure_bridge_latency.py",
                                ["--backend", "onnx", "--onnx", str(candidate.onnx_model),
                                 "--onnx-threads", "1", "--frames-per-chunk", str(frames),
                                 "--duration", "30", "--prefill-ms", str(prefill),
                                 "--result", str(report)])
                    verdict, reason, metrics = performance.classify_latency(
                        json.loads(report.read_text()))
                    item = {"frames_per_chunk": frames, "prefill_ms": float(prefill),
                            "verdict": verdict, "reason": reason, "metrics": metrics}
                    explored.append(item)
                    attempt["candidates"].append(item)
                    if verdict == "pass":
                        best = item
                        break
                if best is not None:
                    break
            if best is None:
                best = performance.choose_best(explored)

            attempt["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            performance.record_attempt(config_path, attempt)

            if best is None:
                performance.write_verdict(config_path, {
                    "verdict": "blocked", "reason": (explored[-1]["reason"] if explored
                                                     else "no_stable_candidate"),
                    "approved_trial": False,
                    "identity": performance.identity(input_device, candidate.onnx_model,
                                                     performance.app_version(root)),
                    "attempt_id": token})
                job["performance"] = "blocked"
                job["performance_reason"] = explored[-1]["reason"] if explored else "no_stable_candidate"
                finish_terminal("FAILED",
                                "声音已保存。当前声音处理不稳定或速度不足，"
                                "请关闭高负载应用后重新检查性能")
                raise ValueError("performance checks failed; voice candidate kept")

            candidate = replace(candidate, frames_per_chunk=best["frames_per_chunk"],
                                prefill_ms=best["prefill_ms"])
            pending = read_pending_candidate(config_path) or {}
            pending.update({"token": token, "input_device": input_device,
                            "frames_per_chunk": best["frames_per_chunk"],
                            "prefill_ms": best["prefill_ms"]})
            pending_candidate_path(config_path).write_text(
                json.dumps(pending, ensure_ascii=False, indent=2) + "\n")
            performance.write_verdict(config_path, {
                "verdict": best["verdict"], "reason": best["reason"],
                "approved_trial": False,
                "frames_per_chunk": best["frames_per_chunk"],
                "prefill_ms": best["prefill_ms"],
                "identity": performance.identity(input_device, candidate.onnx_model,
                                                 performance.app_version(root)),
                "attempt_id": token,
                "latency_ms_p95": best["metrics"].get("latency_ms_p95")})

            if best["verdict"] == "pass":
                # Atomic switch: only a passing (or explicitly approved)
                # candidate ever replaces the active registration.
                previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
                try:
                    save_config(candidate, config_path)
                    committed = True
                    job["performance"] = "pass"
                    finish_terminal("READY",
                                    "设置完成。在豆包输入法中选择 BlackHole 2ch，然后开始过滤")
                finally:
                    signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            else:
                job["performance"] = "latency_warning"
                finish_terminal("WAITING",
                                "声音已保存。语音输入可能需要等一会儿才出字，"
                                "你可以先试用，也可以重新检查")
    except (InterruptedError, KeyboardInterrupt):
        if job.get("performance") not in {"pass", "latency_warning"}:
            job["performance"] = job.get("performance") or "unchecked"
        finish_terminal("CANCELLED", "已取消；" +
                        ("已保存的声音不受影响" if voice_saved else "已有注册保持不变"))
    except EnrollmentQualityError as error:
        finish_terminal("FAILED", error.message, reason=error.reason)
        raise
    except Exception as error:
        job["performance"] = job.get("performance") or "unchecked"
        message = str(error)
        if voice_saved and "性能" not in message:
            message = f"声音已保存；{message}"
        finish_terminal("FAILED", message)
        raise
    finally:
        # A voice that reached the saved point is never deleted on failure;
        # only candidates that failed before saving (recording/model issues)
        # are cleaned up.
        if folder is not None and not voice_saved and not committed:
            shutil.rmtree(folder, ignore_errors=True)
