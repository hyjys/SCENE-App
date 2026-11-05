# Third-party source and redistribution information — v0.3

The application code is GPL-3.0-or-later, copyright (C) 2026 hyjys.
Project source, build scripts, font assets and tests:
https://github.com/hyjys/SCENE-App/tree/v0.3
Release archives (binaries, project source and dependency source):
https://github.com/hyjys/SCENE-App/releases/tag/v0.3

External components retain their own copyright and license. Each portable ZIP
includes LICENSE, licenses/, and the original Nanum Gothic OFL notice. The
manifest records the exact component versions and distributed file hashes.
`SCENE-App-v0.3-source.zip` includes the application sources, build scripts, tests,
font assets, dependency manifests, and matching FFmpeg source/build-recipe archives.
The separately supplied Python source ZIP below contains the pinned PyPI sources.
No third-party license is replaced by the application's GPL notice.

## Python packages

`third-party-python-sources-v0.3.zip` on the same release contains the original
source distributions for the versions below, with an upstream URL and verified
SHA-256 for each file. `tools/package_dependency_sources.py` recreates this ZIP.
Use each PyPI release page's "Download files" / source distribution for an
independent copy. Build this application using README.md and requirements-lock.txt.

| Component | Version | License | Exact release/source |
| --- | --- | --- | --- |
| CustomTkinter | 6.0.0 | MIT | https://pypi.org/project/customtkinter/6.0.0/#files |
| darkdetect | 0.8.0 | BSD-3-Clause | https://pypi.org/project/darkdetect/0.8.0/#files |
| packaging | 26.3 | Apache-2.0 or BSD-2-Clause | https://pypi.org/project/packaging/26.3/#files |
| yt-dlp | 2026.10.26 | Unlicense | https://pypi.org/project/yt-dlp/2026.10.26/#files |
| yt-dlp-ejs | 0.8.0 | Unlicense; bundled JS: MIT/ISC | https://pypi.org/project/yt-dlp-ejs/0.8.0/#files |
| Brotli | 1.2.1 | MIT | https://pypi.org/project/brotli/1.2.1/#files |
| certifi | 2026.10.23 | MPL-2.0 | https://pypi.org/project/certifi/2026.10.23/#files |
| charset-normalizer | 3.5.2 | MIT | https://pypi.org/project/charset-normalizer/3.5.2/#files |
| idna | 3.20 | BSD-3-Clause | https://pypi.org/project/idna/3.20/#files |
| Mutagen | 1.48.1 | GPL-2.0-or-later | https://pypi.org/project/mutagen/1.48.1/#files |
| PyCryptodome (Cryptodome namespace) | 3.24.1 | BSD/public domain | https://pypi.org/project/pycryptodomex/3.24.1/#files |
| requests | 2.34.2 | Apache-2.0 | https://pypi.org/project/requests/2.34.2/#files |
| urllib3 | 2.8.0 | MIT | https://pypi.org/project/urllib3/2.8.0/#files |
| websockets | 17.4 | BSD-3-Clause | https://pypi.org/project/websockets/17.4/#files |
| PyInstaller bootloader | 6.22.3 | GPL with bootloader exception | https://pypi.org/project/pyinstaller/6.22.3/#files |

## Python and Tcl/Tk

The Windows executable embeds unmodified CPython 3.15.0 and its bundled Tcl/Tk 9.0.4.
The Python license (including incorporated third-party notices) is included as
licenses/PYTHON-LICENSE.txt; Tcl/Tk notices are under licenses/ as available in
the Python installation. CPython source and Windows build instructions:
https://www.python.org/downloads/release/python-3150/
https://github.com/python/cpython/tree/v3.15.0
https://github.com/python/cpython/blob/v3.15.0/PCbuild/readme.txt
Tcl/Tk dependency versions, sources and build scripts:
https://github.com/python/cpython/blob/v3.15.0/PCbuild/get_externals.bat
https://github.com/python/cpython-source-deps

## Deno

Deno 2.9.8 Windows x64, unmodified, MIT. Original LICENSE.md is distributed as
licenses/DENO-LICENSE.txt. Exact binary URL and SHA-256 are in vendor/runtime.json.
Source: https://github.com/denoland/deno/tree/v2.9.8
Source archive: https://github.com/denoland/deno/archive/refs/tags/v2.9.8.tar.gz
Build instructions: https://docs.deno.com/runtime/contributing/building_from_source/
Fetch/rebuild integration: tools/fetch_runtime.py and build.ps1.

## Nanum Gothic

Unmodified NanumGothic-Regular.ttf and NanumGothic-Bold.ttf from the user-supplied
Nanum_Gothic.zip. SIL Open Font License 1.1 and the original copyright notice are
in assets/fonts/OFL.txt. ExtraBold is not used. Font sources are included in the
project's source archive; upstream: https://github.com/google/fonts/tree/main/ofl/nanumgothic

## FFmpeg

The portable ZIP includes an unmodified GPL FFmpeg build. Exact binary/source
revisions, source code, build recipes (including external-library revisions),
checksums and mirror instructions are documented in docs/FFMPEG-SOURCES.md.
The build recipes are also provided with the source and binary release.
See vendor/ffmpeg.json and tools/fetch_ffmpeg.py for reproducible download.
