"""Uninstall planning, race prevention, and current-user cleanup contract."""
import json
import os
import plistlib
from pathlib import Path

import pytest

from micforyou import uninstall
from micforyou.cli import build_parser


def fake_app(path: Path, bundle_id: str) -> Path:
    contents = path / "Contents"
    contents.mkdir(parents=True)
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundleIdentifier": bundle_id}, stream)
    (contents / "MacOS").mkdir()
    (contents / "MacOS" / "MicForYouMenuBar").write_bytes(b"\xcf\xfa\xed\xfe")
    return path


def fake_receipts(*present: str):
    def runner(command, **kwargs):
        class Result:
            def __init__(self, code):
                self.returncode = code
        return Result(0 if command[1] == "--pkg-info" and command[2] in present else 1)
    return runner


def make_locations(home: Path) -> dict:
    spots = uninstall.user_locations(home)
    spots["support_dir"].mkdir(parents=True)
    (spots["support_dir"] / "config.json").write_text("{}")
    (spots["support_dir"] / "registrations").mkdir()
    (spots["support_dir"] / "registrations" / "voice.wav").write_bytes(b"voice")
    spots["prefs"].parent.mkdir(parents=True, exist_ok=True)
    spots["prefs"].write_bytes(b"plist-bytes")
    return spots


@pytest.fixture(autouse=True)
def private_coordinator(tmp_path, monkeypatch):
    monkeypatch.setattr(uninstall, "coordination_dir", lambda: tmp_path / "coordinator")
    monkeypatch.setattr(uninstall, "tmp_dir", lambda: tmp_path / "private-control")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


def test_plan_defaults_delete_user_data_and_keep_driver(home: Path, tmp_path: Path):
    app = fake_app(tmp_path / "Applications" / "MicForYou.app", uninstall.APP_BUNDLE_ID)
    make_locations(home)
    plan = uninstall.build_plan(
        remove_user_data=True, app_path=app, home=home,
        receipt_runner=fake_receipts(uninstall.APP_RECEIPT))
    kinds = {item["kind"] for item in plan["targets"]}
    # tmp_dir/caches/saved_state appear only when they exist on this machine.
    assert {"app", "support_dir", "prefs"} <= kinds
    assert kinds <= {"app", "support_dir", "prefs", "tmp_dir", "caches", "saved_state"}
    assert plan["driver"]["selected_for_removal"] is False
    assert any("共享音频驱动" in item["reason"] for item in plan["keep"])
    assert plan["app_receipt_installed"] is True


def test_plan_keep_data_lists_retained_directory(home: Path, tmp_path: Path):
    app = fake_app(tmp_path / "Applications" / "MicForYou.app", uninstall.APP_BUNDLE_ID)
    make_locations(home)
    plan = uninstall.build_plan(
        remove_user_data=False, app_path=app, home=home, receipt_runner=fake_receipts())
    kinds = {item["kind"] for item in plan["targets"]}
    assert "support_dir" not in kinds and "prefs" not in kinds
    assert any("保留" in item["reason"] for item in plan["keep"])


def test_plan_refuses_apps_with_wrong_bundle_id(home: Path, tmp_path: Path):
    other = fake_app(tmp_path / "Applications" / "MicForYou.app", "someone.else.app")
    make_locations(home)
    plan = uninstall.build_plan(
        remove_user_data=True, app_path=other, home=home, receipt_runner=fake_receipts())
    assert all(item["kind"] != "app" for item in plan["targets"])
    assert any("bundle id 不匹配" in item["reason"] for item in plan["keep"])


def test_plan_missing_app_and_driver_variants(home: Path, tmp_path: Path):
    make_locations(home)
    missing = uninstall.build_plan(
        remove_user_data=True, app_path=tmp_path / "nope.app", home=home,
        receipt_runner=fake_receipts())
    assert any("不存在" in item["reason"] for item in missing["keep"])

    selected = uninstall.build_plan(
        remove_user_data=True, remove_driver=True, app_path=tmp_path / "nope.app",
        home=home, receipt_runner=fake_receipts(uninstall.DRIVER_RECEIPT))
    assert selected["driver"]["selected_for_removal"] is True
    assert selected["driver"]["receipt_installed"] is True


def test_cleanup_removes_user_locations_with_spaces_and_unicode(home: Path):
    make_locations(home)
    deep = uninstall.user_locations(home)["support_dir"] / "运行 报告 2026"
    deep.mkdir()
    (deep / "结果.json").write_text("{}")
    plan = uninstall.build_plan(remove_user_data=True, home=home,
                                app_path=home / "absent.app", receipt_runner=fake_receipts())
    result = uninstall.execute_user_cleanup(plan, home=home)
    assert result["verified"] is True
    assert not uninstall.user_locations(home)["support_dir"].exists()
    assert not uninstall.user_locations(home)["prefs"].exists()


def test_cleanup_refuses_symlinks_and_outside_paths(home: Path, tmp_path: Path):
    make_locations(home)
    victim = tmp_path / "outside"
    victim.mkdir()
    (victim / "secret").write_text("keep")
    locations = uninstall.user_locations(home)
    os.symlink(victim, locations["support_dir"] / "escape")
    plan = uninstall.build_plan(remove_user_data=True, home=home,
                                app_path=home / "absent.app", receipt_runner=fake_receipts())
    plan["targets"].append({"kind": "user_data", "path": str(victim),
                            "action": "delete", "reason": "malicious"})
    result = uninstall.execute_user_cleanup(plan, home=home)
    by_path = {item["path"]: item["status"] for item in result["results"]}
    assert by_path[str(victim)] == "refused"
    assert victim.joinpath("secret").exists()
    # The support dir itself was removed together with the symlink inside it.
    assert not locations["support_dir"].exists()


def test_cleanup_is_idempotent(home: Path):
    make_locations(home)
    plan = uninstall.build_plan(remove_user_data=True, home=home,
                                app_path=home / "absent.app", receipt_runner=fake_receipts())
    first = uninstall.execute_user_cleanup(plan, home=home)
    second = uninstall.execute_user_cleanup(plan, home=home)
    assert first["verified"] and second["verified"]
    assert all(item["status"] == "absent" for item in second["results"])


def test_marker_blocks_start_setup_enroll_and_start(tmp_path: Path, monkeypatch):
    config = tmp_path / "userdata" / "config.json"
    config.parent.mkdir(parents=True)
    uninstall.begin_uninstall_window(config.parent)
    try:
        from micforyou.setup import start_setup
        with pytest.raises(ValueError, match="卸载"):
            start_setup(config, "Mic")

        from micforyou import cli
        monkeypatch.setattr(cli, "product_status", lambda *a: pytest.fail("status queried"))
        for command in (["start", "--config", str(config)],
                        ["enroll", "--config", str(config)]):
            args = build_parser().parse_args(command)
            with pytest.raises(ValueError, match="卸载"):
                args.func(args)
    finally:
        uninstall.end_uninstall_window(config.parent)
    assert not uninstall.uninstall_in_progress(config.parent)


def test_stop_all_tasks_waits_for_worker_exit(tmp_path: Path):
    config = tmp_path / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    (config.parent / "setup-job.json").write_text(json.dumps(
        {"status": "RUNNING", "pid": 4242, "token": "t", "process_marker": "/env/bootstrap.py", "config_path": str(config)}))
    calls = {"signals": 0}

    def reader(pid):
        return None if calls["signals"] else f"/env/bin/python /env/bootstrap.py setup-worker --token t --config {config}"

    def sender(pid):
        calls["signals"] += 1

    import micforyou.control as control
    report = uninstall.stop_all_tasks(
        config, command_reader=reader, signal_sender=sender,
        sleeper=lambda _s: None, clock=lambda: 0.0)
    assert calls["signals"] == 1
    assert report["worker"]["exited"] is True
    assert report["all_stopped"] is True


def test_stop_all_tasks_reports_unverifiable_worker(tmp_path: Path):
    config = tmp_path / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    (config.parent / "setup-job.json").write_text(json.dumps(
        {"status": "RUNNING", "pid": 999, "token": "t"}))

    def reader(pid):
        return "/usr/bin/someone_else"

    report = uninstall.stop_all_tasks(config, command_reader=reader,
                                      signal_sender=lambda pid: pytest.fail("signaled foreign pid"),
                                      sleeper=lambda _s: None, clock=lambda: 0.0)
    assert report["worker"]["signaled"] is False
    assert report["all_stopped"] is False


def test_stop_all_tasks_reports_timeout(tmp_path: Path):
    config = tmp_path / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    (config.parent / "setup-job.json").write_text(json.dumps(
        {"status": "RUNNING", "pid": 7, "token": "t", "process_marker": "/env/bootstrap.py", "config_path": str(config)}))

    def reader(pid):
        return f"/env/bin/python /env/bootstrap.py setup-worker --token t --config {config}"

    ticks = iter([0.0, 0.0, 100.0])
    report = uninstall.stop_all_tasks(
        config, command_reader=reader, signal_sender=lambda pid: None,
        sleeper=lambda _s: None, clock=lambda: next(ticks))
    assert report["worker"]["exited"] is False
    assert report["all_stopped"] is False


def test_parent_symlink_and_wrong_action_refused(home, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    home.mkdir()
    (home / "Library").symlink_to(outside, target_is_directory=True)
    support = uninstall.user_locations(home)["support_dir"]
    support.mkdir(parents=True)
    (support / "voice.wav").write_text("keep")
    plan = {"targets": [{"kind": "support_dir", "path": str(support), "action": "delete"}]}
    result = uninstall.execute_user_cleanup(plan, home=home)
    assert not result["verified"] and result["results"][0]["status"] == "refused"
    assert (support / "voice.wav").exists()
    plan["targets"][0]["action"] = "trash"
    assert not uninstall.execute_user_cleanup(plan, home=home)["verified"]


def test_token_mismatch_and_second_identity_check(tmp_path):
    config = tmp_path / "config.json"
    job = {"status": "RUNNING", "pid": 7, "token": "expected",
           "process_marker": "/env/bootstrap.py", "config_path": str(config)}
    (tmp_path / "setup-job.json").write_text(json.dumps(job))
    command = f"python /env/bootstrap.py setup-worker --config {config} --token different"
    report = uninstall.stop_all_tasks(config, command_reader=lambda p: command,
                                     signal_sender=lambda p: pytest.fail("foreign task signaled"))
    assert not report["all_stopped"]
    assert not report["worker"]["signaled"]


def test_waits_for_children_after_leader_exit(tmp_path):
    config = tmp_path / "config.json"
    job = {"status": "RUNNING", "pid": 7, "token": "t",
           "process_marker": "/env/bootstrap.py", "config_path": str(config)}
    (tmp_path / "setup-job.json").write_text(json.dumps(job))
    command = f"python /env/bootstrap.py setup-worker --config {config} --token t"
    signaled = []
    reader = lambda p: None if signaled else command
    def groups():
        return [(8, 7, "python exporter.py")] if signaled else [(7, 7, command), (8, 7, "python exporter.py")]
    ticks = iter([0, 0, 100])
    report = uninstall.stop_all_tasks(config, command_reader=reader,
                                     signal_sender=signaled.append, group_reader=groups,
                                     sleeper=lambda _: None, clock=lambda: next(ticks))
    assert signaled == [7] and not report["all_stopped"]


def test_corrupt_state_with_orphan_worker_refuses(tmp_path):
    config = tmp_path / "config.json"
    (tmp_path / "setup-job.json").write_text("{broken")
    report = uninstall.stop_all_tasks(config, command_reader=lambda _: None,
                                     group_reader=lambda: [(8, 7, "python /env/bootstrap.py setup-worker")])
    assert not report["all_stopped"] and report["unidentified_pids"] == [8]


def test_active_bridge_real_flock_does_not_reenter(tmp_path):
    # Run a real lock in a bounded child; the injected signal must never reach
    # the OS. A nested flock would exceed the outer subprocess timeout.
    import subprocess
    import sys
    script = r'''
import json,sys
from pathlib import Path
from micforyou.control import RuntimeState, save_state
from micforyou.uninstall import stop_all_tasks
config=Path(sys.argv[1]); token="bridge-test-token"
state=RuntimeState("RUNNING", 7, "/env/run_real_tse_bridge.py", None, "now", str(config), None, None, control_token=token)
save_state(state, config.parent/"state.json")
signals=[]
report=stop_all_tasks(config, timeout_seconds=.1,
 command_reader=lambda p: None if signals else "python /env/run_real_tse_bridge.py --control-token bridge-test-token",
 signal_sender=signals.append)
assert report["all_stopped"] and signals == [7], report
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path / "config.json")],
                            capture_output=True, text=True, timeout=3)
    assert result.returncode == 0, result.stderr


def test_cli_stop_failure_does_not_delete(home, tmp_path, monkeypatch):
    from micforyou import cli, control
    locations = make_locations(home)
    config = locations["support_dir"] / "config.json"
    work = tmp_path / "executor-work"
    work.mkdir(mode=0o700)
    (work / "ready").write_text('{"companion_pids": []}')
    executor = work / "executor"
    monkeypatch.setattr(cli, "default_config_path", lambda: config)
    monkeypatch.setattr(control, "process_arguments", lambda _: [str(executor), "--plan", "foo"])
    monkeypatch.setattr(uninstall, "stop_all_tasks", lambda _: {"all_stopped": False})
    monkeypatch.setattr(uninstall, "execute_user_cleanup", lambda *_: pytest.fail("cleanup before handoff"))
    args = build_parser().parse_args(["uninstall", "--config", str(config), "--result", str(work / "plan.json"),
                                     "--executor-pid", "7", "--executor-path", str(executor)])
    with pytest.raises(ValueError, match="停止"):
        args.func(args)
    assert (locations["support_dir"] / "registrations/voice.wav").read_bytes() == b"voice"
    assert not uninstall.uninstall_marker_path().exists()


def test_cli_handoff_keeps_data_and_lease_until_executor(home, tmp_path, monkeypatch):
    from micforyou import cli, control
    locations = make_locations(home)
    config = locations["support_dir"] / "config.json"
    work = tmp_path / "executor-work"
    work.mkdir(mode=0o700)
    (work / "ready").write_text('{"companion_pids": []}')
    executor = work / "executor"
    monkeypatch.setattr(cli, "default_config_path", lambda: config)
    monkeypatch.setattr(control, "process_arguments", lambda _: [str(executor), "--plan", "foo"])
    monkeypatch.setattr(uninstall, "stop_all_tasks", lambda _: {"all_stopped": True})
    original = uninstall.build_plan
    monkeypatch.setattr(uninstall, "build_plan", lambda **kwargs: original(**kwargs, home=home, receipt_runner=fake_receipts()))
    result = work / "plan.json"
    args = build_parser().parse_args(["uninstall", "--config", str(config), "--result", str(result),
                                     "--executor-pid", "7", "--executor-path", str(executor)])
    args.func(args)
    payload = json.loads(result.read_text())
    assert payload["stopped"]["all_stopped"]
    assert uninstall.uninstall_in_progress(config.parent)
    uninstall.execute_user_cleanup(payload["plan"], home=home)
    assert uninstall.uninstall_in_progress(config.parent)  # data removed, lease still active
    uninstall.end_uninstall_window()
    assert not uninstall.uninstall_in_progress(config.parent)


def test_executor_missing_or_not_ready_preserves_data(home, tmp_path, monkeypatch):
    from micforyou import cli, control
    locations = make_locations(home)
    config = locations["support_dir"] / "config.json"
    monkeypatch.setattr(cli, "default_config_path", lambda: config)
    monkeypatch.setattr(control, "process_arguments", lambda _: None)
    args = build_parser().parse_args(["uninstall", "--config", str(config), "--result", str(tmp_path / "plan.json"),
                                     "--executor-pid", "7", "--executor-path", str(tmp_path / "executor")])
    with pytest.raises(ValueError, match="执行器"):
        args.func(args)
    assert (locations["support_dir"] / "registrations/voice.wav").exists()
    monkeypatch.setattr(control, "process_arguments", lambda _: [str(tmp_path / "executor"), "--plan", "foo"])
    with pytest.raises(ValueError, match="准备"):
        args.func(args)
    assert (locations["support_dir"] / "registrations/voice.wav").exists()


def test_barrier_waiting_starter_rechecks_lease(tmp_path):
    import threading
    started = threading.Event()
    finished = threading.Event()
    outcomes = []
    def start():
        started.set()
        try:
            with uninstall.startup_guard():
                outcomes.append("started")
        except ValueError:
            outcomes.append("refused")
        finally:
            finished.set()
    with uninstall.coordination_lock():
        thread = threading.Thread(target=start)
        thread.start()
        assert started.wait(1)
        uninstall.uninstall_marker_path().write_text("manual lease")
        assert not finished.wait(.05)
    assert finished.wait(2)
    thread.join()
    assert outcomes == ["refused"]


def test_stale_executor_lease_allows_keep_data_reinstall(tmp_path, monkeypatch):
    from micforyou import control
    monkeypatch.setattr(control, "process_arguments", lambda _: None)
    uninstall.begin_uninstall_window(executor_pid=7, executor_path="/tmp/dead/executor")
    with uninstall.startup_guard():
        assert not uninstall.uninstall_marker_path().exists()


def test_real_argv_preserves_space_paths(tmp_path):
    import subprocess
    import sys
    from micforyou.control import process_arguments
    config = tmp_path / "Application Support" / "config.json"
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(.3)",
                                "--config", str(config), "--token", "test-token"])
    try:
        argv = process_arguments(process.pid)
        assert argv[argv.index("--config") + 1] == str(config)
    finally:
        process.wait(timeout=3)
    job = {"token": "t", "process_marker": "/App Resources/bootstrap.py", "config_path": str(config)}
    assert uninstall.worker_identity(["python", "/App Resources/bootstrap.py", "setup-worker",
                                     "--config", str(config), "--token", "t"], job, config)


def test_foreign_abort_cannot_release_active_executor(monkeypatch):
    from micforyou import control
    monkeypatch.setattr(control, "process_arguments", lambda _: ["/tmp/executor"])
    uninstall.begin_uninstall_window(executor_pid=7, executor_path="/tmp/executor")
    with pytest.raises(ValueError, match="不属于"):
        uninstall.end_uninstall_window(executor_pid=8)
    assert uninstall.uninstall_in_progress()
    uninstall.end_uninstall_window(executor_pid=7)


def test_crashed_executor_does_not_unlock_while_privileged_helper_lives(monkeypatch):
    from micforyou import control
    monkeypatch.setattr(control, "process_arguments", lambda _: None)
    monkeypatch.setattr(control, "process_command", lambda _: "/bin/sh -c work=/tmp/micforyou-uninstall-test; waiting")
    uninstall.begin_uninstall_window(executor_pid=7, executor_path="/tmp/micforyou-uninstall-test/executor",
                                     companion_pids=[8])
    assert uninstall.uninstall_in_progress()
    monkeypatch.setattr(control, "process_command", lambda _: None)
    assert not uninstall.uninstall_in_progress()
