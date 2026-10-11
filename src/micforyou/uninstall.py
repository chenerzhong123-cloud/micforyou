"""Plan and prepare a clean uninstallation. Deletion of the app bundle and
the optional system driver is handed to a native executor; this module owns
inventory, task shutdown, race prevention, and current-user cleanup.

Safety rules:
- The plan is read-only; nothing is deleted while planning.
- Targets are enumerated from fixed product locations and verified (bundle
  identifier for .app bundles); nothing is derived from configuration files.
- Symlinks and paths outside the allowed roots are refused, never followed.
- ``start``/``setup``/``enroll`` refuse to run while an uninstall marker
  exists, so cleanup cannot race a fresh registration or bridge start.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import time
import fcntl
import shlex
import stat
import tempfile
from contextlib import contextmanager
from functools import wraps

from .product import default_config_path

APP_BUNDLE_ID = "com.micforyou.menubar"
APP_RECEIPT = "com.micforyou.complete"
DRIVER_PATH = Path("/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver")
DRIVER_RECEIPT = "audio.existential.BlackHole2ch"
UNINSTALL_MARKER = "uninstall.lock"


def support_dir(home: Path | None = None) -> Path:
    base = home if home is not None else Path.home()
    return base / "Library" / "Application Support" / "MicForYou"


def user_locations(home: Path) -> dict[str, Path]:
    return {
        "support_dir": support_dir(home),
        "prefs": home / "Library" / "Preferences" / f"{APP_BUNDLE_ID}.plist",
        "caches": home / "Library" / "Caches" / APP_BUNDLE_ID,
        "saved_state": (home / "Library" / "Saved Application State"
                        / f"{APP_BUNDLE_ID}.savedState"),
    }


def tmp_dir() -> Path:
    return Path("/tmp") / f"micforyou-{os.getuid()}"


def coordination_dir() -> Path:
    # Outside every cleanup target; common to all configs for this user.
    return Path.home() / ".micforyou-coordination"


def uninstall_marker_path(config_parent: Path | None = None) -> Path:
    return coordination_dir() / UNINSTALL_MARKER


@contextmanager
def coordination_lock():
    root = coordination_dir()
    root.mkdir(mode=0o700, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("不安全的卸载协调目录")
    root.chmod(0o700)
    fd = os.open(root / "guard.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(fd).st_uid != os.getuid():
            raise ValueError("不安全的卸载协调锁")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def uninstall_in_progress(config_parent: Path | None = None) -> bool:
    path = uninstall_marker_path()
    if not path.exists():
        return False
    # A crashed executor cannot permanently block reinstallation. Only remove
    # its lease after checking the recorded process is no longer that executor.
    try:
        lease = json.loads(path.read_text())
        from .control import process_arguments
        arguments = process_arguments(lease["executor_pid"])
        if arguments and arguments[0] == lease["executor_path"]:
            return True
        directory = Path(lease["executor_path"]).parent
        # An authorized helper may still be finishing a fixed driver command
        # after its executor crashes. Keep the barrier until it also exits.
        from .control import process_command
        for companion in lease.get("companion_pids", []):
            command = process_command(companion)
            if command and str(directory) in command:
                return True
        # Recover only this executor's private directory, never an arbitrary
        # path supplied in stale metadata. Leave the stable guard inode alone.
        if (directory.name.startswith("micforyou-uninstall-") and
                directory.parent.resolve() == Path(tempfile.gettempdir()).resolve() and
                not directory.is_symlink() and directory.exists()):
            info = directory.stat()
            if info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700:
                shutil.rmtree(directory)
        path.unlink()
        return False
    except (OSError, ValueError, KeyError, TypeError):
        return True  # unknown lease is not proof that cleanup has finished


@contextmanager
def startup_guard():
    with coordination_lock():
        if uninstall_in_progress():
            raise ValueError("MicForYou 正在卸载，不能启动或修改任务")
        yield


def coordinated_start(function):
    @wraps(function)
    def run(*args, **kwargs):
        with startup_guard():
            return function(*args, **kwargs)
    return run


def begin_uninstall_window(config_parent: Path | None = None, *,
                           executor_pid: int | None = None,
                           executor_path: str | None = None,
                           companion_pids: list[int] | None = None) -> None:
    with coordination_lock():
        if uninstall_in_progress():
            raise ValueError("MicForYou 正在卸载")
        path = uninstall_marker_path()
        if executor_pid is None:
            # Test/manual lease: explicitly released by its caller.
            path.write_text("manual uninstall in progress\n")
        else:
            path.write_text(json.dumps({"executor_pid": executor_pid,
                                        "executor_path": executor_path,
                                        "companion_pids": companion_pids or []}))
        path.chmod(0o600)


def end_uninstall_window(config_parent: Path | None = None, *, executor_pid: int | None = None) -> None:
    with coordination_lock():
        path = uninstall_marker_path()
        if executor_pid is not None and path.exists():
            lease = json.loads(path.read_text())
            if lease.get("executor_pid") != executor_pid:
                raise ValueError("卸载协调状态不属于本次执行器")
        path.unlink(missing_ok=True)


def read_bundle_id(app_path: Path) -> str | None:
    """Read CFBundleIdentifier from an app bundle without trusting its name."""
    info = app_path / "Contents" / "Info.plist"
    try:
        with info.open("rb") as stream:
            return str(plistlib.load(stream).get("CFBundleIdentifier", ""))
    except (OSError, plistlib.InvalidFile):
        return None


def receipt_installed(receipt: str, runner=subprocess.run) -> bool:
    result = runner(["pkgutil", "--pkg-info", receipt], capture_output=True, text=True)
    return result.returncode == 0


@dataclass(frozen=True)
class PlanTarget:
    kind: str  # app | old_app | support_dir | prefs | caches | saved_state | tmp_dir
    path: Path
    action: str  # trash | delete | optional
    reason: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "path": str(self.path),
                "action": self.action, "reason": self.reason}


def build_plan(
    *,
    remove_user_data: bool,
    remove_driver: bool = False,
    app_path: Path | None = None,
    home: Path | None = None,
    receipt_runner=subprocess.run,
) -> dict:
    """Inventory what an uninstallation would delete and keep. Read-only."""
    home = home if home is not None else Path.home()
    app = app_path if app_path is not None else Path("/Applications/MicForYou.app")
    locations = user_locations(home)
    targets: list[PlanTarget] = []
    keep: list[dict] = []

    if app.exists():
        bundle_id = read_bundle_id(app)
        if bundle_id == APP_BUNDLE_ID:
            targets.append(PlanTarget("app", app, "trash", "已核实的应用本体（含内置模型与运行环境）"))
        else:
            keep.append({"path": str(app), "reason": f"bundle id 不匹配（{bundle_id!r}），不删除"})
    else:
        keep.append({"path": str(app), "reason": "应用不存在（视为已移除）"})

    old_app = home / "Applications" / "MicForYou.app"
    if old_app.exists() and read_bundle_id(old_app) == APP_BUNDLE_ID:
        targets.append(PlanTarget("old_app", old_app, "trash", "旧位置的开发副本，bundle id 已核实"))
    elif old_app.exists():
        keep.append({"path": str(old_app), "reason": "同名但 bundle id 不匹配，不删除"})

    data_items = [("support_dir", "配置、注册录音、个人模型与报告"),
                  ("prefs", "应用偏好"), ("caches", "缓存"), ("saved_state", "窗口状态")]
    for key, label in data_items:
        path = locations[key]
        if remove_user_data:
            if path.exists():
                targets.append(PlanTarget(key, path, "delete", label))
            else:
                keep.append({"path": str(path), "reason": f"{label}：不存在"})
        elif path.exists():
            keep.append({"path": str(path), "reason": f"保留{label}，方便重装后继续使用"})

    control = tmp_dir()
    if control.exists():
        targets.append(PlanTarget("tmp_dir", control, "delete", "本用户控制 socket 残留"))

    driver = {
        "path": str(DRIVER_PATH),
        "exists": DRIVER_PATH.is_dir(),
        "receipt_installed": receipt_installed(DRIVER_RECEIPT, runner=receipt_runner),
        "selected_for_removal": remove_driver,
    }
    if not remove_driver:
        keep.append({"path": str(DRIVER_PATH),
                     "reason": "共享音频驱动，默认保留（其他软件可能使用）"})

    app_receipt = receipt_installed(APP_RECEIPT, runner=receipt_runner)

    return {
        "schema": "micforyou/uninstall-plan/1",
        "remove_user_data": remove_user_data,
        "remove_driver": remove_driver,
        "app_bundle_id": APP_BUNDLE_ID,
        "targets": [item.to_dict() for item in targets],
        "keep": keep,
        "driver": driver,
        "app_receipt_installed": app_receipt,
    }


def _safe_to_delete(path: Path, allowed_roots: tuple[Path, ...]) -> str | None:
    if path not in allowed_roots or ".." in path.parts:
        return "目标不在允许的精确清理范围内"
    # /tmp is a macOS system alias. Every component below that trusted alias,
    # and every component of a user-data path, must remain non-symlink.
    check = path
    boundary = Path("/tmp") if Path("/tmp") in path.parents else Path(path.anchor)
    while check != boundary:
        if check.is_symlink():
            return "目标或父级为符号链接，拒绝删除"
        if check == path and check.exists() and check.stat().st_uid != os.getuid():
            return "目标不属于当前用户"
        check = check.parent
        if check == Path(check.anchor):
            break
    return None


def execute_user_cleanup(
    plan: dict,
    *,
    home: Path | None = None,
    config_path: Path | None = None,
) -> dict:
    """Delete current-user targets from a prepared plan. Idempotent.

    System-level targets (app bundle, driver) are NOT handled here; the native
    executor owns them after the app quits.
    """
    home = home if home is not None else Path.home()
    config_path = config_path if config_path is not None else default_config_path()
    locations = user_locations(home)
    allowed_roots = (
        locations["support_dir"], locations["prefs"],
        locations["caches"], locations["saved_state"], tmp_dir(),
    )
    results = []
    for target in plan.get("targets", []):
        if target.get("kind") in {"app", "old_app"}:
            continue  # native executor trashes bundles
        path = Path(target["path"])
        expected = locations.get(target.get("kind"))
        if target.get("kind") == "tmp_dir":
            expected = tmp_dir()
        refusal = ("类型、动作或路径不匹配" if target.get("action") != "delete" or path != expected
                   else _safe_to_delete(path, allowed_roots))
        if refusal:
            results.append({"path": str(path), "status": "refused", "detail": refusal})
            continue
        if not path.exists():
            results.append({"path": str(path), "status": "absent"})
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            results.append({"path": str(path), "status": "removed"})
        except OSError as error:
            results.append({"path": str(path), "status": "failed", "detail": str(error)})
    verified = all(
        item["status"] in {"removed", "absent"} and not Path(item["path"]).exists()
        for item in results
    )
    return {"results": results, "verified": verified}


def process_groups() -> list[tuple[int, int, str]]:
    result = subprocess.run(["ps", "-ww", "-u", str(os.getuid()), "-o", "pid=,pgid=,command="],
                            capture_output=True, text=True, check=True, timeout=3)
    rows = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3:
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
    return rows


def worker_identity(command: str | list[str] | None, job: dict, config: Path) -> bool:
    if not command or not isinstance(job.get("token"), str) or not job["token"]:
        return False
    try:
        words = shlex.split(command) if isinstance(command, str) else command
        marker = job.get("process_marker")
        if marker is None and os.environ.get("MICFORYOU_BUNDLE_ROOT"):
            marker = str(Path(os.environ["MICFORYOU_BUNDLE_ROOT"]) / "bootstrap.py")
        return (len(words) > 2 and words[1] == marker and words[2] == "setup-worker" and
                words[words.index("--token") + 1] == job["token"] and
                Path(words[words.index("--config") + 1]) == config and
                job.get("config_path", str(config)) == str(config))
    except (ValueError, IndexError):
        return False


def stop_all_tasks(config_path: Path | None = None, *, timeout_seconds: float = 20.0,
                   home: Path | None = None, command_reader=None, signal_sender=None,
                   sleeper=time.sleep, clock=time.monotonic, group_reader=None, arguments_reader=None) -> dict:
    """Under per-task locks, identify again before signaling, await whole groups.

    The coordinator lease freezes new launchers. Missing/corrupt metadata is
    checked against a bounded same-user process census, never a global scan.
    All process operations are injectable for safe fixture tests.
    """
    from .control import load_state, process_command, process_arguments, save_state, RuntimeState, now_iso
    from .runtime_control import state_lock
    from dataclasses import asdict
    config = config_path if config_path is not None else default_config_path()
    real_processes = command_reader is None
    check_groups = real_processes or group_reader is not None
    command_reader = command_reader or process_command
    arguments_reader = arguments_reader or (process_arguments if real_processes else command_reader)
    group_reader = group_reader or (process_groups if real_processes else lambda: [])
    report = {"worker": None, "bridge": None, "all_stopped": True}

    def stop(pid, identity):
        rows = group_reader()
        if command_reader(pid) is None and not any(g == pid for _, g, _ in rows):
            return {"pid": pid, "signaled": False, "exited": True}
        if check_groups and not any(p == pid and g == pid for p, g, _ in rows):
            return {"pid": pid, "signaled": False, "exited": False,
                    "detail": "进程组归属无法核实"}
        if not identity(arguments_reader(pid)):
            return {"pid": pid, "signaled": False, "exited": False,
                    "detail": "任务身份无法核实，未发送信号"}
        try:
            (signal_sender or (lambda p: os.killpg(p, 15)))(pid)
        except ProcessLookupError:
            pass
        deadline = clock() + timeout_seconds
        def alive():
            return command_reader(pid) is not None or any(g == pid for _, g, _ in group_reader())
        while clock() < deadline and alive():
            sleeper(0.1)
        return {"pid": pid, "signaled": True, "exited": not alive()}

    job_path = config.parent / "setup-job.json"
    with state_lock(job_path):
        try:
            job = json.loads(job_path.read_text())
        except (OSError, ValueError):
            job = {}
        if job.get("status") == "RUNNING":
            pid = job.get("pid")
            report["worker"] = (stop(pid, lambda c: worker_identity(c, job, config))
                                if isinstance(pid, int) and pid > 0 else
                                {"signaled": False, "exited": False, "detail": "worker PID 缺失"})
            report["all_stopped"] &= report["worker"]["exited"]
    state_path = config.parent / "state.json"
    with state_lock(state_path):
        try:
            state = load_state(state_path)
        except (OSError, ValueError, TypeError):
            state = None
        if state and state.pid is not None:
            def bridge_identity(command):
                if not command or state.config_path != str(config) or not state.process_marker:
                    return False
                words = shlex.split(command) if isinstance(command, str) else command
                return len(words) > 1 and words[1] == state.process_marker and state.control_token is not None and state.control_token in words
            report["bridge"] = stop(state.pid, bridge_identity)
            report["all_stopped"] &= report["bridge"]["exited"]
            if report["bridge"]["exited"]:
                save_state(RuntimeState(**{**asdict(state), "status": "STOPPED", "pid": None,
                                           "process_marker": None, "updated_at": now_iso()}), state_path)
    # Also catches children surviving their leader, and workers whose job/state
    # was removed or damaged. Refuse cleanup rather than kill an unknown task.
    child_scripts = ("run_real_tse_bridge.py", "export_real_tse_onnx.py",
                     "benchmark_onnx_tse.py", "compare_torch_onnx.py", "measure_bridge_latency.py")
    leftovers = [p for p, _, cmd in group_reader()
                 if ("setup-worker" in cmd and "bootstrap.py" in cmd)
                 or any(script in cmd for script in child_scripts)]
    if leftovers:
        report.update(all_stopped=False, unidentified_pids=leftovers)
    return report
