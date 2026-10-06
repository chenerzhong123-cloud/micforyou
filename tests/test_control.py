import json
from pathlib import Path
import sys
import time

import pytest

from micforyou.control import (
    RuntimeState,
    load_state,
    owns_process,
    refresh_state,
    save_state,
    start_managed_process,
    stop_managed_process,
)


def state(tmp_path: Path, **changes) -> RuntimeState:
    values = {
        "status": "RUNNING",
        "pid": 123,
        "process_marker": "bridge-marker",
        "started_at": "2026-09-22T12:00:00+08:00",
        "updated_at": "2026-09-22T12:00:01+08:00",
        "config_path": str(tmp_path / "config.json"),
        "result_path": str(tmp_path / "result.json"),
        "log_path": str(tmp_path / "bridge.log"),
        "detail": None,
        "health_path": str(tmp_path / "health.json"),
    }
    values.update(changes)
    return RuntimeState(**values)


def test_runtime_state_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_state(state(tmp_path), path)
    assert load_state(path) == state(tmp_path)


def test_process_ownership_requires_marker_match(tmp_path: Path) -> None:
    current = state(tmp_path)
    assert owns_process(current, lambda pid: "python bridge-marker --run")
    assert not owns_process(current, lambda pid: "python unrelated.py")
    assert not owns_process(current, lambda pid: None)


def test_refresh_dead_process_uses_report(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps({"status": "STOPPED", "final_mode": "tse", "degraded": False})
    )
    current = state(tmp_path)
    save_state(current, state_path)

    refreshed = refresh_state(current, state_path)

    assert refreshed.status == "STOPPED"


def test_managed_process_start_pause_and_release(tmp_path: Path) -> None:
    helper = tmp_path / "bridge-helper.py"
    result = tmp_path / "result.json"
    ready = tmp_path / "ready"
    helper.write_text(
        "import json, signal, sys, time\n"
        "result = sys.argv[1]\n"
        "ready = sys.argv[2]\n"
        "def stop(signum, frame):\n"
        "    open(result, 'w').write(json.dumps({'status':'STOPPED','final_mode':'tse','degraded':False}))\n"
        "    raise SystemExit(0)\n"
        "signal.signal(signal.SIGINT, stop)\n"
        "open(ready, 'w').write('ready')\n"
        "while True: time.sleep(0.05)\n"
    )
    state_path = tmp_path / "state.json"
    running = start_managed_process(
        [sys.executable, str(helper), str(result), str(ready)],
        config_path=tmp_path / "config.json",
        state_path=state_path,
        result_path=result,
        log_path=tmp_path / "bridge.log",
        health_path=tmp_path / "health.json",
        cwd=tmp_path,
        process_marker=str(helper),
    )
    assert running.status == "STARTING"
    deadline = time.monotonic() + 2
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ready.exists()
    assert owns_process(running)

    paused = stop_managed_process(
        state_path=state_path, final_status="PAUSED", timeout_seconds=3
    )

    assert paused.status == "PAUSED"
    assert paused.pid is None
    assert result.exists()


def test_refuses_to_signal_unowned_process(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_state(state(tmp_path, pid=999_999), path)
    with pytest.raises(ValueError, match="not running"):
        stop_managed_process(
            state_path=path, final_status="STOPPED", timeout_seconds=0.1
        )


def test_paused_bridge_can_be_ended_without_a_process(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_state(state(tmp_path, status="PAUSED", pid=None, process_marker=None), path)

    stopped = stop_managed_process(
        state_path=path, final_status="STOPPED", timeout_seconds=0.1
    )

    assert stopped.status == "STOPPED"
    assert stopped.pid is None
    assert stopped.detail == "microphone released; bridge stopped"
