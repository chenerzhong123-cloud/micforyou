#!/bin/zsh
set -euo pipefail
# Inputs: portable Python root, pinned REAL-TSE checkout, pinned WeSpeaker package.
package_root="$(cd "$(dirname "$0")" && pwd)"
project_root="$(cd "$package_root/../.." && pwd)"
if [[ $# -lt 3 ]]; then
  echo "Usage: $0 PYTHON_ROOT MODEL_REPO WESPEAKER_PACKAGE [OUTPUT_ROOT]" >&2
  exit 2
fi
release_root="${4:-$project_root/outputs/releases}"
version=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$package_root/Resources/Info.plist")
name="MicForYou-${version}-local-alpha-macos-arm64"
staging="$release_root/$name"
mkdir -p "$staging"
"$1/bin/python3.12" -B "$project_root/tools/bundle/build_bundle.py" \
  --python-root "$1" --model-repo "$2" --wespeaker "$3" --app "$staging/MicForYou.app"
"$1/bin/python3.12" -B - "$project_root" "$staging" <<'PY'
from pathlib import Path
import sys
project, staging = map(Path, sys.argv[1:])
for source, destination in [("INSTALL.md", "INSTALL.zh.md"), ("INSTALL.en.md", "INSTALL.en.md")]:
    text = (project / "docs" / source).read_text()
    text = text.replace("../licenses/", "MicForYou.app/Contents/Resources/Runtime/licenses/")
    text = text.replace("../LICENSE", "MicForYou.app/Contents/Resources/Runtime/licenses/PROJECT_LICENSE.txt")
    text = text.replace("../NOTICE", "MicForYou.app/Contents/Resources/Runtime/licenses/PROJECT_NOTICE.txt")
    (staging / destination).write_text(text)
PY
archive="$release_root/$name.app.zip"
ditto -c -k --sequesterRsrc --keepParent "$staging" "$archive"
(cd "$release_root" && shasum -a 256 "$name.app.zip" > "$name.sha256")
echo "$archive"
