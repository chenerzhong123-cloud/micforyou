"""Lifecycle control for the Stage-D background bridge.

The controller stores metadata only.  It never stores audio, embeddings, or
transcripts.  Every background bridge is its own process group so pause/stop
can interrupt the exact process started by MicForYou without touching other
Python processes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Callable


CONTROL_SCHEMA = "micforyou/runtime-state/1"
ACTIVE_STATES = {"STARTING", "RUNNING", "STOPPING"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def default_state_path(config_path: Path) -> Path:
    return config_path.parent / "state.json"


def default_log_dir(config_path: Path) -> Path:
    return config_path.parent / "logs"


@dataclass(frozen=True)
class RuntimeState:
    status: str
    pid: int | None
    process_marker: str | None
    started_at: str | None
    updated_at: str
    config_path: str
    result_path: str | None
    log_path: str | None
    detail: str | None = None
    health_path: str | None = None

    def to_dict(self) -> dict:
        return {"schema": CONTROL_SCHEMA, **asdict(self)}

    @classmethod
    def from_dict(cls, payload: dict) -> "RuntimeState":
        if payload.get("schema") != CONTROL_SCHEMA:
            raise ValueError("unsupported MicForYou runtime-state schema")
        values = dict(payload)
        values.pop("schema")
        state = cls(**values)
        if state.status not in {
            "STARTING", "RUNNING", "STOPPING", "PAUSED", "STOPPED", "FAULT"
        }:
            raise ValueError(f"invalid runtime status: {state.status}")
        return state


def save_state(state: RuntimeState, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def load_state(source: Path) -> RuntimeState | None:
    if not source.exists():
        return None
    return RuntimeState.from_dict(json.loads(source.read_text(encoding="utf-8")))


def process_command(pid: int) -> str | None:
    if pid <= 0:
        return None
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            check=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


def owns_process(
    state: RuntimeState,
    command_reader: Callable[[int], str | None] = process_command,
) -> bool:
    if state.pid is None or not state.process_marker:
        return False
    command = command_reader(state.pid)
    return command is not None and state.process_marker in command


def refresh_state(state: RuntimeState, state_path: Path) -> RuntimeState:
    if state.status not in ACTIVE_STATES or owns_process(state):
        return state
    detail = "managed bridge exited"
    final_status = "FAULT"
    if state.result_path:
        result_path = Path(state.result_path)
        if result_path.exists():
            try:
                report = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                detail = "managed bridge exited; result report is unreadable"
            else:
                report_status = report.get("status")
                final_status = "FAULT" if report_status == "FAULT" else "STOPPED"
                mode = report.get("final_mode")
                degraded = report.get("degraded")
                detail = (
                    f"bridge report status={report_status}, "
                    f"mode={mode}, degraded={degraded}"
                )
    refreshed = RuntimeState(
        status=final_status,
        pid=None,
        process_marker=None,
        started_at=state.started_at,
        updated_at=now_iso(),
        config_path=state.config_path,
        result_path=state.result_path,
        log_path=state.log_path,
        detail=detail,
        health_path=state.health_path,
    )
    save_state(refreshed, state_path)
    return refreshed


def start_managed_process(
    command: list[str],
    *,
    config_path: Path,
    state_path: Path,
    result_path: Path,
    log_path: Path,
    health_path: Path | None,
    cwd: Path,
    process_marker: str,
) -> RuntimeState:
    previous = load_state(state_path)
    if previous is not None:
        previous = refresh_state(previous, state_path)
        if previous.status in ACTIVE_STATES and owns_process(previous):
            raise ValueError(f"MicForYou is already running (pid {previous.pid})")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = now_iso()
    starting = RuntimeState(
        status="STARTING",
        pid=None,
        process_marker=process_marker,
        started_at=started_at,
        updated_at=started_at,
        config_path=str(config_path),
        result_path=str(result_path),
        log_path=str(log_path),
        detail="launching privacy-first TSE bridge",
        health_path=str(health_path) if health_path else None,
    )
    save_state(starting, state_path)
    try:
        with log_path.open("ab", buffering=0) as log_stream:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except Exception as error:
        failed = RuntimeState(
            **{
                **asdict(starting),
                "status": "FAULT",
                "updated_at": now_iso(),
                "detail": f"launch failed: {error}",
            }
        )
        save_state(failed, state_path)
        raise
    running = RuntimeState(
        status="STARTING",
        pid=process.pid,
        process_marker=process_marker,
        started_at=started_at,
        updated_at=now_iso(),
        config_path=str(config_path),
        result_path=str(result_path),
        log_path=str(log_path),
        detail="bridge process started; waiting for the audio route to open",
        health_path=str(health_path) if health_path else None,
    )
    save_state(running, state_path)
    return running


def stop_managed_process(
    *,
    state_path: Path,
    final_status: str,
    timeout_seconds: float = 15.0,
) -> RuntimeState:
    if final_status not in {"PAUSED", "STOPPED"}:
        raise ValueError("final_status must be PAUSED or STOPPED")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    state = load_state(state_path)
    if state is None:
        raise ValueError("MicForYou has no runtime state")
    state = refresh_state(state, state_path)
    if state.status == "PAUSED" and final_status == "STOPPED":
        stopped = RuntimeState(
            **{
                **asdict(state),
                "status": "STOPPED",
                "updated_at": now_iso(),
                "detail": "microphone released; bridge stopped",
            }
        )
        save_state(stopped, state_path)
        return stopped
    if state.status not in ACTIVE_STATES:
        if state.status == final_status:
            return state
        raise ValueError(f"MicForYou is not running (status {state.status})")
    if not owns_process(state):
        raise ValueError("refusing to signal a process not owned by MicForYou")

    stopping = RuntimeState(
        **{
            **asdict(state),
            "status": "STOPPING",
            "updated_at": now_iso(),
            "detail": f"stopping bridge for {final_status.lower()}",
        }
    )
    save_state(stopping, state_path)
    assert state.pid is not None
    os.killpg(state.pid, signal.SIGINT)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline and process_command(state.pid) is not None:
        time.sleep(0.1)
    if process_command(state.pid) is not None:
        os.killpg(state.pid, signal.SIGTERM)
        terminate_deadline = time.monotonic() + 2.0
        while (
            time.monotonic() < terminate_deadline
            and process_command(state.pid) is not None
        ):
            time.sleep(0.1)
    if process_command(state.pid) is not None:
        failed = RuntimeState(
            **{
                **asdict(stopping),
                "status": "FAULT",
                "updated_at": now_iso(),
                "detail": "managed bridge did not stop after SIGINT and SIGTERM",
            }
        )
        save_state(failed, state_path)
        raise RuntimeError(failed.detail)

    stopped = RuntimeState(
        status=final_status,
        pid=None,
        process_marker=None,
        started_at=state.started_at,
        updated_at=now_iso(),
        config_path=state.config_path,
        result_path=state.result_path,
        log_path=state.log_path,
        detail=(
            "microphone released; resume rebuilds all TSE streaming state"
            if final_status == "PAUSED"
            else "microphone released; bridge stopped"
        ),
        health_path=state.health_path,
    )
    save_state(stopped, state_path)
    return stopped
