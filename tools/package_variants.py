"""Package SCENE App v0.4, FFmpeg, fonts and redistribution notices."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.4"
RUNTIME_PACKAGES = (
    "customtkinter", "darkdetect", "packaging", "yt-dlp", "yt-dlp-ejs", "brotli", "certifi",
    "charset-normalizer", "idna", "mutagen", "pycryptodomex", "requests", "urllib3", "websockets",
    "python-docx", "PyMuPDF", "Pillow", "lxml", "typing_extensions", "tkinterweb", "tkinterweb-tkhtml",
    "tkinterweb-tkhtml-extras", "pythonmonkey", "pminit", "aiohttp", "pyreadline3",
    "aiohappyeyeballs", "aiosignal", "attrs", "frozenlist", "multidict", "propcache", "yarl",
    "pyinstaller",
)
VARIANTS = {
    "scene": ("sceneapp.exe", "scene-app.zip", "SCENE-App", ROOT / "docs" / "SCENE-사용법.txt"),
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def third_party_notices() -> str:
    result = subprocess.run(
        [str(ROOT / "ffmpeg.exe"), "-hide_banner", "-L"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=15, check=True,
    )
    return (
        "Bundled third-party tools\n\n"
        "SCENE App v0.4: GPL-3.0-or-later; see LICENSE.\n"
        "Source: https://github.com/hyjys/SCENE-App/tree/v0.4\n"
        "CustomTkinter: MIT; yt-dlp Python module: Unlicense; yt-dlp-ejs: Unlicense (bundled JS: MIT/ISC).\n"
        "Nanum Gothic Regular/Bold: SIL Open Font License 1.1; see assets/fonts/OFL.txt.\n"
        "python-docx and TkinterWeb: MIT; Pillow: HPND; lxml: BSD-3-Clause.\n"
        "PyMuPDF / MuPDF: AGPL-3.0-or-later; see licenses/PyMuPDF and upstream sources.\n"
        "PythonMonkey/pminit: MIT; bundled SpiderMonkey: MPL-2.0; JS dependency notices: licenses/pminit.\n"
        "FFmpeg: https://ffmpeg.org/\n"
        "FFmpeg Windows build: https://github.com/BtbN/FFmpeg-Builds\n"
        "Deno (embedded in the GUI executable): https://github.com/denoland/deno\n"
        "Deno license: licenses/DENO-LICENSE.txt\n\n"
        "Exact dependency versions, source locations and build configuration: THIRD_PARTY_SOURCES.md\n"
        "Python dependency licenses: licenses/\n\n"
        "License notice reported by the bundled FFmpeg binary:\n"
        + result.stdout + result.stderr
    )


def package_variant(variant: str, notices: str) -> Path:
    executable, archive_name, folder, readme = VARIANTS[variant]
    files = [(ROOT / name, name) for name in (executable, "ffmpeg.exe", "LICENSE", "THIRD_PARTY_SOURCES.md")]
    files += [(readme, "사용법.txt" if variant == "scene" else "README.md"),
              (ROOT / "vendor" / "DENO-LICENSE.txt", "licenses/DENO-LICENSE.txt"),
              (ROOT / "vendor" / "ffmpeg-LICENSE.txt", "licenses/FFMPEG-LICENSE.txt"),
              (ROOT / "vendor" / "ffmpeg-README.txt", "licenses/FFMPEG-BUILD-README.txt"),
              (ROOT / "vendor" / "TCL-LICENSE.txt", "licenses/TCL-LICENSE.txt"),
              (ROOT / "vendor" / "TK-LICENSE.txt", "licenses/TK-LICENSE.txt"),
              (ROOT / "vendor" / "EJS-THIRD-PARTY-LICENSES.txt", "licenses/yt-dlp-ejs/JS-DEPENDENCIES.txt"),
              (ROOT / "docs" / "README.en.md", "README.en.md"),
              (ROOT / "docs" / "CTkPDFViewer-LICENSE.txt", "licenses/CTkPDFViewer-LICENSE.txt"),
              (ROOT / "docs" / "FFMPEG-SOURCES.md", "docs/FFMPEG-SOURCES.md")]
    files += [(path, path.relative_to(ROOT).as_posix()) for path in sorted((ROOT / "assets" / "fonts").glob("*")) if path.is_file()]
    for package in RUNTIME_PACKAGES:
        distribution = importlib.metadata.distribution(package)
        for path in distribution.files or ():
            if not path.name.lower().startswith(("license", "copying", "notice")):
                continue
            parts = PurePosixPath(str(path).replace("\\", "/")).parts
            metadata_index = next((index for index, part in enumerate(parts) if part.endswith(".dist-info")), None)
            relative = PurePosixPath(*parts[metadata_index + 1:]) if metadata_index is not None else PurePosixPath(*parts)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Unsafe dependency license path: {path}")
            source = Path(distribution.locate_file(path))
            if source.is_file() and source.stat().st_size:
                files.append((source, f"licenses/{package}/{relative.as_posix()}"))
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise FileNotFoundError(f"Python license missing: {python_license}")
    files.append((python_license, "licenses/PYTHON-LICENSE.txt"))
    for path in sorted((Path(sys.base_prefix) / "tcl").glob("*/license*")):
        files.append((path, f"licenses/{path.parent.name}-{path.name}"))
    files += [(ROOT / "vendor" / name, f"vendor/{name}") for name in ("runtime.json", "ffmpeg.json")]
    files += [(path, path.relative_to(ROOT).as_posix()) for path in sorted((ROOT / "vendor" / "sources").glob("*"))
              if path.name.startswith(("FFmpeg-Builds-", "ffmpeg-dependency-"))]
    for source, _ in files:
        if not source.is_file() or source.stat().st_size == 0:
            raise FileNotFoundError(f"Required distribution file is missing or empty: {source}")
    manifest = {
        "application": "SCENE App",
        "version": VERSION,
        "license": "GPL-3.0-or-later",
        "source": "https://github.com/hyjys/SCENE-App/tree/v0.4",
        "python": sys.version.split()[0],
        "dependencies": {name: importlib.metadata.version(name) for name in RUNTIME_PACKAGES},
        "variant": variant,
        "executable": executable,
        "files": {name: {"bytes": source.stat().st_size, "sha256": digest(source)} for source, name in files},
    }
    output_dir = ROOT / "dist"
    output_dir.mkdir(exist_ok=True)
    archive_path = output_dir / archive_name
    temporary_path = archive_path.with_suffix(".zip.part")
    with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, name in files:
            archive.write(source, f"{folder}/{name}")
        archive.writestr(f"{folder}/THIRD-PARTY.txt", notices)
        archive.writestr(f"{folder}/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    with zipfile.ZipFile(temporary_path) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise RuntimeError(f"ZIP integrity check failed: {corrupt}")
    temporary_path.replace(archive_path)
    archive_path.with_suffix(".zip.sha256").write_text(
        f"{digest(archive_path)}  {archive_path.name}\n", encoding="ascii",
    )
    print(f"Packaged {variant}: {archive_path} ({archive_path.stat().st_size:,} bytes)", flush=True)
    return archive_path


def package_source() -> Path:
    """Bundle the rebuildable application source without local build artifacts."""
    root_files = {
        "LICENSE", "README.md", "CHANGELOG.md", "THIRD_PARTY_SOURCES.md",
        "build.ps1", "version_info.txt", ".gitignore", ".gitattributes",
    }
    sources = {ROOT / name for name in root_files if (ROOT / name).is_file()}
    sources.update(ROOT.glob("*.py"))
    sources.update(ROOT.glob("requirements*.txt"))
    excluded_dirs = {".git", ".venv", "__pycache__", ".test-work", "build", "dist", "Downloads"}
    excluded_suffixes = {".exe", ".dll", ".pyd", ".pyc", ".log", ".part", ".spec"}
    for directory in ("assets", "docs", "tests", "tools", "installer", ".github", "vendor"):
        for path in (ROOT / directory).rglob("*"):
            relative = path.relative_to(ROOT)
            if (path.is_file() and not path.is_symlink()
                    and not excluded_dirs.intersection(relative.parts)
                    and path.suffix.lower() not in excluded_suffixes):
                sources.add(path)
    required = {
        "scene_app.py", "scene_blackscreen.py", "backend.py", "scene_backend.py",
        "scene_audio.py", "scene_script.py", "scene_updates.py", "scene_settings.py",
        "scene_stage.py", "scene_projector.py", "scene_video.py", "installer/sceneapp.iss",
        "ui_theme.py", "ui_translations.py", "i18n.py", "build.ps1", "version_info.txt",
        "requirements-lock.txt", "LICENSE", "tools/package_variants.py",
        "vendor/ffmpeg.json", "vendor/runtime.json",
    }
    names = {path.relative_to(ROOT).as_posix() for path in sources}
    if missing := required - names:
        raise FileNotFoundError(f"Required source files missing: {', '.join(sorted(missing))}")
    for path in sources:
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError(f"Source path escapes the project: {path}")
    output_dir = ROOT / "dist"
    output_dir.mkdir(exist_ok=True)
    archive_path = output_dir / f"SCENE-App-v{VERSION}-source.zip"
    temporary_path = archive_path.with_suffix(".zip.part")
    folder = f"SCENE-App-v{VERSION}"
    manifest = {
        "application": "SCENE App", "version": VERSION,
        "source": f"https://github.com/hyjys/SCENE-App/tree/v{VERSION}",
        "files": {},
    }
    with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(sources):
            name = path.relative_to(ROOT).as_posix()
            archive.write(path, f"{folder}/{name}")
            manifest["files"][name] = {"bytes": path.stat().st_size, "sha256": digest(path)}
        archive.writestr(f"{folder}/SOURCE-MANIFEST.json",
                         json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    with zipfile.ZipFile(temporary_path) as archive:
        if corrupt := archive.testzip():
            raise RuntimeError(f"Source ZIP integrity check failed: {corrupt}")
    temporary_path.replace(archive_path)
    archive_path.with_suffix(".zip.sha256").write_text(
        f"{digest(archive_path)}  {archive_path.name}\n", encoding="ascii",
    )
    print(f"Packaged source: {archive_path} ({archive_path.stat().st_size:,} bytes)", flush=True)
    return archive_path


def main() -> None:
    package_variant("scene", third_party_notices())
    package_source()


if __name__ == "__main__":
    main()
