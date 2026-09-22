#!/bin/zsh
set -euo pipefail

package_root="$(cd "$(dirname "$0")" && pwd)"
destination="${1:-$package_root/.build/MicForYou.app}"
contents="$destination/Contents"

swift build -c release --package-path "$package_root"
mkdir -p "$contents/MacOS" "$contents/Resources"
install -m 755 \
  "$package_root/.build/release/MicForYouMenuBar" \
  "$contents/MacOS/MicForYouMenuBar"
install -m 644 "$package_root/Resources/Info.plist" "$contents/Info.plist"
codesign --force --deep --sign - "$destination"
codesign --verify --deep --strict "$destination"
echo "$destination"
