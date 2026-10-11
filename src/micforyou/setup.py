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

from .audio import list_devices, record_input, resolve_device
from .product import ProductConfig, save_config
from .runtime_control import state_lock
from .recommendation import BenchmarkCandidate, recommend


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


def start_setup(config_path: Path, input_device: str) -> dict:
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
               "pid": process.pid, "token": token, "log_path": str(log_path)}
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
    value = payload["bridge_internal"]
    p95 = value.get("bridge_latency", {}).get("latency_ms_p95")
    if (value.get("status") != "COMPLETED" or not value.get("length_match")
            or value.get("nonfinite_samples") != 0 or value.get("underrun_ms", 1) > 0
            or not isinstance(p95, (int, float)) or not math.isfinite(p95) or p95 >= 400):
        raise ValueError("音频链路未通过延迟或稳定性检查；已有注册保持不变")


def run_worker(config_path: Path, input_device: str, token: str) -> None:
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
    folder = None

    def interrupted(signum, frame):
        if not committed:
            raise InterruptedError("已取消声音设置")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)

    def stage(label, progress):
        job.update(stage=label, progress=progress)
        save_job(config_path, job)

    try:
        root = bundle_root()
        from .cli import require_inactive
        with state_lock(config_path.parent / "setup-worker"):
            require_inactive(config_path)
            folder = config_path.parent / "registrations" / token
            folder.mkdir(parents=True)
            candidate = ProductConfig(
                input_device=input_device, model_repo=root / "vendor",
                model_dir=root / "models" / "tfmap_context_causal_100",
                enrollment=folder / "enrollment.wav", onnx_model=folder / "core.onnx",
                runtime_python=Path(sys.executable), project_root=root, bundle_managed=True)
            source = resolve_device(list_devices(), input_device, "input")
            resolve_device(list_devices(), candidate.output_device, "output")
            stage("3 秒后开始录音，请在安静环境自然朗读 45 秒", 0.05)
            record_input(source, candidate.enrollment, 45, 3)
            stage("正在为你的声音准备模型", 0.3)
            common = ["--repo", str(candidate.model_repo), "--model-dir", str(candidate.model_dir),
                      "--enrollment", str(candidate.enrollment),
                      "--enrollment-seconds", str(candidate.enrollment_seconds)]

            def run(script, arguments):
                subprocess.run([sys.executable, str(root / "tools" / "inference" / script),
                                *common, *arguments], cwd=root, check=True)

            run("export_real_tse_onnx.py", ["--output", str(candidate.onnx_model),
                                           "--report", str(folder / "export.json")])
            stage("正在校验模型", 0.55)
            run("compare_torch_onnx.py", ["--onnx", str(candidate.onnx_model),
                "--frames-per-chunk", "8", "--chunks", "100",
                "--result", str(folder / "correctness.json")])
            if json.loads((folder / "correctness.json").read_text()).get("gate", {}).get("verdict") != "PASS":
                raise ValueError("模型校验未通过；已有注册保持不变")
            stage("正在检查本机性能，请保持正常工作负载", 0.7)
            run("benchmark_onnx_tse.py", ["--onnx", str(candidate.onnx_model),
                "--threads", "1", "--frames", "8", "16", "24", "--audio-seconds", "10",
                "--result", str(folder / "benchmark.json")])
            choice = select_candidate(json.loads((folder / "benchmark.json").read_text()))
            candidate = replace(candidate, frames_per_chunk=choice["frames_per_chunk"])
            for attempt, prefill in enumerate((100, 150, 200), start=1):
                stage(f"正在复核连续输出与延迟（第 {attempt} 次）", 0.9)
                report = folder / f"latency-{prefill}.json"
                run("measure_bridge_latency.py", ["--backend", "onnx",
                    "--onnx", str(candidate.onnx_model), "--onnx-threads", "1",
                    "--frames-per-chunk", str(candidate.frames_per_chunk), "--duration", "30",
                    "--prefill-ms", str(prefill), "--result", str(report)])
                try:
                    validate_latency(json.loads(report.read_text()))
                except ValueError:
                    if prefill == 200:
                        raise
                else:
                    candidate = replace(candidate, prefill_ms=float(prefill))
                    break
            # Config references a new directory: failures never replace old voice/model.
            previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
            try:
                save_config(candidate, config_path)
                committed = True
                job.update(status="READY", stage="设置完成。在输入法中选择 BlackHole 2ch 后即可开始过滤",
                           progress=1, frames_per_chunk=candidate.frames_per_chunk)
                save_job(config_path, job)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    except (InterruptedError, KeyboardInterrupt):
        job.update(status="CANCELLED", stage="已取消；已有注册保持不变")
        save_job(config_path, job)
    except Exception as error:
        job.update(status="FAILED", stage=str(error))
        save_job(config_path, job)
        raise
    finally:
        if folder is not None and not committed:
            shutil.rmtree(folder, ignore_errors=True)
