import numpy as np
import pytest

from micforyou.audio import Device, ensure_safe_route, map_channels, resolve_device
from micforyou.evaluation import create_mixtures, si_sdr


def device(index: int, name: str, inputs: int, outputs: int) -> Device:
    return Device(index, name, 0, inputs, outputs, 48_000.0)


def test_resolve_exact_before_substring() -> None:
    items = [device(1, "USB Mic", 1, 0), device(2, "USB Mic Extended", 1, 0)]
    assert resolve_device(items, "USB Mic", "input").index == 1


def test_resolve_rejects_ambiguous_substring() -> None:
    items = [device(1, "Mic Left", 1, 0), device(2, "Mic Right", 1, 0)]
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_device(items, "Mic", "input")


def test_route_requires_physical_input_and_blackhole_output() -> None:
    physical = device(1, "Headset Microphone", 1, 0)
    blackhole = device(2, "BlackHole 2ch", 2, 2)
    ensure_safe_route(physical, blackhole)
    with pytest.raises(ValueError, match="physical input"):
        ensure_safe_route(blackhole, physical)
    with pytest.raises(ValueError, match="output must"):
        ensure_safe_route(physical, device(3, "Speakers", 0, 2))


def test_blackhole_cannot_be_selected_as_physical_input() -> None:
    from micforyou.audio import record_input

    with pytest.raises(ValueError, match="physical input"):
        record_input(device(2, "BlackHole 2ch", 2, 2), None, 0)  # type: ignore[arg-type]


def test_mono_is_mapped_to_both_blackhole_channels() -> None:
    mono = np.array([[0.25], [-0.5]], dtype=np.float32)
    stereo = map_channels(mono, 2)
    assert stereo.shape == (2, 2)
    np.testing.assert_array_equal(stereo[:, 0], mono[:, 0])
    np.testing.assert_array_equal(stereo[:, 1], mono[:, 0])


def test_si_sdr_prefers_clean_reference() -> None:
    reference = np.sin(np.linspace(0, 30, 4000)).astype(np.float32)
    noisy = reference + 0.5 * np.random.default_rng(3).normal(size=len(reference))
    assert si_sdr(reference, reference) > si_sdr(noisy, reference)
