# FFmpeg binary, corresponding source and build instructions

SCENE App v0.3 includes the unmodified **BtbN win64 GPL static** FFmpeg
build `n9.0.2-42-gd7643a0fe3-20261101`. The nonfree variant is not used.

| Item | Pinned value |
| --- | --- |
| Upstream binary release | [autobuild-2026-11-01-12-49](https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-2026-11-01-12-49) |
| Upstream ZIP | `ffmpeg-n9.0.2-42-gd7643a0fe3-win64-gpl-9.0.zip` |
| ZIP SHA-256 | `ce92c2ee8a90fbe3da3e8a2bd510f4ebc0e838d4cf433371095ac2179f95e834` |
| `ffmpeg.exe` SHA-256 | `238eb9e809e1b2e80b9ebdb4d12f382edf1cb77ccc44543ec24cdf26dad00643` |
| FFmpeg source commit | [`d7643a0fe3f4f65516c302eba045ba884faed015`](https://github.com/FFmpeg/FFmpeg/tree/d7643a0fe3f4f65516c302eba045ba884faed015) |
| Build recipes and dependency revisions | [`5ece62897c650b863c1ddda7b6964845344aef2d`](https://github.com/BtbN/FFmpeg-Builds/tree/5ece62897c650b863c1ddda7b6964845344aef2d) |
| License | GPL version 3 or later; copy: `vendor/ffmpeg-LICENSE.txt` |

The versioned project release mirrors the original upstream binary ZIP so that
upstream daily-release pruning does not prevent rebuilding. `tools/fetch_ffmpeg.py`
checks the archive hash and the extracted binary hash, tries the
[SCENE App v0.3 mirror](https://github.com/hyjys/SCENE-App/releases/download/v0.3/ffmpeg-n9.0.2-42-gd7643a0fe3-win64-gpl-9.0.zip)
if the upstream URL is unavailable, and refuses to overwrite a different existing binary.

## Accessing the source

The following source material is supplied without charge beside the binary
release and in the project source distribution:

- `vendor/sources/FFmpeg-d7643a0fe3f4f65516c302eba045ba884faed015.tar.gz`:
  the FFmpeg source matching the binary, including its GPL license.
- `vendor/sources/FFmpeg-Builds-5ece62897c650b863c1ddda7b6964845344aef2d.tar.gz`:
  the matching BtbN build scripts, dependency source retrieval commands, patches,
  Dockerfiles and target settings. SHA-256:
  `3399050a6fb3d93fffb6e6a565889ff02c483fe7b8aea09e95a777043309b1af`.
- `vendor/sources/ffmpeg-dependency-sources.json`: a machine-readable index of
  source repository URLs and pinned revisions declared by the build recipes.
  It lists every recipe, including packages disabled in this particular variant.
- `vendor/ffmpeg.json`: checksums and source/binary provenance.
- `vendor/ffmpeg-README.txt`: the matching upstream build instructions.

The recipes' `scripts.d/` files identify each dependency's source and version;
`ffbuild_dockerdl` describes retrieval and preparation. They include, for example,
[x264 at `0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee`](https://code.videolan.org/videolan/x264/-/tree/0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee)
and [LAME SVN revision 7113](https://svn.code.sf.net/p/lame/svn/trunk/lame/?p=7113).
The complete retrieval commands, additional dependencies, patches and build
settings are provided in the source recipe archive. `download.sh` populates the
source download cache from those identified upstream sources.

Equivalent direct source archives:

- [FFmpeg source archive](https://github.com/FFmpeg/FFmpeg/archive/d7643a0fe3f4f65516c302eba045ba884faed015.tar.gz)
- [Build recipe archive](https://github.com/BtbN/FFmpeg-Builds/archive/5ece62897c650b863c1ddda7b6964845344aef2d.tar.gz)

## Building

Use a Linux environment with Bash and Docker and extract the pinned build recipe
archive above. The target is `win64`, variant `gpl`, and addin `9.0`:

```bash
./makeimage.sh win64 gpl 9.0
```

The upstream `9.0` addin follows the moving `release/9.0` branch. Before running
the final build, pin the FFmpeg checkout to the commit matching this release by
adding `git checkout d7643a0fe3f4f65516c302eba045ba884faed015` immediately after
the `cd ffmpeg` line in the generated-build-script block in `build.sh`:

```bash
sed -i '/^    cd ffmpeg$/a\    git checkout d7643a0fe3f4f65516c302eba045ba884faed015' build.sh
./build.sh win64 gpl 9.0
```

The output is in `artifacts/`. The source recipe contains the cross compiler and
dependency configurations; `ffmpeg.exe -buildconf` reports the shipped binary's
configure options. This documents how to rebuild the same source and features;
byte-for-byte identical output is not claimed because the upstream toolchain
images and build timestamp are not fixed by these commands.
