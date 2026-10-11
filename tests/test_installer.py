"""Installer safety checks without administrator rights or touching CoreAudio."""
from pathlib import Path
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('version,binary,selected', [
    (None, False, True), ('0.7.0', True, True), ('0.7.1', True, False),
    ('0.8.0', True, False), ('0.7.1', False, True),
])
def test_driver_install_selection(version, binary, selected):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required for Installer JS behavior check')
    tree = ET.parse(ROOT / 'tools/installer/Distribution.xml')
    script = tree.findtext('script')
    # Exercise the real selection function with documented Installer JS objects.
    harness = '''const vm = require('node:vm');
const input = JSON.parse(process.argv[1]);
let context = {system: {
  files: {plistAtPath: () => input.version ? {
    CFBundleIdentifier: 'audio.existential.BlackHole2ch',
    CFBundleShortVersionString: input.version} : null,
    fileExistsAtPath: (path) => path.endsWith('/MacOS/BlackHole') && input.binary},
  compareVersions: (a,b) => {
    const left=a.split('.').map(Number), right=b.split('.').map(Number);
    for(let i=0;i<Math.max(left.length,right.length);i++) {
      if ((left[i]||0)!==(right[i]||0)) return (left[i]||0)>(right[i]||0)?1:-1;
    } return 0;
  }
}};
vm.createContext(context); vm.runInContext(input.script, context);
process.stdout.write(JSON.stringify(context.needsDriver()));'''
    output = subprocess.check_output([node, '-e', harness, json.dumps({
        'version': version, 'binary': binary, 'script': script})], text=True)
    assert json.loads(output) is selected
    choice = tree.find("choice[@id='driver']")
    assert choice.attrib['selected'] == 'needsDriver()'


@pytest.mark.parametrize('comm,args,target,expected', [
    ('', '', '/', 0),
    ('11 /Applications/MicForYou.app/Contents/MacOS/MicForYouMenuBar', '', '/', 1),
    ('11 /Applications/Path With Spaces/MicForYouMenuBar', '', '/', 1),
    ('11 /Applications/Path With Spaces/python3.12',
     '/Applications/Path With Spaces/python3.12 /app/micforyou/bootstrap.py setup-worker', '/', 1),
    ('11 /env/bin/python3.12', '/env/bin/python3.12 /app/tools/inference/run_real_tse_bridge.py', '/', 1),
    ('11 /env/bin/python3.12', '/env/bin/python3.12 unrelated.py', '/', 0),
    ('', '', '/Volumes/Other', 1),
])
def test_preinstall_refuses_active_processes(tmp_path, comm, args, target, expected):
    fake_ps = tmp_path / 'ps'
    # Fixtures stay in data files, never interpolate them into executable shell text.
    (tmp_path / 'comm').write_text(comm + '\n')
    (tmp_path / 'args').write_text(args + '\n')
    fake_ps.write_text('#!/bin/sh\nbase=$(dirname "$0")\n'
                       'if [ "$1" = -axo ]; then cat "$base/comm"; else cat "$base/args"; fi\n')
    fake_ps.chmod(0o755)
    script = (ROOT / 'tools/installer/scripts/preinstall').read_text()
    script = script.replace('/bin/ps', f'"{fake_ps}"')
    path = tmp_path / 'preinstall'
    path.write_text(script)
    result = subprocess.run(['/bin/sh', str(path), 'package', '/Applications', target], capture_output=True)
    assert result.returncode == expected
