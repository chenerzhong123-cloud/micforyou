"""Prepare native notices/sources and a WAV-capable, codec-free libsndfile.

Build-time only: nothing here runs on an end user's machine.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

ASSETS = {
    "libsndfile-1.2.0.tar.xz": (
        "https://github.com/libsndfile/libsndfile/releases/download/1.2.0/libsndfile-1.2.0.tar.xz",
        "0e30e7072f83dc84863e2e55f299175c7e04a5902ae79cfb99d4249ee8f6d60a"),
    "soxr-0.5.0.post1.tar.gz": (
        "https://files.pythonhosted.org/packages/02/c0/4429bf9b3be10e749149e286aa5c53775399ec62891c6b970456c6dca325/soxr-0.5.0.post1.tar.gz",
        "7092b9f3e8a416044e1fa138c8172520757179763b85dc53aa9504f4813cff73"),
    "ml_dtypes-0.5.4.tar.gz": (
        "https://files.pythonhosted.org/packages/0e/4a/c27b42ed9b1c7d13d9ba8b6905dece787d6259152f2309338aed29b2447b/ml_dtypes-0.5.4.tar.gz",
        "8ab06a50fb9bf9666dd0fe5dfb4676fa2b0ac0f31ecff72a6c3af8e22c063453"),
    "cpython-3.12.13-20260602-full.tar.zst": (
        "https://github.com/astral-sh/python-build-standalone/releases/download/20260602/cpython-3.12.13%2B20260602-aarch64-apple-darwin-pgo%2Blto-full.tar.zst",
        "04b8c175a01e60ff081088294ac486e814bc621902517bf1a29ff65c5d075695"),
}
FLAGS = ["-DCMAKE_POLICY_VERSION_MINIMUM=3.5", "-DBUILD_SHARED_LIBS=ON",
         "-DBUILD_TESTING=OFF", "-DBUILD_PROGRAMS=OFF", "-DBUILD_EXAMPLES=OFF",
         "-DENABLE_EXTERNAL_LIBS=OFF", "-DENABLE_MPEG=OFF",
         "-DCMAKE_OSX_ARCHITECTURES=arm64", "-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0"]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--cmake", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.sources.mkdir(parents=True, exist_ok=True)
    for name, (url, checksum) in ASSETS.items():
        path = args.sources / name
        if not path.exists():
            subprocess.run(["curl", "-fL", "--retry", "2", url, "-o", str(path)], check=True)
        if digest(path) != checksum:
            raise SystemExit(f"Source checksum mismatch: {name}")
    source = args.sources / "libsndfile-1.2.0"
    if not source.exists():
        with tarfile.open(args.sources / "libsndfile-1.2.0.tar.xz") as archive:
            archive.extractall(args.sources, filter="data")
    build = args.sources.parent / "libsndfile-build"
    subprocess.run([str(args.cmake), "-S", str(source), "-B", str(build), *FLAGS], check=True)
    subprocess.run([str(args.cmake), "--build", str(build), "-j4"], check=True)
    args.output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(build / "libsndfile.1.0.35.dylib", args.output / "libsndfile_arm64.dylib")
    licenses = args.output / "licenses"
    sources = licenses / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    for name in ASSETS:
        if not name.startswith("cpython"):
            shutil.copy2(args.sources / name, sources / name)
    subprocess.run(["tar", "-xf", str(args.sources / "cpython-3.12.13-20260602-full.tar.zst"),
                    "-C", str(licenses), "--strip-components", "1",
                    "python/licenses", "python/PYTHON.json"], check=True)
    urllib.request.urlretrieve(
        "https://raw.githubusercontent.com/llvm/llvm-project/llvmorg-17.0.6/LICENSE.TXT",
        licenses / "LLVM-LICENSE.txt")
    shutil.copy2(source / "COPYING", licenses / "libsndfile-COPYING.txt")
    shutil.copy2(Path(__file__), licenses / "prepare_native.py")
    metadata = {"sources": {name: {"url": url, "sha256": checksum}
                            for name, (url, checksum) in ASSETS.items()},
                "libsndfile_build_flags": FLAGS,
                "libsndfile_pre_sign_sha256": digest(args.output / "libsndfile_arm64.dylib"),
                "libsndfile_modifications": "Unmodified 1.2.0 sources; external codecs and MPEG disabled",
                "llvm_license_url": "https://raw.githubusercontent.com/llvm/llvm-project/llvmorg-17.0.6/LICENSE.TXT"}
    (args.output / "native-assets.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
