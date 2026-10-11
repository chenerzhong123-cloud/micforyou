"""Check the real live main with synthetic duplex callbacks, never a microphone.

Run from the controller environment:
  uv run python tools/verification/verify_pause_passthrough.py --config CONFIG.json
Optional --runtime-python PATH verifies a newly installed model environment.
Only synthetic signals and numeric reports are created; private enrollment stays local.
"""
from __future__ import annotations
import argparse
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

def synthetic_worker():
    import sys, threading, time, json
    from pathlib import Path
    import numpy as np
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "inference"))
    import run_real_tse_bridge as live
    from micforyou.audio import Device
    from micforyou.modes import SwitchableBridge
    raw_blocks = 0
    raw_mismatches = 0
    stream_opens = 0
    underflows = 0
    original_process = SwitchableBridge.process

    def measured_process(self, block, frames):
        nonlocal raw_blocks, raw_mismatches
        result = original_process(self, block, frames)
        if self.mode == 'passthrough' and not self.fault.is_set() and block is not None:
            raw_blocks += 1
            raw_mismatches += int(not np.array_equal(result[0], block))
        return result
    SwitchableBridge.process = measured_process
    input_name = sys.argv[sys.argv.index('--input-device') + 1]
    devices = [Device(0, input_name, 0, 1, 0, 48000), Device(1, 'BlackHole 2ch', 0, 2, 2, 48000)]
    live.list_devices = lambda: devices
    live.list_devices_fresh = lambda: devices

    class SyntheticStream:
        latency = (0.01, 0.01)
        def __init__(self, **kwargs):
            self.callback = kwargs['callback']
            self.frames = kwargs['blocksize']
            self.running = threading.Event()
        def __enter__(self):
            nonlocal stream_opens
            stream_opens += 1
            self.running.set()
            def run():
                position = 0
                while self.running.is_set():
                    started = time.monotonic()
                    t = (np.arange(self.frames) + position) / 48000
                    block = (0.1*np.sin(2*np.pi*220*t)).astype(np.float32)[:,None]
                    output = np.zeros((self.frames, 2), np.float32)
                    self.callback(block, output, self.frames, None, None)
                    assert np.array_equal(output[:,0], output[:,1])
                    position += self.frames
                    time.sleep(max(0, 0.01 - (time.monotonic()-started)))
            self.thread = threading.Thread(target=run, daemon=True)
            self.thread.start()
            return self
        def __exit__(self, *args):
            self.running.clear()
            self.thread.join(1)

    live.sd.Stream = SyntheticStream
    live.sd.sleep = lambda duration: time.sleep(duration / 1000)
    try:
        live.main()
    finally:
        result = Path(sys.argv[sys.argv.index('--result') + 1])
        result.with_suffix('.synthetic.json').write_text(json.dumps({
            'raw_blocks':raw_blocks,'raw_mismatches':raw_mismatches,'stream_opens':stream_opens,
            'actual_microphone_opened':False, 'ime_used':False,
        }))


def main():
    from micforyou.product import load_config, default_config_path, build_bridge_command
    from micforyou.control import start_managed_process, switch_managed_mode, stop_managed_process, owns_process, load_state
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--runtime-python", type=Path)
    parser.add_argument("--result-dir", type=Path)
    parser.add_argument("--cycles", type=int, default=5)
    parser.add_argument("--startup-timeout", type=float, default=180)
    args = parser.parse_args()
    if args.cycles < 1 or args.startup_timeout <= 0:
        parser.error("cycles and startup timeout must be positive")
    root = Path(__file__).resolve().parents[2]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    work = args.result_dir or root / "outputs" / f"pause-validation-{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    for filename in ("health.json", "result.json", "result.synthetic.json"):
        (work / filename).unlink(missing_ok=True)
    config = load_config(args.config)
    if args.runtime_python:
        config = replace(config, runtime_python=args.runtime_python.absolute())
    command = build_bridge_command(config, 0, work/'result.json', work/'health.json')
    command[1] = str(Path(__file__).resolve())
    command.insert(2, "--synthetic-worker")
    state_path=work/'state.json'
    state = start_managed_process(command, config_path=args.config, state_path=state_path,
        result_path=work/'result.json', log_path=work/'run.log',health_path=work/'health.json', cwd=root, process_marker=command[1])
    checks=[]
    try:
        deadline=time.monotonic()+args.startup_timeout
        while time.monotonic()<deadline:
            if (work/'health.json').exists():
                health=json.loads((work/'health.json').read_text())
                if health['status']=='RUNNING': break
                if health['status']=='FAULT':
                    raise RuntimeError(health['detail'])
            time.sleep(0.1)
        else: raise RuntimeError('synthetic live route did not become ready')
        time.sleep(1.5)
        for _ in range(args.cycles):
            before=time.monotonic()
            raw=switch_managed_mode(state_path=state_path,mode='passthrough',timeout_seconds=5)
            pause_ms=(time.monotonic()-before)*1000
            assert raw.pid==state.pid
            time.sleep(0.5)
            before=time.monotonic()
            filtered=switch_managed_mode(state_path=state_path,mode='tse',timeout_seconds=5)
            resume_ms=(time.monotonic()-before)*1000
            assert filtered.pid==state.pid
            time.sleep(0.5)
            checks.append({'pause_ack_ms':pause_ms,'resume_ack_ms':resume_ms,'same_pid':True})
        switch_managed_mode(state_path=state_path,mode='passthrough')
        time.sleep(0.2)
    finally:
        current=load_state(state_path)
        if current and owns_process(current):
            stop_managed_process(state_path=state_path,final_status='STOPPED',timeout_seconds=15)
    result=json.loads((work/'result.json').read_text())
    metrics=json.loads((work/'result.synthetic.json').read_text())
    assert result['status']=='STOPPED',result['errors']
    assert not result['errors'],result['errors']
    assert metrics['raw_blocks']>0 and metrics['raw_mismatches']==0 and metrics['stream_opens']==1,metrics
    summary={'status':'PASS','context':'real ONNX model and live main; synthetic duplex callbacks; no microphone or IME',
        'checks':checks,'callback_count':result['callback_count'],'model_call_count':result['model_call_count'],
        'faults':result['errors'],**metrics}
    (work/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__ == "__main__":
    if "--synthetic-worker" in sys.argv:
        sys.argv.remove("--synthetic-worker")
        synthetic_worker()
    else:
        main()
