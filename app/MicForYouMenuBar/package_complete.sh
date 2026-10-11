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
name="MicForYou-${version}-trial-macos-arm64"
staging="$release_root/$name"
mkdir -p "$staging"
"$1/bin/python3.12" -B "$project_root/tools/bundle/build_bundle.py" \
  --python-root "$1" --model-repo "$2" --wespeaker "$3" --app "$staging/MicForYou.app"
"$1/bin/python3.12" -B "$project_root/tools/bundle/package_docs.py" \
  --project "$project_root" --dest "$staging"
archive="$release_root/$name.app.zip"
ditto -c -k --sequesterRsrc --keepParent "$staging" "$archive"
(cd "$release_root" && shasum -a 256 "$name.app.zip" > "$name.sha256")
echo "$archive"
