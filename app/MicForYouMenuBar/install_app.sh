#!/bin/zsh
set -euo pipefail

package_root="$(cd "$(dirname "$0")" && pwd)"
destination="$HOME/Applications/MicForYou.app"

mkdir -p "$HOME/Applications"
"$package_root/build_app.sh" "$destination"
open "$destination"
echo "Installed and opened: $destination"
