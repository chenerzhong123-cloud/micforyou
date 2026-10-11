"""Build a relocatable local alpha bundle; never includes personal audio/models."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[2]
SOURCE_COMMIT = "2a540977a348fbaa92e623210505430e2cec608d"
WEIGHTS_HASH = "97c01b79b0cf1a5b914a4a3bc1113c1864752ebdd320f528e77a53202447fef2"
WESPEAKER_COMMIT = "8f53b6485d9f88a207bd17e7f8dba899495ec794"
BLACKHOLE_HASH = "57b540f27a3e29c37e310e01bee0fdfab76733087e47f997ef9dccf851400dcf"
BLACKHOLE_VERSION = "0.7.1"
SCRIPTS = ["run_real_tse_bridge.py", "probe_real_tse_stateful.py",
           "export_real_tse_onnx.py", "compare_torch_onnx.py",
           "benchmark_onnx_tse.py", "measure_bridge_latency.py"]


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_code(source, destination):
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", ".DS_Store"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-root", type=Path, required=True,
                        help="uv-managed standalone CPython 3.12 with requirements-bundle installed")
    parser.add_argument("--model-repo", type=Path, required=True)
    parser.add_argument("--wespeaker", type=Path, required=True,
                        help="WeSpeaker package directory at the pinned source revision")
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--blackhole-pkg", type=Path,
                        help="Authorized official BlackHole 2ch 0.7.1 installer for offline repair")
    parser.add_argument("--native-assets", type=Path,
                        default=PROJECT / "outputs/bundle-build/native",
                        help="Output of prepare_native.py")
    args = parser.parse_args()
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise SystemExit("Build on macOS arm64")
    if args.blackhole_pkg:
        if sha256(args.blackhole_pkg) != BLACKHOLE_HASH:
            raise SystemExit("Unexpected BlackHole installer hash")
        signature = subprocess.check_output(
            ["pkgutil", "--check-signature", str(args.blackhole_pkg)], text=True)
        if "Existential Audio Inc. (Q5C99V536K)" not in signature:
            raise SystemExit("Unexpected BlackHole installer signer")
    revision = subprocess.check_output(["git", "-C", str(args.model_repo),
                                       "rev-parse", "HEAD"], text=True).strip()
    if revision != SOURCE_COMMIT:
        raise SystemExit("Unexpected REAL-TSE source revision")
    direct_urls = list(args.wespeaker.parent.glob("wespeaker-*.dist-info/direct_url.json"))
    if not any(json.loads(path.read_text()).get("vcs_info", {}).get("commit_id") == WESPEAKER_COMMIT
               for path in direct_urls):
        raise SystemExit("Cannot verify pinned WeSpeaker package revision")
    model = args.model_repo / "pretrained" / "tfmap_context_causal_100"
    if sha256(model / "avg_model.pt") != WEIGHTS_HASH:
        raise SystemExit("Unexpected checkpoint hash; do not bundle it")
    if not (PROJECT / "licenses" / "MODEL_NOTICES.md").is_file():
        raise SystemExit("Missing model licensing notices")
    native_metadata = json.loads((args.native_assets / "native-assets.json").read_text())
    if sha256(args.native_assets / "libsndfile_arm64.dylib") != native_metadata["libsndfile_pre_sign_sha256"]:
        raise SystemExit("Unexpected prepared libsndfile hash")
    for name, info in native_metadata["sources"].items():
        if not name.startswith("cpython") and sha256(args.native_assets / "licenses/sources" / name) != info["sha256"]:
            raise SystemExit(f"Unexpected native source hash: {name}")
    root = args.app / "Contents" / "Resources" / "Runtime"
    if root.exists():
        raise SystemExit("Runtime already exists; use a new output App directory")
    subprocess.run([str(PROJECT / "app/MicForYouMenuBar/build_app.sh"),
                    str(args.app)], check=True)
    root.mkdir()
    shutil.copytree(args.python_root, root / "python", symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.dll",
                                                  "*.onnx", "*.wav", "*.flac", "*.m4a"))
    site = root / "python/lib/python3.12/site-packages"
    shutil.copy2(args.native_assets / "libsndfile_arm64.dylib",
                 site / "_soundfile_data/libsndfile_arm64.dylib")
    # These optional modules require an external libsox and are never used.
    for name in ("_torchaudio_sox.so", "libtorchaudio_sox.so"):
        (site / "torchaudio/lib" / name).unlink(missing_ok=True)
    # Never rely on a developer venv, Homebrew, or packages from user site.
    for item in (root / "python").rglob("*"):
        if item.is_symlink() and not item.resolve().is_relative_to(root.resolve()):
            raise SystemExit(f"External runtime symlink: {item}")
    copy_code(PROJECT / "src", root / "src")
    (root / "tools" / "inference").mkdir(parents=True)
    for name in SCRIPTS:
        shutil.copy2(PROJECT / "tools" / "inference" / name, root / "tools" / "inference" / name)
    shutil.copy2(PROJECT / "tools/bundle/bootstrap.py", root / "bootstrap.py")
    vendor = root / "vendor"
    vendor.mkdir()
    wesep = vendor / "wesep"
    wesep.mkdir()
    for part in ("models", "modules"):
        copy_code(args.model_repo / "wesep" / part, wesep / part)
    shutil.copy2(PROJECT / "tools/bundle/wesep_init.py", wesep / "__init__.py")
    speaker = vendor / "wespeaker"
    (speaker / "models").mkdir(parents=True)
    (speaker / "__init__.py").write_text(
        "# MicForYou modification: offline ECAPA-only inference subset.\n")
    shutil.copy2(args.wespeaker / "models" / "__init__.py", speaker / "models/__init__.py")
    for name in ("ecapa_tdnn.py", "pooling_layers.py"):
        shutil.copy2(args.wespeaker / "models" / name, speaker / "models" / name)
    shutil.copy2(PROJECT / "tools/bundle/speaker_model.py", speaker / "models/speaker_model.py")
    (root / "models/tfmap_context_causal_100").mkdir(parents=True)
    for name in ("avg_model.pt", "config.yaml"):
        shutil.copy2(model / name, root / "models/tfmap_context_causal_100" / name)
    copy_code(PROJECT / "licenses", root / "licenses")
    shutil.copy2(PROJECT / "LICENSE", root / "licenses/PROJECT_LICENSE.txt")
    shutil.copy2(PROJECT / "NOTICE", root / "licenses/PROJECT_NOTICE.txt")
    copy_code(args.native_assets / "licenses", root / "licenses/native")
    if args.blackhole_pkg:
        installers = args.app / "Contents/Resources/Installers"
        installers.mkdir()
        shutil.copy2(args.blackhole_pkg, installers / f"BlackHole2ch-{BLACKHOLE_VERSION}.pkg")
    version = plistlib.loads((args.app / "Contents/Info.plist").read_bytes())["CFBundleShortVersionString"]
    python = root / "python/bin/python3.12"
    metadata_code = """import importlib.metadata as m,json
print(json.dumps([{'name':d.metadata['Name'],'version':d.version,
 'license':d.metadata.get('License-Expression') or d.metadata.get('License'),
 'homepage':d.metadata.get('Home-page'),
 'license_files':[str(f) for f in d.files or [] if 'license' in str(f).lower() or 'notice' in str(f).lower()]}
 for d in m.distributions()],indent=2))"""
    manifest = {
        "schema": "micforyou/bundle/1", "version": version, "architecture": "arm64",
        "project_license": "Apache-2.0",
        "real_tse_commit": SOURCE_COMMIT, "wespeaker_commit": WESPEAKER_COMMIT,
        "model_sha256": WEIGHTS_HASH,
        "model_licenses": ["Apache-2.0 (Ke Zhang's portions)", "CC-BY-4.0 (WeSpeaker ECAPA parameters)"],
        "personal_data_included": False, "driver_included": bool(args.blackhole_pkg),
        "blackhole": {"version": BLACKHOLE_VERSION, "installer_sha256": BLACKHOLE_HASH,
                      "role": "official offline repair installer; system driver installed by product pkg",
                      "license_basis": "separate integration authorization confirmed by project owner 2026-10-09"}
                     if args.blackhole_pkg else None,
        "native_assets": native_metadata,
        "public_release_ready": False,
        "remaining_release_checks": ["Developer ID/notarization", "native dependency source compliance",
                                      "clean-device onboarding", "physical microphone/IME 30-minute test"],
        "dependencies": json.loads(subprocess.check_output([str(python), "-B", "-c", metadata_code], text=True))}
    (root / "bundle-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    # Package metadata/license files and Python LICENSES remain in the runtime.
    for filename in ("MODEL_NOTICES.md", "Apache-2.0.txt", "CC-BY-4.0.html"):
        if not (root / "licenses" / filename).is_file():
            raise SystemExit(f"Missing license: {filename}")
    # Sign nested Mach-O files inside-out. The local alpha is ad-hoc signed.
    native = []
    for item in root.rglob("*"):
        if item.is_file() and not item.is_symlink():
            with item.open("rb") as stream:
                magic = stream.read(4)
            if magic in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xcf"):
                native.append(item)
    for item in sorted(native, key=lambda p: len(p.parts), reverse=True):
        subprocess.run(["codesign", "--force", "--sign", "-", str(item)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["codesign", "--force", "--sign", "-", str(args.app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(args.app)], check=True)
    print(args.app)


if __name__ == "__main__":
    main()
