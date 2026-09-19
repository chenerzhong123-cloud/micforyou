import json
from pathlib import Path

import pytest

from micforyou.product import (
    CONFIG_SCHEMA,
    ProductConfig,
    build_bridge_command,
    load_config,
    save_config,
)


def config(tmp_path: Path, **changes) -> ProductConfig:
    values = {
        "input_device": "MacBook Air Microphone",
        "model_repo": tmp_path / "repo",
        "model_dir": tmp_path / "model",
        "enrollment": tmp_path / "enrollment.wav",
        "onnx_model": tmp_path / "personalized.onnx",
        "runtime_python": tmp_path / "python",
        "project_root": tmp_path / "project",
    }
    values.update(changes)
    return ProductConfig(**values)


def test_config_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    original = config(tmp_path, fault_policy="passthrough")

    save_config(original, path)

    assert load_config(path) == original
    assert json.loads(path.read_text())["schema"] == CONFIG_SCHEMA


def test_config_rejects_invalid_fault_policy(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        config(tmp_path, fault_policy="guess").validate()


def test_bridge_command_contains_explicit_safe_runtime_contract(tmp_path: Path) -> None:
    command = build_bridge_command(config(tmp_path), 0, tmp_path / "result.json")

    assert command[0] == str(tmp_path / "python")
    assert command[1] == str(tmp_path / "project/experiments/run_real_tse_bridge.py")
    assert command[command.index("--backend") + 1] == "onnx"
    assert command[command.index("--fault-policy") + 1] == "silence"
    assert command[command.index("--duration") + 1] == "0"
