#!/bin/zsh
set -euo pipefail
package_root="$(cd "$(dirname "$0")" && pwd)"
project_root="$(cd "$package_root/../.." && pwd)"
if [[ $# -lt 4 ]]; then
  echo "Usage: $0 PYTHON_ROOT MODEL_REPO WESPEAKER_PACKAGE BLACKHOLE_PKG [OUTPUT_ROOT]" >&2
  exit 2
fi
release_root="${5:-$project_root/outputs/releases/installer}"
version=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$package_root/Resources/Info.plist")
name="MicForYou-${version}-local-alpha-macos-arm64"
staging="$release_root/$name"
mkdir -p "$staging"
"$1/bin/python3.12" -B "$project_root/tools/bundle/build_bundle.py" \
  --python-root "$1" --model-repo "$2" --wespeaker "$3" --blackhole-pkg "$4" \
  --app "$staging/MicForYou.app"
"$1/bin/python3.12" -B "$project_root/tools/bundle/build_installer.py" \
  --app "$staging/MicForYou.app" --blackhole-pkg "$4" --output "$release_root/$name.pkg"
