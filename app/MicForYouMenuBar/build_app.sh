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

# C01 is the approved artwork. Derive every icon size from the same master.
iconset="$package_root/.build/AppIcon.iconset"
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$package_root/Resources/AppIcon.png" \
    --out "$iconset/icon_${size}x${size}.png" >/dev/null
  retina_size=$((size * 2))
  sips -z "$retina_size" "$retina_size" "$package_root/Resources/AppIcon.png" \
    --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil --convert icns --output "$contents/Resources/AppIcon.icns" "$iconset"

codesign --force --deep --sign - "$destination"
codesign --verify --deep --strict "$destination"
echo "$destination"
