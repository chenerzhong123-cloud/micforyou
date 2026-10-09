from argparse import Namespace
from pathlib import Path
from dataclasses import replace

from micforyou.audio import Device
from micforyou.cli import command_configure, command_set_policy, build_parser
from micforyou.product import load_config


def test_configure_persists_then_policy_update_is_not_overwritten(tmp_path, monkeypatch, capsys):
    import micforyou.cli as cli
    devices = [Device(0, 'Test Mic', 0, 1, 0, 48000), Device(1, 'BlackHole 2ch', 0, 2, 2, 48000)]
    monkeypatch.setattr(cli, 'list_devices', lambda: devices)
    args = build_parser().parse_args([
        'configure', '--config', str(tmp_path / 'config.json'),
        '--input-device', 'Test Mic', '--model-repo', str(tmp_path / 'model-repo'),
        '--model-dir', str(tmp_path / 'model'), '--enrollment', str(tmp_path / 'voice.wav'),
        '--onnx', str(tmp_path / 'voice.onnx'), '--runtime-python', str(tmp_path / 'runtime/bin/python'),
        '--project-root', str(tmp_path),
    ])
    command_configure(args)
    original = load_config(args.config)
    assert original.input_device == 'Test Mic'
    command_set_policy(Namespace(config=args.config, fault_policy='passthrough'))
    assert load_config(args.config) == replace(original, fault_policy='passthrough')
    command_set_policy(Namespace(config=args.config, fault_policy='silence'))
    assert load_config(args.config).fault_policy == 'silence'
