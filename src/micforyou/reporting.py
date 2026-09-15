"""Host and run reporting helpers shared by benchmark and latency tools."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import platform
import subprocess
from typing import Any

import numpy as np


def _sysctl(name: str) -> str | None:
    try:
        value = subprocess.run(
            ["sysctl", "-n", name],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        return value or None
    except (OSError, subprocess.SubprocessError):
        return None


def _power_source() -> str | None:
    try:
        text = subprocess.run(
            ["pmset", "-g", "ps"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    if "AC Power" in text:
        return "AC"
    if "Battery" in text:
        return "Battery"
    return None


def collect_system_info(extras: dict[str, Any] | None = None) -> dict[str, Any]:
    """Best-effort host snapshot; performance context, never audio content."""
    info: dict[str, Any] = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "system_version": platform.version(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "loadavg_at_start": list(os.getloadavg()),
        "cpu_brand": _sysctl("machdep.cpu.brand_string"),
        "hw_model": _sysctl("hw.model"),
        "perflevel0_cores": _sysctl("hw.perflevel0.logicalcpu"),
        "perflevel1_cores": _sysctl("hw.perflevel1.logicalcpu"),
        "power_source": _power_source(),
    }
    if extras:
        info.update(extras)
    return {key: value for key, value in info.items() if value is not None}


def percentile_summary(values: list[float] | np.ndarray) -> dict[str, float | int]:
    """p50/p95/max/mean over milliseconds-style samples."""
    array = np.asarray(values, dtype=np.float64)
    if not len(array):
        return {"count": 0}
    return {
        "count": int(len(array)),
        "p50": float(np.percentile(array, 50)),
        "p95": float(np.percentile(array, 95)),
        "max": float(array.max()),
        "mean": float(array.mean()),
    }
