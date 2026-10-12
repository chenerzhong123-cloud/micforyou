"""Persisted product configuration and command construction."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import os
import re


CONFIG_SCHEMA = "micforyou/product-config/1"


def default_config_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "MicForYou" / "config.json"


@dataclass(frozen=True)
class ProductConfig:
    input_device: str
    model_repo: Path
    model_dir: Path
    enrollment: Path
    onnx_model: Path
    runtime_python: Path
    project_root: Path
    output_device: str = "BlackHole 2ch"
    fault_policy: str = "silence"
    route_change_policy: str = "continue_tse"
    frames_per_chunk: int = 8
    onnx_threads: int = 1
    prefill_ms: float = 100.0
    queue_ms: float = 500.0
    enrollment_seconds: float = 6.0
    auto_recoveries: int = 2
    recovery_window_seconds: float = 300.0
    route_reconnect_timeout_seconds: float = 120.0
    bundle_managed: bool = False
    # Name of the attempts subdirectory (under the enrollment folder) whose
    # verdict.json authorizes this config. Absent in registrations made by
    # older builds, which kept the verdict at the folder root.
    verdict_ref: str | None = None

    def validate(self) -> None:
        if self.fault_policy not in {"silence", "passthrough"}:
            raise ValueError("fault_policy must be silence or passthrough")
        if self.route_change_policy not in {"continue_tse", "silence_on_route_change"}:
            raise ValueError(
                "route_change_policy must be continue_tse or silence_on_route_change"
            )
        if self.frames_per_chunk <= 0:
            raise ValueError("frames_per_chunk must be positive")
        if self.onnx_threads < 0:
            raise ValueError("onnx_threads must be zero or positive")
        if not 0 <= self.prefill_ms <= self.queue_ms:
            raise ValueError("prefill_ms must be between zero and queue_ms")
        if self.enrollment_seconds <= 0:
            raise ValueError("enrollment_seconds must be positive")
        if self.auto_recoveries < 0 or self.recovery_window_seconds <= 0:
            raise ValueError("invalid recovery budget")
        if self.route_reconnect_timeout_seconds <= 0:
            raise ValueError("route_reconnect_timeout_seconds must be positive")
        if self.verdict_ref is not None and not re.fullmatch(
                r"[0-9A-Za-z_-]{6,64}", self.verdict_ref):
            raise ValueError("verdict_ref must be a plain attempt directory name")

    def to_dict(self) -> dict:
        payload = asdict(self)
        for key in (
            "model_repo",
            "model_dir",
            "enrollment",
            "onnx_model",
            "runtime_python",
            "project_root",
        ):
            payload[key] = str(payload[key])
        return {"schema": CONFIG_SCHEMA, **payload}

    @classmethod
    def from_dict(cls, payload: dict) -> "ProductConfig":
        if payload.get("schema") != CONFIG_SCHEMA:
            raise ValueError("unsupported MicForYou config schema")
        values = dict(payload)
        values.pop("schema")
        for key in (
            "model_repo",
            "model_dir",
            "enrollment",
            "onnx_model",
            "runtime_python",
            "project_root",
        ):
            values[key] = Path(values[key])
        config = cls(**values)
        config.validate()
        return config


def save_config(config: ProductConfig, destination: Path) -> None:
    config.validate()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def load_config(source: Path) -> ProductConfig:
    if not source.exists():
        raise ValueError(f"configuration not found: {source}; run configure first")
    config = ProductConfig.from_dict(json.loads(source.read_text(encoding="utf-8")))
    root = os.environ.get("MICFORYOU_BUNDLE_ROOT")
    if config.bundle_managed and root:
        root = Path(root)
        config = replace(config, project_root=root, model_repo=root / "vendor",
                         model_dir=root / "models" / "tfmap_context_causal_100",
                         runtime_python=root / "python" / "bin" / "python3.12")
    return config


def required_paths(config: ProductConfig) -> dict[str, Path]:
    return {
        "runtime_python": config.runtime_python,
        "project_root": config.project_root,
        "bridge_script": config.project_root / "tools" / "inference" / "run_real_tse_bridge.py",
        "model_repo": config.model_repo,
        "model_dir": config.model_dir,
        "checkpoint": config.model_dir / "avg_model.pt",
        "enrollment": config.enrollment,
        "onnx_model": config.onnx_model,
    }


def build_bridge_command(
    config: ProductConfig,
    duration: float,
    result: Path,
    health_file: Path | None = None,
) -> list[str]:
    config.validate()
    command = [
        str(config.runtime_python),
        str(config.project_root / "tools" / "inference" / "run_real_tse_bridge.py"),
        "--repo",
        str(config.model_repo),
        "--model-dir",
        str(config.model_dir),
        "--enrollment",
        str(config.enrollment),
        "--enrollment-seconds",
        str(config.enrollment_seconds),
        "--input-device",
        config.input_device,
        "--output-device",
        config.output_device,
        "--backend",
        "onnx",
        "--onnx",
        str(config.onnx_model),
        "--onnx-threads",
        str(config.onnx_threads),
        "--frames-per-chunk",
        str(config.frames_per_chunk),
        "--prefill-ms",
        str(config.prefill_ms),
        "--queue-ms",
        str(config.queue_ms),
        "--fault-policy",
        config.fault_policy,
        "--route-change-policy",
        config.route_change_policy,
        "--route-reconnect-timeout-seconds",
        str(config.route_reconnect_timeout_seconds),
        "--auto-recoveries",
        str(config.auto_recoveries),
        "--recovery-window-seconds",
        str(config.recovery_window_seconds),
        "--duration",
        str(duration),
        "--result",
        str(result),
    ]
    if health_file is not None:
        command.extend(["--health-file", str(health_file)])
    return command
