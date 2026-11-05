"""Fetch the pinned BtbN Windows FFmpeg build, checking both SHA-256 hashes.

Existing ffmpeg.exe files are verified and never silently overwritten. This
downloads the binary directly from the upstream builder, with a versioned
project-release mirror as fallback. ffmpeg.json records source provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "vendor" / "ffmpeg.json"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_binary(path: Path, manifest: dict) -> None:
    if path.stat().st_size != manifest["binary_bytes"]:
        raise RuntimeError(f"FFmpeg size mismatch; leaving existing file unchanged: {path}")
    actual = digest(path)
    if actual != manifest["binary_sha256"]:
        raise RuntimeError(f"FFmpeg SHA-256 mismatch ({actual}); leaving file unchanged: {path}")


def fetch(destination: Path, manifest: dict, *, verify_only: bool = False) -> None:
    if destination.exists():
        verify_binary(destination, manifest)
        print(f"Verified FFmpeg {manifest['version']}: {destination}", flush=True)
        return
    if verify_only:
        raise FileNotFoundError(f"FFmpeg is missing: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ffmpeg-download-", dir=destination.parent) as temporary:
        temporary_root = Path(temporary)
        archive_path = temporary_root / "ffmpeg.zip"
        print(f"Downloading FFmpeg {manifest['version']} from its upstream builder...", flush=True)
        urls = [manifest["archive_url"]]
        if manifest.get("archive_fallback_url"):
            urls.append(manifest["archive_fallback_url"])
        for index, url in enumerate(urls):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "SCENE-App-v0.3"})
                with urllib.request.urlopen(request, timeout=60) as response, archive_path.open("wb") as output:
                    shutil.copyfileobj(response, output, length=1024 * 1024)
                actual = digest(archive_path)
                if actual != manifest["archive_sha256"]:
                    raise RuntimeError(f"FFmpeg archive SHA-256 mismatch: {actual}")
                break
            except (OSError, urllib.error.URLError):
                if index == len(urls) - 1:
                    raise
                print("Upstream archive unavailable; trying the versioned release mirror...", flush=True)
        binary_path = temporary_root / "ffmpeg.exe"
        with zipfile.ZipFile(archive_path) as archive:
            with archive.open(manifest["archive_member"]) as source, binary_path.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
        verify_binary(binary_path, manifest)
        # Do not overwrite a file created by another process during the download.
        if destination.exists():
            verify_binary(destination, manifest)
        else:
            os.rename(binary_path, destination)
        print(f"Verified and installed FFmpeg {manifest['version']}: {destination}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "ffmpeg.exe")
    parser.add_argument("--verify-only", action="store_true", help="Verify without downloading")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    fetch(args.output.resolve(), manifest, verify_only=args.verify_only)


if __name__ == "__main__":
    main()
