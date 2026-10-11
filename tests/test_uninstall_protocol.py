"""Real Python JSON -> production Swift UI and executor types (read-only fixtures)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path
import pytest
from micforyou import uninstall


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("swiftc"), reason="native macOS protocol check")
def test_real_python_plan_swift_ui_executor(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    home = tmp_path / "home"
    support = uninstall.support_dir(home)
    support.mkdir(parents=True)
    (support / "voice.wav").write_bytes(b"fixture")
    # Do not enumerate the current user's control files or installed app.
    monkeypatch.setattr(uninstall, "tmp_dir", lambda: Path("/tmp") / f"micforyou-{__import__('os').getuid()}")
    monkeypatch.setattr(uninstall, "read_bundle_id", lambda _: None)
    class Result:
        returncode = 1
    paths = []
    for index, (data, driver) in enumerate([(True, False), (False, False), (True, True)]):
        plan = uninstall.build_plan(remove_user_data=data, remove_driver=driver, home=home,
                                    app_path=home / "absent.app", receipt_runner=lambda *a, **kw: Result())
        plan["targets"] = [item for item in plan["targets"] if item["kind"] != "tmp_dir"]
        path = tmp_path / f"plan-{index}.json"
        path.write_text(json.dumps(plan))
        paths.append(path)
    executable = tmp_path / "protocol-check"
    sources = [root / "app/MicForYouMenuBar/Sources/MicForYouMenuBar/Models.swift",
               root / "app/MicForYouMenuBar/Uninstall/UninstallExecutor.swift",
               root / "app/MicForYouMenuBar/Uninstall/UninstallProtocolCheck.swift"]
    result = subprocess.run(["swiftc", "-parse-as-library", "-D", "UNINSTALL_TESTING", *map(str, sources),
                             "-o", str(executable)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(executable), str(home), *map(str, paths)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("protocol PASS") == 3
    assert "native failure/retry/summary PASS" in result.stdout
