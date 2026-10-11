#!/bin/zsh
set -euo pipefail

package_root="$(cd "$(dirname "$0")" && pwd)"
project_root="$(cd "$package_root/../.." && pwd)"
version=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$package_root/Resources/Info.plist")
architecture="$(uname -m)"
release_name="MicForYou-${version}-alpha-macos-${architecture}"
release_root="${1:-$project_root/outputs/releases}"
staging="$release_root/$release_name"
mkdir -p "$staging"
"$package_root/build_app.sh" "$staging/MicForYou.app"
cat > "$staging/INSTALL.txt" <<'GUIDE'
MicForYou — Experimental Alpha

中文：此包只有菜单栏 App，不含 Python 环境、REAL-TSE 权重、声音注册或 BlackHole。
先按仓库的安装指南完成本地设置，再把 MicForYou.app 放入 ~/Applications。
暂停过滤会继续输出原音；结束才释放麦克风。退出界面会保留后台音频。
当前为 ad-hoc 签名，未经过 Developer ID 签名或 Apple 公证。

English: This package contains the menu-bar controller only. It does not include
Python runtimes, REAL-TSE weights, voice enrollment, or BlackHole. Complete local
setup first, then move MicForYou.app to ~/Applications. Pause forwards raw audio;
End releases the microphone. Quitting the interface preserves background audio.
The app is ad-hoc signed, without Developer ID signing or Apple notarization.

https://github.com/chenerzhong123-cloud/micforyou
Chinese: docs/DEVELOPMENT.md
English: docs/DEVELOPMENT.en.md
GUIDE
archive="$release_root/$release_name.app.zip"
ditto -c -k --sequesterRsrc --keepParent "$staging" "$archive"
(cd "$release_root" && shasum -a 256 "$release_name.app.zip" > "$release_name.sha256")
echo "$archive"
