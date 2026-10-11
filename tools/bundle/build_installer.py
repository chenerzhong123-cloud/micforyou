"""Wrap a complete signed App and the authorized official driver in one product pkg."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from build_bundle import BLACKHOLE_HASH, BLACKHOLE_VERSION, PROJECT, sha256


def run(*args):
    subprocess.run(list(map(str, args)), check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--blackhole-pkg', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Output exists; choose a fresh release directory')
    if sha256(args.blackhole_pkg) != BLACKHOLE_HASH:
        raise SystemExit('Unexpected official driver package hash')
    plist = plistlib.loads((args.app / 'Contents/Info.plist').read_bytes())
    version = plist['CFBundleShortVersionString']
    bundled_driver = args.app / f'Contents/Resources/Installers/BlackHole2ch-{BLACKHOLE_VERSION}.pkg'
    if not bundled_driver.is_file() or sha256(bundled_driver) != BLACKHOLE_HASH:
        raise SystemExit('Complete App must include the verified offline driver installer')
    run('codesign', '--verify', '--deep', '--strict', args.app)
    run('pkgutil', '--check-signature', args.blackhole_pkg)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='micforyou-installer-') as work:
        stage = Path(work)
        packages = stage / 'Packages'
        packages.mkdir()
        expanded = stage / 'Official'
        run('pkgutil', '--expand', args.blackhole_pkg, expanded)
        original = expanded / 'BlackHole.pkg'
        driver_info = ET.parse(original / 'PackageInfo').getroot()
        if (driver_info.attrib['identifier'] != 'audio.existential.BlackHole2ch'
                or driver_info.attrib['version'] != BLACKHOLE_VERSION
                or driver_info.attrib['install-location'] != '/Library/Audio/Plug-Ins/HAL'):
            raise SystemExit('Unexpected official component metadata')
        # Flatten only the original component; Payload/Bom/metadata/scripts stay unchanged.
        run('pkgutil', '--flatten', original, packages / 'BlackHole.pkg')
        root = stage / 'AppRoot'
        root.mkdir()
        shutil.copytree(args.app, root / 'MicForYou.app', symlinks=True)
        components = stage / 'components.plist'
        run('pkgbuild', '--analyze', '--root', root, components)
        metadata = plistlib.loads(components.read_bytes())
        for item in metadata:
            item['BundleIsRelocatable'] = False
            item['BundleIsVersionChecked'] = True
            item['BundleHasStrictIdentifier'] = True
        components.write_bytes(plistlib.dumps(metadata))
        run('pkgbuild', '--root', root, '--component-plist', components,
            '--identifier', 'com.micforyou.complete', '--version', version,
            '--install-location', '/Applications', '--ownership', 'recommended',
            '--scripts', PROJECT / 'tools/installer/scripts', packages / 'MicForYou.pkg')
        resources = stage / 'Resources'
        shutil.copytree(PROJECT / 'tools/installer/resources', resources)
        # Show all model/driver terms; the source texts are also retained inside the App.
        notices = ['MODEL_NOTICES.md', 'Apache-2.0.txt', 'BLACKHOLE_NOTICES.md', 'BlackHole-LICENSE.txt']
        license_text = (PROJECT / 'LICENSE').read_text() + '\n\n' + (PROJECT / 'NOTICE').read_text()
        license_text += '\n\n' + '\n\n'.join((PROJECT / 'licenses' / name).read_text() for name in notices)
        license_text += '\n\nCC BY 4.0: https://creativecommons.org/licenses/by/4.0/legalcode.en\n'
        (resources / 'license.txt').write_text(license_text)
        dist = stage / 'Distribution.xml'
        dist.write_text((PROJECT / 'tools/installer/Distribution.xml').read_text().replace('@VERSION@', version))
        run('productbuild', '--distribution', dist, '--package-path', packages,
            '--resources', resources, args.output)
        component_hashes = {str(p.relative_to(original)): sha256(p)
                            for p in original.rglob('*') if p.is_file()}
    digest = sha256(args.output)
    args.output.with_suffix('.sha256').write_text(f'{digest}  {args.output.name}\n')
    manifest = {'schema': 'micforyou/installer/1', 'version': version,
                'installer': args.output.name, 'sha256': digest,
                'size_bytes': args.output.stat().st_size,
                'app_location': '/Applications/MicForYou.app',
                'driver_location': '/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver',
                'blackhole_official_pkg_sha256': BLACKHOLE_HASH,
                'blackhole_component_files': component_hashes,
                'signing': 'combined pkg unsigned; App ad-hoc signed; official repair pkg signed/notarized',
                'personal_data_included': False, 'public_release_ready': False}
    args.output.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for source, name in [('BUNDLED_APP.md', 'INSTALL.zh.md'), ('BUNDLED_APP.en.md', 'INSTALL.en.md')]:
        guide = (PROJECT / 'docs' / source).read_text().replace(
            '../licenses/', '/Applications/MicForYou.app/Contents/Resources/Runtime/licenses/')
        guide = guide.replace('../LICENSE', '/Applications/MicForYou.app/Contents/Resources/Runtime/licenses/PROJECT_LICENSE.txt')
        guide = guide.replace('../NOTICE', '/Applications/MicForYou.app/Contents/Resources/Runtime/licenses/PROJECT_NOTICE.txt')
        (args.output.parent / name).write_text(guide)
    print(args.output)


if __name__ == '__main__':
    main()
