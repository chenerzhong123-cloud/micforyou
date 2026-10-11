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
        {"status": "RUNNING", "pid": 4242, "token": "t"}))
    calls = {"signals": 0}

    def reader(pid):
        return None if calls["signals"] else "/env/bin/python bootstrap.py setup-worker"

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
        {"status": "RUNNING", "pid": 7, "token": "t"}))

    def reader(pid):
        return "/env/bin/python bootstrap.py setup-worker"

    ticks = iter([0.0, 0.0, 100.0])
    report = uninstall.stop_all_tasks(
        config, command_reader=reader, signal_sender=lambda pid: None,
        sleeper=lambda _s: None, clock=lambda: next(ticks))
    assert report["worker"]["exited"] is False
    assert report["all_stopped"] is False
