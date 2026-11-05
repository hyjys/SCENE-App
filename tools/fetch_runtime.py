"""Fetch the pinned official Deno binary for the portable one-file build."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
VERSION = "2.9.8"
ASSET = "deno-x86_64-pc-windows-msvc.zip"
ARCHIVE_SHA256 = "cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf"
URL = f"https://github.com/denoland/deno/releases/download/v{VERSION}/{ASSET}"


def main() -> None:
    VENDOR.mkdir(exist_ok=True)
    binary = VENDOR / "deno.exe"
    manifest_path = VENDOR / "runtime.json"
    if binary.is_file() and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (manifest.get("version") == VERSION
                and manifest.get("archive_sha256") == ARCHIVE_SHA256
                and hashlib.sha256(binary.read_bytes()).hexdigest() == manifest.get("binary_sha256")
                and (VENDOR / "DENO-LICENSE.txt").is_file()):
            print(f"Verified existing Deno {VERSION}.")
            return

    print(f"Downloading official Deno {VERSION} for Windows x64...", flush=True)
    request = urllib.request.Request(URL, headers={"User-Agent": "scene-app-build"})
    with urllib.request.urlopen(request, timeout=60) as response:
        archive = response.read()
    digest = hashlib.sha256(archive).hexdigest()
    if digest != ARCHIVE_SHA256:
        raise RuntimeError(f"Deno archive SHA-256 mismatch: {digest}")
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        executable = zipped.read("deno.exe")
    binary.write_bytes(executable)

    license_url = f"https://raw.githubusercontent.com/denoland/deno/v{VERSION}/LICENSE.md"
    with urllib.request.urlopen(license_url, timeout=30) as response:
        license_text = response.read().decode("utf-8")
    (VENDOR / "DENO-LICENSE.txt").write_text(license_text, encoding="utf-8")
    manifest_path.write_text(json.dumps({
        "name": "Deno", "version": VERSION, "source": URL,
        "archive_sha256": ARCHIVE_SHA256,
        "binary_sha256": hashlib.sha256(executable).hexdigest(),
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Verified Deno {VERSION}: {len(executable):,} bytes; licenses saved.")


if __name__ == "__main__":
    main()
