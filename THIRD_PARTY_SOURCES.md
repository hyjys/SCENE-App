# Third-party source and redistribution information — v0.4

The application code is GPL-3.0-or-later, copyright (C) 2026 hyjys.
Project source, build scripts, font assets and tests:
https://github.com/hyjys/SCENE-App/tree/v0.4
Release archives (binaries, project source and dependency source):
https://github.com/hyjys/SCENE-App/releases/tag/v0.4

External components retain their own copyright and license. Each portable ZIP
includes LICENSE, licenses/, and the original Nanum Gothic OFL notice. The
manifest records the exact component versions and distributed file hashes.
`SCENE-App-v0.4-source.zip` includes the application sources, build scripts, tests,
font assets, dependency manifests, and matching FFmpeg source/build-recipe archives.
The separately supplied Python source ZIP below contains the pinned PyPI sources.
No third-party license is replaced by the application's GPL notice.

## Python packages

`third-party-python-sources-v0.4.zip` on the same release contains the original
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
| python-docx | 1.2.0 | MIT | https://pypi.org/project/python-docx/1.2.0/#files |
| lxml | 6.1.3 | BSD-3-Clause; bundled XML libraries retain their notices | https://pypi.org/project/lxml/6.1.3/#files |
| typing_extensions | 4.16.0 | PSF-2.0 | https://pypi.org/project/typing_extensions/4.16.0/#files |
| PyMuPDF | 1.28.2 | AGPL-3.0; commercial alternative not used | https://pypi.org/project/PyMuPDF/1.28.2/#files |
| Pillow | 13.0.0 | MIT-CMU; bundled image libraries retain their notices | https://pypi.org/project/Pillow/13.0.0/#files |
| TkinterWeb | 4.25.5 | MIT | https://pypi.org/project/tkinterweb/4.25.5/#files |
| tkinterweb-tkhtml | 2.3.0 | MIT; included native components retain their notices | https://pypi.org/project/tkinterweb-tkhtml/2.3.0/#files |
| tkinterweb-tkhtml-extras | 1.5.0 | MIT; included native components retain their notices | https://pypi.org/project/tkinterweb-tkhtml-extras/1.5.0/#files |
| PythonMonkey | 1.4.1 | MIT; incorporated PSF/Node/MPL notices | https://pypi.org/project/pythonmonkey/1.4.1/#files |
| pminit | 1.4.1 | MIT | https://pypi.org/project/pminit/1.4.1/#files |
| aiohttp | 3.14.5 | Apache-2.0 AND MIT | https://pypi.org/project/aiohttp/3.14.5/#files |
| aiohappyeyeballs | 2.7.1 | PSF-2.0 | https://pypi.org/project/aiohappyeyeballs/2.7.1/#files |
| aiosignal | 1.4.0 | Apache-2.0 | https://pypi.org/project/aiosignal/1.4.0/#files |
| attrs | 26.1.0 | MIT | https://pypi.org/project/attrs/26.1.0/#files |
| frozenlist | 1.8.0 | Apache-2.0 | https://pypi.org/project/frozenlist/1.8.0/#files |
| multidict | 7.2.1 | Apache-2.0 | https://pypi.org/project/multidict/7.2.1/#files |
| propcache | 0.5.4 | Apache-2.0 | https://pypi.org/project/propcache/0.5.4/#files |
| pyreadline3 | 3.5.6 | BSD | https://pypi.org/project/pyreadline3/3.5.6/#files |
| yarl | 1.25.1 | Apache-2.0 | https://pypi.org/project/yarl/1.25.1/#files |
| PyInstaller bootloader | 6.22.3 | GPL with bootloader exception | https://pypi.org/project/pyinstaller/6.22.3/#files |

The source archive is generated when `build.ps1 -IncludeDependencySources` or
the source-packaging tool is run. Publish its output beside the binaries. A
PyPI source distribution alone does not necessarily contain the sources of
every native library in its wheels; the native-source references below are
also required when preparing a complete corresponding-source release.

## PDF viewer and MuPDF

`scene_script.py` contains a maintained adaptation of the CustomTkinter +
PyMuPDF rendering approach from [CTkPDFViewer](https://github.com/Akascape/CTkPDFViewer),
copyright (c) 2023 Akash Bora, MIT. It adds lazy single-page rendering, main-thread
Tk widget updates, proportional pages, rectangle selections and sidecar notes.
The upstream MIT notice is retained in the module and
`docs/CTkPDFViewer-LICENSE.txt`. The reference was the upstream `main` source;
an exact upstream commit was not recorded, so no commit-level provenance is claimed.

PyMuPDF 1.28.2 and the installed MuPDF engine report version 1.28.2. They are used
under AGPL-3.0, not a proprietary Artifex license. Their AGPL notice is in the
installed distribution's COPYING and is collected with the package licenses.
[Upstream licensing](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright)
describes the AGPL/commercial alternatives. GPLv3 section 13 in this project's
LICENSE permits combining GPLv3 and AGPLv3 works; it preserves the licenses of
the respective parts and applies AGPLv3's network-interaction requirements to
the combination. This does not replace PyMuPDF's AGPL with GPL.

Corresponding sources and build entry points:

- [PyMuPDF 1.28.2 source](https://github.com/pymupdf/PyMuPDF/tree/1.28.2)
  and its [setup.py](https://github.com/pymupdf/PyMuPDF/blob/1.28.2/setup.py).
- [MuPDF 1.28.2 source archive](https://mupdf.com/downloads/archive/mupdf-1.28.2-source.tar.gz),
  including its third-party source material and notices.
- [MuPDF build documentation](https://mupdf.readthedocs.io/en/latest/quick-start.html).

The PyMuPDF build script fetches its MuPDF source separately at build time.
Keep that archive and the relevant build instructions with the release's
corresponding sources; do not describe the PyPI-only archive as a complete
MuPDF source archive. Byte-for-byte reconstruction of upstream wheels is not claimed.

## TkinterWeb, PythonMonkey and SpiderMonkey

The application uses TkinterWeb's `recommended,javascript` extras. PythonMonkey
1.4.1 and pminit 1.4.1 provide JavaScript support. Their installed MIT license
also retains incorporated CPython, Node.js and Mozilla notices. The PythonMonkey
wheel includes `mozjs-136a1.dll`, Mozilla SpiderMonkey, under MPL-2.0 with its
own incorporated notices. It is not covered solely by PythonMonkey's MIT license.

- [PythonMonkey v1.4.1 source and build files](https://github.com/Distributive-Network/PythonMonkey/tree/v1.4.1).
- [Upstream license notices](https://github.com/Distributive-Network/PythonMonkey/blob/v1.4.1/LICENSE).
- The tag's [mozcentral.version](https://github.com/Distributive-Network/PythonMonkey/blob/v1.4.1/mozcentral.version)
  declares Mozilla revision `6bca861985ba51920c1cacc21986af01c51bd690`.
  This is an upstream build reference, not independent verification that the
  distributed wheel's DLL was compiled from precisely that revision.
- [Mozilla source at the declared revision](https://hg.mozilla.org/mozilla-central/file/6bca861985ba51920c1cacc21986af01c51bd690/)
  and [SpiderMonkey build instructions](https://firefox-source-docs.mozilla.org/js/build.html).
- [Mozilla Public License 2.0](https://www.mozilla.org/en-US/MPL/2.0/).
- [TkinterWeb sources](https://github.com/Andereoo/TkinterWeb)
  and [JavaScript documentation](https://tkinterweb.readthedocs.io/en/latest/javascript.html).

Provide the matching SpiderMonkey source/build material and preserve native
Tkhtml/extras notices when publishing the bundled wheels. Consult the pinned
package sources for their native dependency and build provenance; a DLL name
alone is not sufficient to identify an exact source revision.

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

