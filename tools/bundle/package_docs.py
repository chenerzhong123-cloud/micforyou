"""Convert the repository guides into the documents shipped beside a delivery.

Both packaging entry points use this module so the ZIP staging layout
(package_complete.sh) and the pkg sidecar layout (build_installer.py) cannot
drift apart. Sources are plain markdown; only a fixed set of link rewrites is
applied — no document-generation pipeline is involved.

Layouts:
- zip staging: guides sit next to the MicForYou.app directory, so license
  links point at the contained app (relative path).
- pkg sidecar: guides sit next to the installer and license links use the
  fixed install location (/Applications/...).

README is not shipped; its navigation links are rewritten to the project page.
"""
from __future__ import annotations
import argparse
import re
from pathlib import Path

REPO_URL = "https://github.com/chenerzhong123-cloud/micforyou"
ZIP_APP_PREFIX = "MicForYou.app/Contents/Resources/Runtime"
PKG_APP_PREFIX = "/Applications/MicForYou.app/Contents/Resources/Runtime"

# Output name -> repository source, per delivery.
SOURCES = {
    "INSTALL.zh.md": "docs/INSTALL.md",
    "INSTALL.en.md": "docs/INSTALL.en.md",
    "USAGE.zh.md": "docs/USAGE.md",
    "USAGE.en.md": "docs/USAGE.en.md",
}

# Repository-internal navigation targets -> delivered equivalents. Language
# switching must work under the renamed files, and the unshipped README links
# become the absolute project page.
NAV_MAP = {
    "INSTALL.md": "INSTALL.zh.md",
    "USAGE.md": "USAGE.zh.md",
    "../README.md": REPO_URL,
    "../README.en.md": REPO_URL,
}

LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)\s]*)?\)")


def rewrite(text: str, app_prefix: str) -> str:
    def replace(match: re.Match) -> str:
        target = match.group(1)
        if target.startswith(("http://", "https://", "mailto:")):
            return match.group(0)
        if target in NAV_MAP:
            return f"]({NAV_MAP[target]})"
        if target == "../LICENSE":
            return f"]({app_prefix}/licenses/PROJECT_LICENSE.txt)"
        if target == "../NOTICE":
            return f"]({app_prefix}/licenses/PROJECT_NOTICE.txt)"
        if target.startswith("../licenses/"):
            return f"]({app_prefix}/licenses/{target[len('../licenses/'):]})"
        if target.startswith("../"):
            raise SystemExit(f"Unhandled repository-relative link: {target}")
        return match.group(0)

    return LINK.sub(replace, text)


def write_delivery_docs(project: Path, destination: Path, app_prefix: str) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    written = []
    for name, source in SOURCES.items():
        text = (project / source).read_text(encoding="utf-8")
        path = destination / name
        path.write_text(rewrite(text, app_prefix), encoding="utf-8")
        written.append(str(path))
    # Every remaining relative link must resolve inside the delivery; absolute
    # links (pkg install locations, the project page) are layout-dependent and
    # are not checked here.
    for name in SOURCES:
        for match in LINK.finditer((destination / name).read_text(encoding="utf-8")):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "/")):
                continue
            if not (destination / target).resolve().exists():
                raise SystemExit(f"Broken relative link in {name}: {target}")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--app-prefix", default=ZIP_APP_PREFIX,
                        help="app location the license links should point at "
                             "(zip staging: relative, pkg sidecar: /Applications/...)")
    args = parser.parse_args()
    for path in write_delivery_docs(args.project, args.dest, args.app_prefix):
        print(path)


if __name__ == "__main__":
    main()
