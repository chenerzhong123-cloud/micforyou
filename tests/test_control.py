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
    switch_managed_mode,
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


def test_managed_process_pause_resume_same_pid_and_stop(tmp_path: Path) -> None:
    helper = tmp_path / "bridge-helper.py"
    result = tmp_path / "result.json"
    ready = tmp_path / "ready"
    source = Path(__file__).resolve().parents[1] / "src"
    helper.write_text(f"import sys\nsys.path.insert(0, {str(source)!r})\n" + r"""
import argparse, json, signal, time
from pathlib import Path
import numpy as np
from micforyou.bridging import BridgeEngine
from micforyou.modes import SwitchableBridge
from micforyou.runtime_control import ControlServer
p = argparse.ArgumentParser()
p.add_argument('result'); p.add_argument('ready')
p.add_argument('--control-socket', type=Path); p.add_argument('--control-token')
a = p.parse_args()
raw_checks = 0
models = 0
stream_opens = 1

def transform(block):
    global models
    models += 1
    return block * 0.25

def factory():
    return BridgeEngine(transform, lambda: np.empty(0, np.float32), input_bound_blocks=8, ring_maximum_frames=4096)
engine = SwitchableBridge(factory)
server = ControlServer(a.control_socket, a.control_token, engine.switch)
def stop(*args):
    raise KeyboardInterrupt
signal.signal(signal.SIGINT, stop)
Path(a.ready).write_text('ready')
block = np.linspace(-0.5, 0.5, 480, dtype=np.float32)
try:
    while True:
        output, written = engine.process(block, len(block))
        if engine.mode == 'passthrough':
            assert np.array_equal(output, block)
            raw_checks += 1
        time.sleep(0.01)
except KeyboardInterrupt:
    pass
finally:
    engine.close(); server.close()
    Path(a.result).write_text(json.dumps({'status':'STOPPED','final_mode':engine.mode,'degraded':False,
        'raw_checks':raw_checks,'stream_opens':stream_opens,'model_calls':models}))
""")
    state_path = tmp_path / "state.json"
    running = start_managed_process(
        [sys.executable, str(helper), str(result), str(ready)],
        config_path=tmp_path / "config.json", state_path=state_path,
        result_path=result, log_path=tmp_path / "bridge.log",
        health_path=tmp_path / "health.json", cwd=tmp_path, process_marker=str(helper),
    )
    try:
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        assert owns_process(running)
        paused = switch_managed_mode(state_path=state_path, mode="passthrough")
        assert paused.status == "PAUSED"
        assert paused.pid == running.pid
        assert owns_process(paused)
        assert paused.processing_mode == "passthrough"
        assert not result.exists()
        from micforyou.cli import require_inactive
        with pytest.raises(ValueError, match="end MicForYou"):
            require_inactive(tmp_path / "config.json")
        with pytest.raises(ValueError, match="already running"):
            start_managed_process(
                [sys.executable, str(helper)], config_path=tmp_path / "config.json",
                state_path=state_path, result_path=result, log_path=tmp_path / "other.log",
                health_path=None, cwd=tmp_path, process_marker=str(helper),
            )
        resumed = switch_managed_mode(state_path=state_path, mode="tse")
        assert resumed.pid == running.pid
        assert resumed.status == "RUNNING"
        assert resumed.mode_revision == 2
        switch_managed_mode(state_path=state_path, mode="passthrough")
        stopped = stop_managed_process(state_path=state_path, final_status="STOPPED", timeout_seconds=3)
        assert stopped.pid is None
        assert stopped.processing_mode == "none"
        report = json.loads(result.read_text())
        assert report['raw_checks'] > 0
        assert report['stream_opens'] == 1
    finally:
        current = load_state(state_path)
        if current and owns_process(current):
            stop_managed_process(state_path=state_path, final_status="STOPPED", timeout_seconds=3)


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


def test_old_paused_state_does_not_start_or_claim_raw_output(tmp_path):
    path = tmp_path / "state.json"
    old = state(tmp_path, status="PAUSED", pid=None, process_marker=None).to_dict()
    old["schema"] = "micforyou/runtime-state/1"
    for key in ("control_path", "control_token", "processing_mode", "mode_reason", "mode_revision"):
        old.pop(key)
    path.write_text(json.dumps(old))
    loaded = load_state(path)
    assert loaded.pid is None
    assert loaded.processing_mode == "none"
    with pytest.raises(ValueError, match="no live"):
        switch_managed_mode(state_path=path, mode="tse")


def test_dead_paused_process_is_refreshed(tmp_path):
    current = state(tmp_path, status="PAUSED", processing_mode="passthrough")
    refreshed = refresh_state(current, tmp_path / "state.json")
    assert refreshed.pid is None
    assert refreshed.processing_mode == "none"
    assert refreshed.status == "FAULT"
