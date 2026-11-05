"""SCENE App's yt-dlp Python API and FFmpeg services.

All callbacks run on the calling worker thread.  The GUI must marshal them to
its event queue; no Tk objects are used by this module.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Callable
from urllib.parse import urlsplit

import yt_dlp
from i18n import tr


class AppError(Exception):
    """An error suitable for showing in the application."""


class Cancelled(AppError):
    """The user cancelled the current operation."""


@dataclass
class MediaFormat:
    format_id: str
    kind: str
    ext: str = ""
    resolution: str = ""
    fps: str = ""
    codec: str = ""
    bitrate: str = ""
    size: str = ""
    note: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class MediaInfo:
    url: str
    title: str
    duration: float | None
    audio_formats: list[MediaFormat]
    video_formats: list[MediaFormat]


def app_dir() -> Path:
    """Find sidecar executables beside the app, never in PyInstaller's temp dir."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


class ProcessRunner:
    def __init__(self, event_callback: Callable[[str, object], None]):
        self._callback = event_callback
        self._cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self.progress_duration: float | None = None

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def emit(self, kind: str, payload: object) -> None:
        self._callback(kind, payload)

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise Cancelled(tr("작업을 취소했습니다."))

    def cancel(self) -> None:
        self._cancel_event.set()
        with self._lock:
            process = self._process
        if process is not None:
            # taskkill may take a moment; never block the Tk event loop.
            threading.Thread(target=self._kill_tree, args=(process,), daemon=True).start()

    @staticmethod
    def _kill_tree(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=_creation_flags(),
                    timeout=10,
                    check=False,
                )
                if process.poll() is None:
                    process.kill()
            else:
                process.kill()
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass

    def run(self, command: list[str], cwd: Path | None = None) -> list[str]:
        self.check_cancelled()
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUTF8"] = "1"
        try:
            with self._lock:
                self.check_cancelled()
                process = subprocess.Popen(
                    [str(part) for part in command],
                    cwd=str(cwd) if cwd else None,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=environment,
                    creationflags=_creation_flags(),
                    bufsize=1,
                    shell=False,
                )
                self._process = process
        except OSError as exc:
            raise AppError(tr("실행할 수 없습니다: {name}\n{error}", name=Path(command[0]).name, error=exc)) from exc

        lines: list[str] = []
        error_tail: deque[str] = deque(maxlen=16)
        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.rstrip("\r\n")
                if not line:
                    continue
                lines.append(line)
                if re.match(r"^(frame|fps|stream_\d+_\d+_q|bitrate|total_size|out_time_us|out_time_ms|out_time|dup_frames|drop_frames|speed|progress)=", line):
                    key, value = line.split("=", 1)
                    if key == "out_time_us" and self.progress_duration:
                        try:
                            percent = float(value) / 1_000_000 / self.progress_duration * 100
                            self.emit("progress", max(0.0, min(99.9, percent)))
                        except ValueError:
                            pass
                    elif key == "progress" and value == "end":
                        self.emit("progress", 100.0)
                    continue
                error_tail.append(line)
                self.emit("log", line)
            returncode = process.wait()
            self.check_cancelled()
            if returncode:
                detail = "\n".join(error_tail)
                raise AppError(tr("{name} 실행 실패 (코드 {code})\n{detail}", name=Path(command[0]).name, code=returncode, detail=detail))
            return lines
        except BaseException:
            if process.poll() is None:
                self._kill_tree(process)
            raise
        finally:
            if process.stdout is not None:
                process.stdout.close()
            with self._lock:
                if self._process is process:
                    self._process = None


def _executable(name: str) -> Path:
    path = app_dir() / name
    if not path.is_file():
        raise AppError(tr("{name} 파일을 찾을 수 없습니다.\n앱과 같은 폴더에 놓아 주세요:\n{directory}", name=name, directory=app_dir()))
    return path


def _validate_url(url: str) -> str:
    url = url.strip()
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        valid = False
    if not valid or any(ord(char) < 32 for char in url):
        raise AppError(tr("올바른 http:// 또는 https:// 동영상 링크를 입력해 주세요."))
    return url


class _YtdlpLogger:
    """Forward text without writing to the console of a frozen windowed app."""

    def __init__(self, runner: ProcessRunner):
        self.runner = runner

    def debug(self, message: str) -> None:
        self.runner.check_cancelled()
        if not message.startswith("[debug] "):
            self.runner.emit("log", message)

    info = debug

    def warning(self, message: str) -> None:
        self.runner.check_cancelled()
        self.runner.emit("log", tr("경고: {message}", message=message))

    def error(self, message: str) -> None:
        self.runner.check_cancelled()
        self.runner.emit("log", message)


def _yt_options(runner: ProcessRunner) -> dict:
    """Construct API options; YoutubeDL does not read user CLI config files."""
    runner.check_cancelled()
    return {
        "noplaylist": True,
        "color": "no_color",
        "socket_timeout": 10,
        "retries": 2,
        "fragment_retries": 2,
        "extractor_retries": 2,
        "cachedir": False,
        "logger": _YtdlpLogger(runner),
        "noprogress": True,
        "js_runtimes": _js_runtimes(),
        "ffmpeg_location": str(app_dir()),
        # Let our own cancellable ProcessRunner perform media conversion.
        "fixup": "never",
        "external_downloader": {"m3u8": "native", "dash": "native"},
    }


def _js_runtimes() -> dict[str, dict[str, str]]:
    """Translate the shared runtime probe into YoutubeDL's Python API format."""
    args = _js_runtime_args()
    if not args:
        return {}
    runtime, path = args[-1].split(":", 1)
    return {runtime: {"path": path}}


@lru_cache(maxsize=1)
def _js_runtime_args() -> list[str]:
    """Use the packaged Deno runtime without requiring a system JS install."""
    frozen = bool(getattr(sys, "frozen", False))
    deno_candidates: list[Path] = []
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if frozen and bundle_dir:
        deno_candidates.append(Path(bundle_dir) / "runtime" / "deno.exe")
    if not frozen:
        deno_candidates.append(app_dir() / "vendor" / "deno.exe")
    deno_candidates.append(app_dir() / "deno.exe")
    for candidate in deno_candidates:
        if _runtime_is_supported(candidate, "deno"):
            # Disable yt-dlp's default runtime search: the distributable must
            # work with precisely the Deno included in its single-file bundle.
            return ["--no-js-runtimes", "--js-runtimes", f"deno:{candidate}"]
    if frozen:
        raise AppError(tr("내장 JavaScript 런타임(Deno)을 실행할 수 없습니다.\n앱을 다시 빌드하거나 정상적인 sceneapp.exe로 교체해 주세요."))

    # Source development may precede downloading vendor/deno.exe.  Packaged
    # applications deliberately never fall back to a system Node installation.
    candidates = [app_dir() / "node.exe"]
    located = shutil.which("node")
    if located:
        candidates.append(Path(located))
    for variable in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        location = os.environ.get(variable)
        if location:
            candidates.append(Path(location) / "nodejs" / "node.exe")
    seen: set[Path] = set()
    for candidate in candidates:
        if not candidate.is_file() or candidate in seen:
            continue
        seen.add(candidate)
        if _runtime_is_supported(candidate, "node"):
            return ["--no-js-runtimes", "--js-runtimes", f"node:{candidate}"]
    return []


def _runtime_is_supported(candidate: Path, runtime: str) -> bool:
    if not candidate.is_file():
        return False
    try:
        result = subprocess.run(
            [str(candidate), "--version"], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=_creation_flags(), timeout=5, check=False,
        )
        pattern = r"deno\s+(\d+)\." if runtime == "deno" else r"v?(\d+)\."
        match = re.match(pattern, result.stdout.strip())
        minimum = 2 if runtime == "deno" else 22
        return bool(result.returncode == 0 and match and int(match.group(1)) >= minimum)
    except (OSError, subprocess.SubprocessError):
        return False


def _number(value: object) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _display_number(value: object, suffix: str = "") -> str:
    number = _number(value)
    return f"{number:g}{suffix}" if number is not None else "—"


def _display_size(value: object, approximate: bool) -> str:
    number = _number(value)
    if number is None or number <= 0:
        return "—"
    prefix = "~" if approximate else ""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if number < 1024 or unit == "TiB":
            return f"{prefix}{number:.1f} {unit}"
        number /= 1024
    return "—"


def _parse_formats(data: dict, url: str) -> MediaInfo:
    if data.get("_type") in {"playlist", "multi_video"} or data.get("entries") is not None:
        raise AppError(tr("재생목록 전체 대신 개별 동영상 링크를 입력해 주세요."))
    audio_formats: list[MediaFormat] = []
    video_formats: list[MediaFormat] = []
    seen: set[tuple[str, str]] = set()
    for item in data.get("formats", []):
        if not isinstance(item, dict) or item.get("has_drm") or not item.get("format_id"):
            continue
        vcodec, acodec = item.get("vcodec"), item.get("acodec")
        if item.get("ext") in {"mhtml", "jpg", "jpeg", "png", "webp"} or item.get("protocol") == "mhtml":
            continue
        has_video = vcodec not in (None, "none")
        has_audio = acodec not in (None, "none")
        if not has_video and not has_audio:
            continue
        kind = "video" if has_video else "audio"
        format_id = str(item["format_id"])
        if (kind, format_id) in seen:
            continue
        seen.add((kind, format_id))
        resolution = item.get("resolution")
        if has_video and item.get("width") and item.get("height"):
            resolution = f"{item['width']}×{item['height']}"
        elif not has_video:
            resolution = _display_number(item.get("asr"), " Hz")
        notes = [str(item[key]) for key in ("language", "format_note", "dynamic_range") if item.get(key)]
        if has_video and has_audio:
            notes.append(tr("내장 오디오는 제외"))
        filesize = item.get("filesize") or item.get("filesize_approx")
        fmt = MediaFormat(
            format_id=format_id, kind=kind, ext=str(item.get("ext") or ""),
            resolution=str(resolution or "—"),
            fps=_display_number(item.get("fps")) if has_video else "—",
            codec=str(vcodec if has_video else acodec),
            bitrate=_display_number(item.get("tbr") if has_video else (item.get("abr") or item.get("tbr")), " kbps"),
            size=_display_size(filesize, not bool(item.get("filesize"))),
            note=" · ".join(notes), raw=dict(item),
        )
        (video_formats if has_video else audio_formats).append(fmt)
    if not audio_formats and not video_formats:
        raise AppError(tr("다운로드할 수 있는 오디오/비디오 형식을 찾지 못했습니다."))
    audio_formats.sort(key=lambda f: (_number(f.raw.get("abr")) or _number(f.raw.get("tbr")) or 0, f.format_id), reverse=True)
    video_formats.sort(key=lambda f: (_number(f.raw.get("height")) or 0, _number(f.raw.get("fps")) or 0, _number(f.raw.get("tbr")) or 0), reverse=True)
    return MediaInfo(url=url, title=str(data.get("title") or data.get("id") or tr("동영상")),
                     duration=_number(data.get("duration")), audio_formats=audio_formats, video_formats=video_formats)


def fetch_formats(url: str, runner: ProcessRunner) -> MediaInfo:
    url = _validate_url(url)
    runner.check_cancelled()
    runner.emit("status", tr("동영상 정보와 형식 목록을 불러오는 중…"))
    runner.emit("progress", None)
    runner.emit("log", tr("yt-dlp Python 모듈 {version}: 오디오 / 비디오 형식 조회", version=yt_dlp.version.__version__))
    try:
        with yt_dlp.YoutubeDL(_yt_options(runner)) as ydl:
            data = ydl.extract_info(url, download=False)
        runner.check_cancelled()
        if not isinstance(data, dict):
            raise AppError(tr("yt-dlp의 동영상 정보를 해석할 수 없습니다."))
        info = _parse_formats(data, url)
    except (yt_dlp.utils.YoutubeDLError, OSError) as exc:
        runner.check_cancelled()
        raise AppError(tr("동영상 정보를 불러오지 못했습니다.\n{error}", error=exc)) from exc
    runner.emit("status", tr("형식 목록을 불러왔습니다."))
    runner.emit("progress", 0.0)
    return info


def _download_format(info: MediaInfo, fmt: MediaFormat, work_dir: Path, runner: ProcessRunner) -> Path:
    runner.check_cancelled()
    kind_name = tr("비디오") if fmt.kind == "video" else tr("오디오")
    runner.emit("status", tr("{kind} 다운로드 중 · ID {format_id}", kind=kind_name, format_id=fmt.format_id))
    runner.emit("log", tr("{kind} 다운로드 · {format_id} / {ext}", kind=kind_name, format_id=fmt.format_id, ext=fmt.ext))
    runner.emit("progress", 0.0)
    # Use a title chosen and sanitised by yt-dlp, and keep each selected stream
    # separate even when they happen to have the same filename or extension.
    stream_dir = work_dir / fmt.kind
    stream_dir.mkdir()
    completed: list[Path] = []

    def select_exact_format(context: dict):
        # A callable treats IDs literally instead of interpreting '+' or '/'
        # as format-selection syntax and silently downloading another stream.
        runner.check_cancelled()
        for candidate in context.get("formats", []):
            if str(candidate.get("format_id")) == fmt.format_id:
                yield candidate
                return
        raise AppError(tr("선택한 형식 ID {format_id}가 더 이상 제공되지 않습니다. 목록을 다시 조회해 주세요.", format_id=fmt.format_id))

    def progress_hook(progress: dict) -> None:
        runner.check_cancelled()
        state = progress.get("status")
        if state == "finished":
            runner.emit("progress", 100.0)
            return
        if state != "downloading":
            return
        downloaded = _number(progress.get("downloaded_bytes")) or 0
        total = _number(progress.get("total_bytes")) or _number(progress.get("total_bytes_estimate"))
        percent = min(100.0, max(0.0, downloaded / total * 100)) if total and total > 0 else None
        runner.emit("progress", percent)
        details = [f"{percent:.1f}%" if percent is not None else _display_size(downloaded, False)]
        speed = _number(progress.get("speed"))
        eta = _number(progress.get("eta"))
        if speed and speed > 0:
            details.append(_display_size(speed, False) + "/s")
        if eta is not None:
            details.append(tr("남은 시간 {seconds}초", seconds=max(0, int(eta))))
        runner.emit("status", tr("{kind} 다운로드 중 · {details}", kind=kind_name, details=" · ".join(details)))

    def completed_hook(filename: str) -> None:
        runner.check_cancelled()
        completed.append(Path(filename))

    options = _yt_options(runner)
    options.update({
        "format": select_exact_format,
        # Keep literal directory names (including '%') out of the template.
        "paths": {"home": str(stream_dir)},
        "outtmpl": "%(title).100s [%(id)s].%(ext)s",
        "windowsfilenames": True,
        "trim_file_name": 120,
        "updatetime": False,
        "overwrites": False,
        "progress_delta": 0.25,
        "progress_hooks": [progress_hook],
        "post_hooks": [completed_hook],
    })
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.extract_info(info.url, download=True)
        runner.check_cancelled()
    except (yt_dlp.utils.YoutubeDLError, OSError) as exc:
        runner.check_cancelled()
        raise AppError(tr("{kind} 다운로드에 실패했습니다.\n{error}", kind=kind_name, error=exc)) from exc
    for candidate in reversed(completed):
        path = candidate.resolve()
        if path.is_relative_to(stream_dir.resolve()) and path.is_file() and path.stat().st_size:
            return path
    # Some extractors omit post_hooks if they did not need to move the file.
    files = [path for path in stream_dir.iterdir() if path.is_file() and path.suffix not in {".part", ".ytdl", ".json", ".temp"} and path.stat().st_size]
    if len(files) == 1:
        return files[0]
    raise AppError(tr("다운로드된 {kind} 파일을 찾을 수 없습니다.", kind=kind_name))


def _ffmpeg_command(video_path: Path | None, audio_path: Path | None, output_path: Path,
                    make_mp3: bool, make_mp4: bool, fast: bool) -> list[str]:
    command = [str(_executable("ffmpeg.exe")), "-hide_banner", "-loglevel", "warning",
               "-nostdin", "-n", "-nostats", "-progress", "pipe:1", "-stats_period", "0.25"]
    if video_path:
        command += ["-i", str(video_path)]
    if audio_path:
        command += ["-i", str(audio_path)]
    if video_path:
        command += ["-map", "0:v:0"]
        if audio_path:
            command += ["-map", "1:a:0"]
        else:
            command += ["-an"]
        if make_mp4:
            command += ["-c:v", "libx264", "-preset", "fast" if fast else "slow", "-crf", "20",
                        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p"]
            if audio_path:
                command += ["-c:a", "libmp3lame", "-q:a", "2"]
            command += ["-movflags", "+faststart"]
        else:
            command += ["-c", "copy"]
    elif audio_path:
        command += ["-map", "0:a:0", "-vn"]
        command += ["-c:a", "libmp3lame", "-q:a", "2"] if make_mp3 else ["-c:a", "copy"]
    command += [str(output_path)]
    return command


def _publish_unique(source: Path, downloads: Path, name: str, runner: ProcessRunner) -> Path:
    """Publish without replacing anything, including files created concurrently."""
    target = downloads / name
    stem, suffix = target.stem, target.suffix
    index = 1
    while True:
        runner.check_cancelled()
        try:
            # Windows rename fails if the destination exists; on POSIX use a
            # hard link to obtain the same atomic no-replace guarantee.
            if os.name == "nt":
                source.rename(target)
            else:
                os.link(source, target)
                source.unlink()
            return target
        except FileExistsError:
            index += 1
            target = downloads / f"{stem} ({index}){suffix}"


def _cleanup_work_dir(work_dir: Path, downloads: Path) -> None:
    """Confine recursive deletion to our own verified temporary directory."""
    if not work_dir.exists():
        return
    if (not work_dir.name.startswith(".gui-yt-dlp-")
            or not work_dir.is_dir()
            or work_dir.is_symlink()
            or getattr(work_dir, "is_junction", lambda: False)()
            or work_dir.resolve().parent != downloads.resolve()):
        raise AppError(tr("안전한 임시 폴더인지 확인할 수 없어 정리하지 않았습니다: {directory}", directory=work_dir))
    shutil.rmtree(work_dir)


def download_media(info: MediaInfo, video: MediaFormat | None, audio: MediaFormat | None,
                   make_mp3: bool, make_mp4: bool, fast: bool, runner: ProcessRunner,
                   *, output_name: str | None = None) -> Path:
    runner.check_cancelled()
    if output_name is not None and (
            not output_name or output_name in {".", ".."}
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', output_name)
            or output_name.endswith((" ", "."))):
        raise AppError(tr("저장 파일명에 사용할 수 없는 문자가 있습니다."))
    _validate_url(info.url)
    if video is None and audio is None:
        raise AppError(tr("오디오 또는 비디오를 하나 이상 선택해 주세요."))
    if video is not None and (video.kind != "video" or not any(f.format_id == video.format_id for f in info.video_formats)):
        raise AppError(tr("비디오 선택이 현재 형식 목록과 일치하지 않습니다. 목록을 다시 불러와 주세요."))
    if audio is not None and (audio.kind != "audio" or not any(f.format_id == audio.format_id for f in info.audio_formats)):
        raise AppError(tr("오디오 선택이 현재 형식 목록과 일치하지 않습니다. 목록을 다시 불러와 주세요."))
    # An unknown audio codec may mean a progressive file.  Strip audio unless
    # the extractor explicitly identified this as a video-only stream.
    embedded_audio = video is not None and video.raw.get("acodec") != "none"
    requires_ffmpeg = bool((video and audio) or (video and make_mp4) or
                           (audio and not video and make_mp3) or embedded_audio)
    if requires_ffmpeg:
        _executable("ffmpeg.exe")
    downloads = app_dir() / "Downloads"
    try:
        downloads.mkdir(exist_ok=True)
        work_dir = Path(tempfile.mkdtemp(prefix=".gui-yt-dlp-", dir=downloads))
    except OSError as exc:
        raise AppError(tr("다운로드 폴더에 파일을 쓸 수 없습니다.\n{directory}\n{error}", directory=downloads, error=exc)) from exc
    runner.emit("log", tr("작업 폴더: {directory}", directory=work_dir))
    try:
        video_path = _download_format(info, video, work_dir, runner) if video else None
        audio_path = _download_format(info, audio, work_dir, runner) if audio else None
        base_path = video_path or audio_path
        assert base_path is not None
        runner.check_cancelled()
        if requires_ffmpeg:
            if video:
                suffix = ".mp4" if make_mp4 else ".mkv"
            else:
                suffix = ".mp3"
            converted_path = work_dir / (base_path.stem + suffix)
            runner.emit("status", tr("MP4 변환 중…" if video and make_mp4 else "MP3 변환 중…" if not video else "선택한 스트림을 합치는 중…" if audio else "비디오 트랙을 추출하는 중…"))
            runner.emit("progress", 0.0 if info.duration else None)
            codec_summary = (f"H.264 (libx264, {'fast' if fast else 'slow'}, CRF 20)" if make_mp4 else tr("원본 코덱 유지")) if video else "MP3 (libmp3lame, VBR 2)"
            if video and audio and make_mp4:
                codec_summary += " + MP3 (libmp3lame, VBR 2)"
            runner.emit("log", "FFmpeg: " + codec_summary)
            runner.progress_duration = info.duration
            runner.run(_ffmpeg_command(video_path, audio_path, converted_path, make_mp3, make_mp4, fast), cwd=work_dir)
            if not converted_path.is_file() or converted_path.stat().st_size == 0:
                raise AppError(tr("FFmpeg가 결과 파일을 만들지 못했습니다."))
            source = converted_path
        else:
            source = base_path
        runner.check_cancelled()
        final_path = _publish_unique(source, downloads, output_name or source.name, runner)
        # Only remove our private working directory after successful publication.
        try:
            _cleanup_work_dir(work_dir, downloads)
        except (OSError, AppError):
            runner.emit("log", tr("임시 파일 정리가 필요합니다: {directory}", directory=work_dir))
        runner.emit("progress", 100.0)
        runner.emit("status", tr("다운로드 완료"))
        runner.emit("log", tr("저장 완료: {path}", path=final_path))
        return final_path
    except (AppError, OSError) as exc:
        try:
            has_files = any(path.is_file() for path in work_dir.rglob("*"))
        except OSError:
            has_files = True
        if has_files:
            message = tr("{error}\n\n다운로드한 파일 / 미완성 파일은 여기에 보관했습니다:\n{directory}", error=exc, directory=work_dir)
        else:
            message = str(exc)
            try:
                _cleanup_work_dir(work_dir, downloads)
            except (OSError, AppError):
                message += tr("\n임시 폴더 정리가 필요합니다: {directory}", directory=work_dir)
        if isinstance(exc, Cancelled):
            raise Cancelled(message) from exc
        raise AppError(message) from exc
    finally:
        runner.progress_duration = None
