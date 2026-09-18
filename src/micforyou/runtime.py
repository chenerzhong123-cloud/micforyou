"""Pure runtime-configuration helpers shared by optional experiment tools."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrtThreadSetting:
    """An ORT thread request and the exact label written to reports."""

    requested: int
    label: str
    intra_op_num_threads: int | None
    inter_op_num_threads: int | None


def ort_thread_settings(values: list[int]) -> list[OrtThreadSetting]:
    """Validate/deduplicate ORT thread requests without changing their order.

    Zero means leave ORT's thread counts unset (the runtime default). Positive
    values explicitly set intra-op threads and pin inter-op threads to one.
    """
    if not values:
        raise ValueError("at least one ORT thread setting is required")
    settings: list[OrtThreadSetting] = []
    seen: set[int] = set()
    for value in values:
        if value < 0:
            raise ValueError("ORT thread counts must be zero or positive")
        if value in seen:
            continue
        seen.add(value)
        settings.append(
            OrtThreadSetting(
                requested=value,
                label="auto" if value == 0 else str(value),
                intra_op_num_threads=None if value == 0 else value,
                inter_op_num_threads=None if value == 0 else 1,
            )
        )
    return settings
