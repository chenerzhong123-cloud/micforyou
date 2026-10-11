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


def uninstall_marker_path(config_parent: Path | None = None) -> Path:
    base = config_parent if config_parent is not None else default_config_path().parent
    return base / UNINSTALL_MARKER


def uninstall_in_progress(config_parent: Path | None = None) -> bool:
    return uninstall_marker_path(config_parent).exists()


def begin_uninstall_window(config_parent: Path | None = None) -> None:
    path = uninstall_marker_path(config_parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("uninstall in progress; do not start tasks\n", encoding="utf-8")


def end_uninstall_window(config_parent: Path | None = None) -> None:
    uninstall_marker_path(config_parent).unlink(missing_ok=True)


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
    """Return a refusal reason, or None when deletion may proceed."""
    if path.is_symlink():
        return "符号链接，拒绝删除"
    resolved = path.resolve(strict=False)
    if resolved == Path(resolved.anchor):
        return "拒绝删除根目录"
    inside = any(
        resolved == root or root in resolved.parents
        for root in (r.resolve(strict=False) for r in allowed_roots)
    )
    if not inside:
        return "目标不在允许的清理范围内"
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
        if not path.exists():
            results.append({"path": str(path), "status": "absent"})
            continue
        refusal = _safe_to_delete(path, allowed_roots)
        if refusal:
            results.append({"path": str(path), "status": "refused", "detail": refusal})
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
        not Path(item["path"]).exists()
        for item in results
        if item["status"] in {"removed", "absent"}
    )
    return {"results": results, "verified": verified}


def stop_all_tasks(
    config_path: Path | None = None,
    *,
    timeout_seconds: float = 20.0,
    home: Path | None = None,
    command_reader=None,
    signal_sender=None,
    sleeper=time.sleep,
    clock=time.monotonic,
) -> dict:
    """Stop the setup worker and the background bridge, then wait for exit.

    Uses the existing identity rules (worker token via ps, process marker) and
    never signals a PID it cannot identify. The marker file must already be in
    place so no new task can start while we shut down.
    """
    from .control import load_state, owns_process, process_command, stop_managed_process
    from .runtime_control import state_lock

    if command_reader is None:
        command_reader = process_command
    config_path = config_path if config_path is not None else default_config_path()
    state_path = config_path.parent / "state.json"
    report = {"worker": None, "bridge": None, "all_stopped": True}

    job_path = config_path.parent / "setup-job.json"
    with state_lock(job_path):
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            job = {}
        pid = job.get("pid")
        if job.get("status") == "RUNNING" and isinstance(pid, int):
            command = command_reader(pid)
            if command and "setup-worker" in command:
                report["worker"] = {"pid": pid, "signaled": True}
                if signal_sender is not None:
                    signal_sender(pid)
                else:
                    os.killpg(pid, 15)
                deadline = clock() + timeout_seconds
                while clock() < deadline and command_reader(pid) is not None:
                    sleeper(0.1)
                alive = command_reader(pid) is not None
                report["worker"]["exited"] = not alive
                report["all_stopped"] = report["all_stopped"] and not alive
            else:
                report["worker"] = {"pid": pid, "signaled": False,
                                    "detail": "无法核实归属，未发送信号"}
                report["all_stopped"] = False

    with state_lock(state_path):
        state = load_state(state_path)
        if state is not None and state.status in {"STARTING", "RUNNING", "RECOVERING",
                                                  "PAUSED", "STOPPING"}:
            if state.pid is not None and owns_process(state, command_reader):
                try:
                    stopped = stop_managed_process(
                        state_path=state_path, final_status="STOPPED",
                        timeout_seconds=timeout_seconds)
                    report["bridge"] = {"pid": state.pid,
                                        "status": stopped.status}
                    report["all_stopped"] = report["all_stopped"] and stopped.status == "STOPPED"
                except ValueError as error:
                    report["bridge"] = {"pid": state.pid, "status": "FAILED",
                                        "detail": str(error)}
                    report["all_stopped"] = False
            else:
                report["bridge"] = {"pid": state.pid, "status": "skipped",
                                    "detail": "进程身份无法核实，未停止"}
                report["all_stopped"] = False
    return report
