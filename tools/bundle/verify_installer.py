"""Read-only product package verification. Never invokes an installation."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import plistlib
import subprocess
import xml.etree.ElementTree as ET

from build_bundle import BLACKHOLE_HASH, PROJECT, WEIGHTS_HASH, sha256


def run(*args):
    return subprocess.check_output(list(map(str, args)), text=True, stderr=subprocess.STDOUT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pkg', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True, help='Fresh directory for extracted inspection data')
    parser.add_argument('--reuse', action='store_true', help='Reuse a previous extraction of this same package')
    parser.add_argument('--checks-dir', type=Path, default=PROJECT / 'outputs/installer-build',
                        help='Directory holding bundle-check and standalone-check built from app/MicForYouMenuBar/Checks')
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=args.reuse)
    manifest = json.loads(args.pkg.with_suffix('.manifest.json').read_text())
    assert sha256(args.pkg) == manifest['sha256']
    raw, full = args.work / 'raw', args.work / 'full'
    if not args.reuse:
        run('pkgutil', '--expand', args.pkg, raw)
        run('pkgutil', '--expand-full', args.pkg, full)
        (args.work / 'extracted-sha256.txt').write_text(manifest['sha256'])
    else:
        assert (args.work / 'extracted-sha256.txt').read_text() == manifest['sha256']
    driver = raw / 'BlackHole.pkg'
    for name, digest in manifest['blackhole_component_files'].items():
        assert sha256(driver / name) == digest, name
    app_info = ET.parse(raw / 'MicForYou.pkg/PackageInfo').getroot()
    assert app_info.attrib['install-location'] == '/Applications'
    assert app_info.attrib['identifier'] == 'com.micforyou.complete'
    assert app_info.attrib['version'] == manifest['version']
    assert app_info.attrib['relocatable'] == 'false'
    assert not list(app_info.find('relocate'))
    assert sha256(raw / 'MicForYou.pkg/Scripts/preinstall') == sha256(PROJECT / 'tools/installer/scripts/preinstall')
    app = full / 'MicForYou.pkg/Payload/MicForYou.app'
    runtime = app / 'Contents/Resources/Runtime'
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    assert info['CFBundleShortVersionString'] == manifest['version']
    # The bundle manifest must record the same build identity the performance
    # verdicts bind to; a missing build field would silently stop verdict
    # invalidation between builds of the same version.
    bundle_manifest = json.loads((runtime / 'bundle-manifest.json').read_text())
    assert bundle_manifest['build'] == str(info['CFBundleVersion']), \
        'bundle-manifest build identity missing or mismatched'
    assert sha256(runtime / 'models/tfmap_context_causal_100/avg_model.pt') == WEIGHTS_HASH
    repair = app / 'Contents/Resources/Installers/BlackHole2ch-0.7.1.pkg'
    assert sha256(repair) == BLACKHOLE_HASH
    assert all(not p.is_symlink() or p.resolve().is_relative_to(app.resolve()) for p in app.rglob('*'))
    unexpected = [str(p) for p in app.rglob('*') if p.suffix in ('.pyc', '.wav', '.flac', '.m4a', '.onnx', '.dll')]
    assert not unexpected, unexpected
    sig = run('codesign', '--verify', '--deep', '--strict', app)
    driver_bundle = full / 'BlackHole.pkg/Payload/BlackHole2ch.driver'
    driver_sig = run('codesign', '--verify', '--strict', driver_bundle)
    official_sig = run('pkgutil', '--check-signature', repair)
    assert 'Existential Audio Inc. (Q5C99V536K)' in official_sig
    assert 'trusted by the Apple notary service' in official_sig
    choices_text = run('/usr/sbin/installer', '-pkg', args.pkg.resolve(), '-target', '/', '-showChoicesXML')
    # This is only a query. It does not execute preinstall or change the target.
    choices = plistlib.loads(choices_text.encode())
    def flatten(items):
        for choice in items:
            yield choice
            yield from flatten(choice.get('childItems', []))
    selected = {choice['choiceIdentifier']: choice['choiceIsSelected'] for choice in flatten(choices)}
    assert selected['app'] == 1
    (args.work / 'choices.xml').write_text(choices_text)
    executor = app / 'Contents/Resources/UninstallExecutor'
    assert executor.is_file(), 'missing uninstall executor'
    with executor.open('rb') as stream:
        assert stream.read(4) in (b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe'), 'executor not Mach-O'
    run(executor, '--self-check')
    for name, check in [('bundle-check', app), ('standalone-check', app)]:
        binary = args.checks_dir / name
        if not binary.is_file():
            raise SystemExit(f'Missing check binary: {binary}; build it from app/MicForYouMenuBar/Checks')
        run(binary, check)
    run('codesign', '--verify', '--deep', '--strict', app)
    report = dict(manifest, result='PASS',
                  checks=['product checksum', 'official component byte identity', 'fixed /Applications install',
                          'nonrelocatable App', 'preinstall script identity', 'model checkpoint hash',
                          'bundle build identity recorded and consistent',
                          'offline repair pkg hash/signature/notarization', 'App and driver signatures',
                          'no external symlinks or personal model/audio/cache files',
                          'Installer read-only choices query', 'C01 icon', 'Swift bundled CLI first-use status',
                          'native uninstall executor present and self-checked',
                          'App signature intact after bundled execution'],
                  host_selected_choices=selected,
                  extracted_app=str(app.resolve()),
                  not_run=['administrator installation', 'restart', 'clean-device voice enrollment',
                           'real microphone/IME acceptance', 'Developer ID signing/notarization'])
    (args.work / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
