"""Stage the pinned FluidSynth runtime and the bundled FluidR3 soundfont."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
MANIFEST = VENDOR / "fluidsynth.json"


def verify_file(path: Path, expected: dict) -> None:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != expected["sha256"]:
        raise RuntimeError(f"{path} SHA-256 mismatch: {digest}")


def download_archive(manifest: dict) -> zipfile.ZipFile:
    print(f"Downloading FluidSynth {manifest['version']} for Windows x64...", flush=True)
    request = urllib.request.Request(
        manifest["archive_url"], headers={"User-Agent": "SCENE-App-build"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(manifest["archive_bytes"] + 1)
    if len(data) != manifest["archive_bytes"]:
        raise RuntimeError(f"FluidSynth archive size mismatch: {len(data)} bytes")
    digest = hashlib.sha256(data).hexdigest()
    if digest != manifest["archive_sha256"]:
        raise RuntimeError(f"FluidSynth archive SHA-256 mismatch: {digest}")
    return zipfile.ZipFile(io.BytesIO(data))


def fetch(destination: Path, manifest: dict, *, verify_only: bool = False) -> None:
    missing = {}
    for name, expected in manifest["files"].items():
        path = destination / name
        if path.exists() or verify_only:
            verify_file(path, expected)
        else:
            missing[name] = expected

    if missing:
        destination.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="fluidsynth-", dir=destination.parent) as temporary:
            staging = Path(temporary)
            binaries = {name: info for name, info in missing.items() if "archive_member" in info}
            if binaries:
                with download_archive(manifest) as archive:
                    for name, expected in binaries.items():
                        with (
                            archive.open(expected["archive_member"]) as source,
                            (staging / name).open("wb") as output,
                        ):
                            shutil.copyfileobj(source, output)
            for name, expected in missing.items():
                if "bundled_source" in expected:
                    shutil.copyfile(VENDOR / expected["bundled_source"], staging / name)
                verify_file(staging / name, expected)
            for name, expected in missing.items():
                path = destination / name
                try:
                    os.rename(staging / name, path)
                except FileExistsError:
                    verify_file(path, expected)

    print(f"Verified FluidSynth {manifest['version']} and FluidR3 GM: {destination}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=VENDOR / "fluidsynth")
    parser.add_argument("--verify-only", action="store_true", help="Verify without downloading")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    fetch(args.output.resolve(), manifest, verify_only=args.verify_only)


if __name__ == "__main__":
    main()
