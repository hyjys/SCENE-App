"""Verify the SCENE App ZIP and frozen GUI without a system Python/Node dependency."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import traceback
import uuid
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
VARIANTS = {
    "scene": ("scene-app.zip", "SCENE-App", "sceneapp.exe"),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def portable_environment() -> dict[str, str]:
    environment = os.environ.copy()
    windows = Path(environment.get("SystemRoot", r"C:\Windows"))
    environment["PATH"] = os.pathsep.join((str(windows / "System32"), str(windows)))
    environment["DENO_NO_UPDATE_CHECK"] = "1"
    for name in ("PYTHONPATH", "PYTHONHOME", "NODE_PATH"):
        environment.pop(name, None)
    return environment


def run(command: list[str], *, cwd: Path, environment: dict[str, str], timeout: int = 120,
        check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=cwd, env=environment, capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=NO_WINDOW, timeout=timeout, check=False)
    if check and result.returncode:
        detail = (result.stdout + "\n" + result.stderr).strip()[-6000:]
        raise RuntimeError(f"{Path(command[0]).name} failed ({result.returncode})\n{detail}")
    return result


def verify_archive(variant: str, work_dir: Path) -> tuple[Path, dict]:
    archive_name, folder, executable = VARIANTS[variant]
    source = ROOT / "dist" / archive_name
    require(source.is_file(), f"Build the release first; archive is missing: {source}")
    checksum_file = source.with_suffix(".zip.sha256")
    expected_zip_sha = checksum_file.read_text(encoding="ascii").split()[0]
    actual_zip_sha = sha256(source)
    require(actual_zip_sha == expected_zip_sha, f"ZIP SHA-256 mismatch: {source}")
    extraction_root = work_dir / variant
    extraction_root.mkdir()
    with zipfile.ZipFile(source) as archive:
        require(archive.testzip() is None, f"Corrupt ZIP: {source}")
        for member in archive.infolist():
            destination = (extraction_root / member.filename).resolve()
            require(destination.is_relative_to(extraction_root.resolve()),
                    f"ZIP member escapes extraction directory: {member.filename}")
            require((member.external_attr >> 16) & 0o170000 != 0o120000,
                    f"Unexpected symbolic link in ZIP: {member.filename}")
        archive.extractall(extraction_root)
    app_root = extraction_root / folder
    manifest = json.loads((app_root / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["variant"] == variant and manifest["executable"] == executable,
            f"Incorrect variant manifest: {source}")
    required = {executable, "ffmpeg.exe", "LICENSE", "THIRD_PARTY_SOURCES.md", "licenses/DENO-LICENSE.txt",
                "assets/fonts/NanumGothic-Regular.ttf", "assets/fonts/NanumGothic-Bold.ttf", "assets/fonts/OFL.txt"}
    require(required.issubset(manifest["files"]), f"Incomplete file manifest: {source}")
    require(manifest.get("application") == "SCENE App", f"Wrong application: {source}")
    require(manifest.get("version") == "0.3", f"Wrong release version: {source}")
    require(not any((app_root / name).exists() for name in ("gui-yt-dlp.exe", "sceneaudiodown.exe")),
            "Legacy applications must not be included in SCENE App")
    require(not (app_root / "yt-dlp.exe").exists(), "SCENE App must use the embedded Python module")
    for name, expected in manifest["files"].items():
        path = (app_root / name).resolve()
        require(path.is_relative_to(app_root.resolve()), f"Unsafe manifest filename: {name}")
        require(path.is_file(), f"Manifest file missing: {path}")
        require(path.stat().st_size == expected["bytes"], f"File size mismatch: {path}")
        require(sha256(path) == expected["sha256"], f"File SHA-256 mismatch: {path}")
    return app_root, {"archive": str(source), "bytes": source.stat().st_size,
                      "sha256": actual_zip_sha, "manifest": manifest, "extracted_to": str(app_root)}


def frozen_check(executable: Path, arguments: list[str], report_path: Path,
                 environment: dict[str, str]) -> dict:
    result = run([str(executable), *arguments, str(report_path)], cwd=executable.parent,
                 environment=environment, check=False)
    require(report_path.is_file(),
            f"Frozen executable wrote no report ({result.returncode}): {executable}\n{result.stderr}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    require(result.returncode == 0 and report.get("ok") is True,
            f"Frozen check failed: {executable}\n{report.get('error', result.stderr)}")
    require(report.get("frozen") is True, f"Check did not run a frozen executable: {executable}")
    require(Path(report["app_dir"]).resolve() == executable.parent.resolve(),
            f"Frozen executable uses the wrong application directory: {report['app_dir']}")
    require(report.get("version") == "0.3", "Frozen app has the wrong version")
    require(report.get("variant") == "SCENE App", "Frozen app has the wrong product identity")
    require(report.get("blackscreen_available") is True, "Integrated blackscreen controls are missing")
    require(report.get("fonts", {}).get("family") == "NanumGothic", "Bundled Korean font was not applied")
    require(report.get("customtkinter") == "6.0.0", "CustomTkinter was not bundled")
    if "--self-test" in arguments or "--self-test-language" in arguments:
        require(report.get("python_api") == "YoutubeDL", "The embedded yt_dlp API was not exercised")
        require(report.get("yt_dlp") == "2026.10.26", "Unexpected yt_dlp version")
        require(report.get("ejs_scripts", 0) >= 2, "Bundled EJS challenge scripts are missing")
    return report


def verify_mp3(path: Path, app_root: Path, environment: dict[str, str]) -> dict:
    require(path.is_file() and path.stat().st_size > 0, f"No MP3 output: {path}")
    result = run([str(app_root / "ffmpeg.exe"), "-hide_banner", "-i", str(path)],
                 cwd=app_root, environment=environment, timeout=20, check=False)
    streams = re.findall(r"^\s*Stream #.*$", result.stderr, re.MULTILINE)
    require(sum("Audio: mp3" in stream for stream in streams) == 1,
            f"Expected one MP3 audio stream: {path}\n{result.stderr}")
    require(not any("Video:" in stream for stream in streams), f"Unexpected video stream: {path}")
    run([str(app_root / "ffmpeg.exe"), "-hide_banner", "-loglevel", "error", "-nostdin",
         "-i", str(path), "-map", "0:a:0", "-f", "null", "-"],
        cwd=app_root, environment=environment, timeout=20)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path), "streams": streams}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def verify_scene_workflows(app_root: Path, work_dir: Path, environment: dict[str, str]) -> dict:
    fixtures = work_dir / "fixtures"
    fixtures.mkdir()
    wav = fixtures / "외부 원본.wav"
    ffmpeg = str(app_root / "ffmpeg.exe")
    executable = app_root / "sceneapp.exe"
    run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "lavfi", "-i",
         "sine=frequency=440:sample_rate=44100", "-t", "0.8", str(wav)],
        cwd=fixtures, environment=environment, timeout=30)
    original_wav_sha = sha256(wav)
    run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(wav),
         "-map", "0:a:0", "-map", "0:a:0", "-c:a", "aac", "-b:a:0", "64k", "-b:a:1", "160k",
         "-f", "dash", "sample.mpd"], cwd=fixtures, environment=environment, timeout=30)
    xml = ET.parse(fixtures / "sample.mpd")
    representations = [node.attrib for node in xml.iter() if node.tag.rsplit("}", 1)[-1] == "Representation"]
    require(len(representations) == 2 and all(item.get("mimeType", "").startswith("audio/") for item in representations),
            f"Fixture must contain two audio-only representations: {representations}")
    highest = max(representations, key=lambda item: int(item["bandwidth"]))
    expected_id = highest["id"]
    expected_kbps = int(highest["bandwidth"]) / 1000
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(fixtures)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/sample.mpd"
        download = frozen_check(executable, ["--self-test-download", url, "7", "다운로드검증"],
                                work_dir / "scene-download.json", environment)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    downloaded = Path(download["output"])
    require(downloaded.parent == app_root / "Downloads" and downloaded.name == "bgm7_다운로드검증.mp3",
            f"Incorrect downloaded cue filename: {downloaded}")
    expected_selections = (f"오디오 전용 ID {expected_id} · {expected_kbps:g} kbps",
                           f"audio-only ID {expected_id} · {expected_kbps:g} kbps")
    require(any(text in download["log"] for text in expected_selections), f"Highest bitrate was not selected:\n{download['log']}")
    require(any(text in download["log"] for text in (f"오디오 다운로드 · {expected_id} /", f"Downloading Audio · {expected_id} /")),
            f"The selected format ID was not downloaded:\n{download['log']}")
    downloaded_media = verify_mp3(downloaded, app_root, environment)
    require(not (app_root / "yt-dlp.exe").exists(), "No yt-dlp sidecar may be shipped")
    converted = frozen_check(executable, ["--self-test-convert", str(wav), "007.50", "외부음원검증"],
                             work_dir / "scene-convert.json", environment)
    converted_path = Path(converted["output"])
    require(converted_path.parent == app_root / "Downloads" and converted_path.name == "bgm007.50_외부음원검증.mp3",
            f"Incorrect converted cue filename: {converted_path}")
    require(sha256(wav) == original_wav_sha, "External source file was modified during conversion")
    require("FFmpeg: MP3 (libmp3lame, VBR 2)" in converted["log"], "External conversion did not report Make MP3 settings")
    require(not list((app_root / "Downloads").glob(".gui-yt-dlp-*")), "Successful workflows left working directories behind")
    converted_media = verify_mp3(converted_path, app_root, environment)
    return {"fixture": {"representations": representations, "selected_id": expected_id,
                         "selected_kbps": expected_kbps},
            "download": download, "download_media": downloaded_media,
            "convert_without_yt_dlp": converted, "converted_media": converted_media,
            "external_source_preserved": True}


def main() -> None:
    (ROOT / "build").mkdir(exist_ok=True)
    work_dir = ROOT / "build" / ("release-check-" + uuid.uuid4().hex[:12])
    work_dir.mkdir()
    report = {"ok": False, "started_utc": datetime.now(timezone.utc).isoformat(), "workspace": str(work_dir),
              "variants": {}}
    environment = portable_environment()
    report["restricted_path"] = environment["PATH"]
    try:
        roots = {}
        for variant in VARIANTS:
            app_root, archive = verify_archive(variant, work_dir)
            roots[variant] = app_root
            executable = app_root / VARIANTS[variant][2]
            self_test = frozen_check(executable, ["--self-test"], work_dir / f"{variant}-self-test.json", environment)
            english_test = frozen_check(executable, ["--self-test-language", "en", "--self-test"], work_dir / f"{variant}-english.json", environment)
            require(english_test.get("language") == "en", "English diagnostic did not select English")
            report["variants"][variant] = {"archive": archive, "self_test": self_test, "english_test": english_test}
            print(f"Verified {variant}: ZIP manifest, CustomTkinter/NanumGothic/yt_dlp/Deno, restricted PATH", flush=True)
        report["scene_workflows"] = verify_scene_workflows(roots["scene"], work_dir, environment)
        report["ok"] = True
        print("Verified SCENE: highest-bitrate audio download via yt_dlp module and external conversion", flush=True)
    except Exception:
        report["error"] = traceback.format_exc()
        print(report["error"], flush=True)
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    destination = ROOT / "build" / "release-verification.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Verification report: {destination}", flush=True)
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
