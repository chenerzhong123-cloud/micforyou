# Native runtime notices and replacement instructions

These third-party components retain their own licenses. MicForYou does not
restrict modification, replacement or reverse engineering needed to exercise
rights granted by their licenses. No endorsement is implied.

## libsndfile 1.2.0

Copyright Erik de Castro Lopo and contributors. LGPL-2.1-or-later.
The SoundFile wheel's codec-rich binary is replaced with a shared library built
from unmodified libsndfile 1.2.0 sources, with optional external codecs and MPEG
disabled. WAV enrollment is supported; MP3/FLAC/Vorbis/Opus support is not used.
The complete source archive and COPYING are included in `native/sources` and
`native/libsndfile-COPYING.txt`.

Build with CMake on macOS arm64 using `native/prepare_native.py`; exact configure
flags, source URLs and SHA-256 values are in `bundle-manifest.json`.
The dynamic library may be replaced at
`Runtime/python/lib/python3.12/site-packages/_soundfile_data/libsndfile_arm64.dylib`.
Use an ABI-compatible libsndfile 1.x arm64 library for replacement.

## soxr 0.5.0.post1 / libsoxr

Python binding copyright Myungchul Keum and contributors, LGPL-2.1-or-later.
Embedded libsoxr copyright Rob Sykes and contributors, LGPL-2.1-or-later;
PFFFT has its own retained permissive notice. Exact notices remain in
`Runtime/python/lib/python3.12/site-packages/soxr-0.5.0.post1.dist-info/licenses`.
The full source distribution, including libsoxr and build scripts, is in
`native/sources/soxr-0.5.0.post1.tar.gz`.
To modify libsoxr, unpack that archive, modify its `libsoxr` sources, build the
Python extension with the upstream `pyproject.toml`, and replace the resulting
arm64 CPython 3.12 extension in the runtime's `site-packages/soxr` directory.

## ml_dtypes 0.5.4 / Eigen

ml_dtypes is Apache-2.0; its bundled Eigen code is MPL-2.0. The full source
distribution including Eigen headers is in `native/sources/ml_dtypes-0.5.4.tar.gz`.
Its original notices and full MPL text remain in
`Runtime/python/lib/python3.12/site-packages/ml_dtypes-0.5.4.dist-info/licenses`.
Upstream source: https://github.com/jax-ml/ml_dtypes

## CPython standalone build and remaining wheels

CPython 3.12.13 build 20260602 comes from python-build-standalone. Its build
metadata and original native dependency notices are copied from the matching
full archive into `native/PYTHON.json` and `native/licenses`.
The archive URL and verified SHA-256 are recorded in `bundle-manifest.json`.
CPython's LICENSE is also retained in the Python standard library.

Original wheel LICENSE/NOTICE files remain with each installed distribution;
the bundle manifest inventories them. `native/LLVM-LICENSE.txt` also retains
Apache-2.0 with LLVM exceptions for LLVM runtime components. Optional Windows
PortAudio DLLs and unused Torchaudio SoX modules are excluded from this macOS app.

After replacing native components in this ad-hoc signed local alpha, re-sign
the modified Mach-O libraries and then the app with `codesign --force --sign -`.
The complete builder signs libraries inside-out and verifies the final app.
This is a local rebuild procedure, not an Apple notarization procedure.

These supplied sources/notices address the identified native obligations.
A final distribution review of all actual bundled binaries remains part of
public release acceptance; the local alpha is not marked public-release-ready.
