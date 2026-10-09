import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from micforyou.bridging import BridgeEngine
from micforyou.modes import SwitchableBridge


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.001)
    assert predicate()


def factory(transform=lambda block: block * 0.25):
    return BridgeEngine(transform, lambda: np.empty(0, np.float32),
                        input_bound_blocks=8, ring_maximum_frames=4096)


def commit(bridge, mode, block, timeout=2):
    with ThreadPoolExecutor() as pool:
        task = pool.submit(bridge.switch, mode, timeout)
        wait_for(lambda: bridge.snapshot()['requested_mode'] == mode)
        output = bridge.process(block, len(block))
        return task.result(), output


def test_pause_raw_is_exact_and_model_calls_stop():
    calls = []
    def transform(block):
        calls.append(1)
        return block * 0.25
    bridge = SwitchableBridge(lambda: factory(transform))
    block = np.linspace(-0.8, 0.8, 480, dtype=np.float32)
    try:
        bridge.process(block, len(block))
        wait_for(lambda: len(calls) == 1)
        result, (raw, written) = commit(bridge, 'passthrough', block)
        assert result['mode_reason'] == 'user_pause'
        assert written == len(block)
        np.testing.assert_array_equal(raw, block)
        for _ in range(20):
            np.testing.assert_array_equal(bridge.process(block, len(block))[0], block)
        assert len(calls) == 1
        assert bridge.snapshot()['processing_mode'] == 'passthrough'
    finally:
        bridge.close()


def test_late_old_result_and_state_do_not_leak_into_resume():
    entered, release = threading.Event(), threading.Event()
    generations = []
    def new_engine():
        index = len(generations)
        def transform(block):
            if index == 0:
                entered.set()
                release.wait(2)
                return np.full(len(block), 99, np.float32)
            return block * 0.25
        value = factory(transform)
        generations.append(value)
        return value
    bridge = SwitchableBridge(new_engine)
    block = np.ones(480, np.float32)
    try:
        bridge.process(block, len(block))
        assert entered.wait(1)
        _, (raw, _) = commit(bridge, 'passthrough', block)
        np.testing.assert_array_equal(raw, block)
        release.set()
        assert generations[0].worker_done.wait(1)
        _, _ = commit(bridge, 'tse', block)
        wait_for(lambda: generations[1].output_ring.available() >= len(block))
        filtered, written = bridge.process(None, len(block))
        np.testing.assert_array_equal(filtered, block * 0.25)
        assert written == len(block)
        assert len(generations) == 2
        assert not bridge.fault.is_set()
    finally:
        release.set()
        bridge.close()


def test_resume_preparation_failure_keeps_explicit_raw_audio():
    def fail():
        raise RuntimeError('cannot reset DSP')
    bridge = SwitchableBridge(fail, initial_mode='passthrough')
    block = np.ones(480, np.float32)
    try:
        with pytest.raises(RuntimeError, match='cannot reset'):
            bridge.switch('tse')
        np.testing.assert_array_equal(bridge.process(block, 480)[0], block)
        assert bridge.mode == 'passthrough'
    finally:
        bridge.close()


def test_timeout_cancels_pending_switch_without_false_success():
    bridge = SwitchableBridge(factory)
    try:
        with pytest.raises(TimeoutError, match='did not confirm'):
            bridge.switch('passthrough', timeout=0.02)
        assert bridge.mode == 'tse'
        assert bridge.snapshot()['requested_mode'] is None
    finally:
        bridge.close()


@pytest.mark.parametrize('mode', ['tse', 'passthrough'])
def test_fault_always_silences_and_rejects_mode_commands(mode):
    bridge = SwitchableBridge(factory, initial_mode=mode)
    try:
        bridge.latch_fault('selected input disappeared')
        audio, written = bridge.process(np.ones(480, np.float32), 480)
        assert written == 0
        assert not audio.any()
        with pytest.raises(RuntimeError, match='faulted'):
            bridge.switch('passthrough')
    finally:
        bridge.close()


def test_100_mode_toggles_are_serialized_and_keep_one_active_generation():
    bridge = SwitchableBridge(factory)
    block = np.ones(48, np.float32)
    try:
        for _ in range(100):
            commit(bridge, 'passthrough', block)
            assert bridge.switch('passthrough')['processing_mode'] == 'passthrough'
            commit(bridge, 'tse', block)
            assert bridge.switch('tse')['processing_mode'] == 'tse'
            assert len(bridge._retired) <= 1
        assert bridge.revision == 200
        assert not bridge.fault.is_set()
    finally:
        bridge.close()


def test_stop_rejects_a_pending_resume():
    bridge = SwitchableBridge(factory, initial_mode='passthrough')
    with ThreadPoolExecutor() as pool:
        task = pool.submit(bridge.switch, 'tse', 1)
        wait_for(lambda: bridge.snapshot()['requested_mode'] == 'tse')
        bridge.close()
        with pytest.raises(RuntimeError, match='closed'):
            task.result()
        assert bridge.snapshot()['processing_mode'] == 'none'
