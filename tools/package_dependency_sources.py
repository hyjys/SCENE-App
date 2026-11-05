"""Archive the exact Python dependency sources beside the v0.4 binaries.

Downloads original PyPI source distributions, verifies PyPI's SHA-256 values,
and includes installed license notices and a provenance manifest. Run with the
same virtual environment used to build the release.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import re
import urllib.parse
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "build" / "dependency-sources"
OUTPUT = ROOT / "dist" / "third-party-python-sources-v0.4.zip"
MAX_SOURCE_BYTES = 200 * 1024 * 1024


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pinned_dependencies() -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in (ROOT / "requirements-lock.txt").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?==([A-Za-z0-9_.+-]+)", line)
        if not match:
            raise ValueError(f"Expected a pinned release dependency, got {line!r}")
        name, version = match.groups()
        pins[name] = version
    pins["pyinstaller"] = "6.22.3"
    for name, version in pins.items():
        installed = importlib.metadata.version(name)
        if installed != version:
            raise RuntimeError(f"Build environment differs from lock: {name} {installed}, expected {version}")
    return pins


def fetch_source(item: tuple[str, str]) -> tuple[dict, Path]:
    name, version = item
    api_url = f"https://pypi.org/pypi/{urllib.parse.quote(name)}/{urllib.parse.quote(version)}/json"
    request = urllib.request.Request(api_url, headers={"User-Agent": "SCENE-App-v0.4-source-packager"})
    with urllib.request.urlopen(request, timeout=30) as response:
        metadata = json.load(response)
    sources = sorted((entry for entry in metadata["urls"] if entry["packagetype"] == "sdist"),
                     key=lambda entry: entry["filename"])
    if not sources:
        raise RuntimeError(f"PyPI has no source distribution for {name}=={version}")
    source = sources[0]
    filename = source["filename"]
    if not re.fullmatch(r"[A-Za-z0-9_.+-]+", filename) or filename in {".", ".."}:
        raise RuntimeError(f"Unsafe source filename from PyPI: {filename!r}")
    url = source["url"]
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "files.pythonhosted.org":
        raise RuntimeError(f"Unexpected PyPI source location for {name}: {url}")
    expected_sha = source["digests"]["sha256"]
    expected_size = source["size"]
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha) or not 0 < expected_size <= MAX_SOURCE_BYTES:
        raise RuntimeError(f"Invalid source integrity metadata for {name}")
    directory = CACHE / name / version
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / filename
    if not (destination.is_file() and destination.stat().st_size == expected_size
            and digest(destination) == expected_sha):
        temporary = destination.with_name(destination.name + ".part")
        source_request = urllib.request.Request(url, headers={"User-Agent": "SCENE-App-v0.4-source-packager"})
        try:
            with urllib.request.urlopen(source_request, timeout=30) as response, temporary.open("wb") as stream:
                received = 0
                while block := response.read(1024 * 1024):
                    received += len(block)
                    if received > expected_size:
                        raise RuntimeError(f"Source exceeds published size: {name}")
                    stream.write(block)
            if temporary.stat().st_size != expected_size or digest(temporary) != expected_sha:
                raise RuntimeError(f"Source SHA-256/size mismatch: {name}")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    print(f"Verified {name}=={version}: {filename} ({expected_size:,} bytes)", flush=True)
    info = metadata.get("info", {})
    return {
        "name": name, "version": version, "filename": filename,
        "archive_path": f"sources/{name}/{filename}", "bytes": expected_size,
        "sha256": expected_sha, "source_url": url, "pypi_metadata_url": api_url,
        "license_expression": info.get("license_expression"),
        "license_metadata": info.get("license"),
        "project_urls": info.get("project_urls") or {},
    }, destination


def license_files(name: str) -> list[tuple[Path, str]]:
    distribution = importlib.metadata.distribution(name)
    notices: list[tuple[Path, str]] = []
    for path in distribution.files or ():
        parts = PurePosixPath(str(path).replace("\\", "/")).parts
        metadata_index = next((index for index, part in enumerate(parts) if part.endswith(".dist-info")), None)
        if not path.name.lower().startswith(("license", "copying", "notice")):
            continue
        relative = PurePosixPath(*parts[metadata_index + 1:]) if metadata_index is not None else PurePosixPath(*parts)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Unsafe installed license path for {name}: {path}")
        source = Path(distribution.locate_file(path))
        if source.is_file() and source.stat().st_size:
            notices.append((source, f"licenses/{name}/{relative.as_posix()}"))
    if not notices:
        raise RuntimeError(f"No installed license notices found for {name}")
    return notices


def main() -> None:
    pins = pinned_dependencies()
    with ThreadPoolExecutor(max_workers=4) as executor:
        sources = list(executor.map(fetch_source, sorted(pins.items())))
    manifest = {
        "application": "SCENE App", "version": "0.4",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "description": "Unmodified original PyPI source distributions for the exact Windows release dependencies.",
        "packages": [],
    }
    OUTPUT.parent.mkdir(exist_ok=True)
    temporary = OUTPUT.with_suffix(".zip.part")
    with zipfile.ZipFile(temporary, "w") as archive:
        for entry, source in sources:
            archive.write(source, entry["archive_path"], compress_type=zipfile.ZIP_STORED)
            entry["licenses"] = []
            for license_source, archive_path in license_files(entry["name"]):
                archive.write(license_source, archive_path, compress_type=zipfile.ZIP_DEFLATED)
                entry["licenses"].append({"archive_path": archive_path,
                                          "sha256": digest(license_source)})
            manifest["packages"].append(entry)
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                         compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("README.txt", (
            "Python dependency sources for SCENE App v0.4\n\n"
            "sources/ contains unmodified upstream source archives from PyPI.\n"
            "manifest.json records exact versions, download URLs and verified SHA-256 digests.\n"
            "licenses/ contains the license notices from the corresponding installed distributions.\n"
            "Each dependency retains its own upstream license.\n"
            "Application source and build instructions: https://github.com/hyjys/SCENE-App/tree/v0.4\n"
        ), compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(temporary) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise RuntimeError(f"Source ZIP integrity check failed: {corrupt}")
    temporary.replace(OUTPUT)
    sha = digest(OUTPUT)
    OUTPUT.with_suffix(".zip.sha256").write_text(f"{sha}  {OUTPUT.name}\n", encoding="ascii")
    print(f"Packaged {len(sources)} source distributions: {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)", flush=True)
    print(f"SHA-256: {sha}", flush=True)


if __name__ == "__main__":
    main()
