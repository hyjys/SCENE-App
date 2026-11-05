"""BGM-numbered projector downloads with explicit H.264/MP3 encoding."""
from __future__ import annotations

from pathlib import Path
import tempfile

import backend
from scene_backend import scene_output_name, _select_audio, _positive_number
from scene_settings import validate_settings


def _options(settings: dict) -> dict:
    try:
        return validate_settings(settings)
    except (ValueError, TypeError, AttributeError) as exc:
        raise backend.AppError(f"영상 설정을 확인하세요.\n{exc}") from exc


def video_command(source: Path, audio: Path | None, output: Path, settings: dict) -> list[str]:
    options = _options(settings)
    encoder = options["video_encoder"]
    preset = options["video_preset"]
    cmd = [str(backend._executable("ffmpeg.exe")), "-hide_banner", "-loglevel", "warning",
           "-nostdin", "-n", "-nostats", "-progress", "pipe:1", "-i", str(source)]
    if audio:
        cmd += ["-i", str(audio)]
    cmd += ["-map", "0:v:0", "-map", "1:a:0" if audio else "0:a:0?",
            "-c:v", encoder]
    if encoder == "libx264":
        cmd += ["-preset", preset, "-crf", "20"]
    elif encoder == "h264_nvenc":
        # p7 is NVENC's highest quality preset; names from x264 do not apply.
        cmd += ["-preset", "p7" if preset in {"slow", "slower", "veryslow"} else "p4", "-cq", "20", "-b:v", "0"]
    else:
        cmd += ["-preset", "veryslow" if preset in {"slower", "veryslow"} else "medium", "-global_quality", "20"]
    return cmd + ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p",
                  "-c:a", "libmp3lame", "-q:a", "2", "-movflags", "+faststart", str(output)]


def _produce(number, title, runner, settings, get_sources) -> Path:
    name = Path(scene_output_name(number, title)).with_suffix(".mp4").name
    runner.check_cancelled()
    settings = _options(settings)
    backend._executable("ffmpeg.exe")
    folder = backend.app_dir() / "Downloads"
    work = None
    try:
        folder.mkdir(exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=".gui-yt-dlp-", dir=folder))
        source, audio = get_sources(work)
        output = work / "converted.mp4"
        runner.emit("status", "프로젝터용 H.264 / MP3 영상 변환 중…")
        runner.emit("progress", None)
        runner.emit("log", f"FFmpeg: {settings['video_encoder']} / {settings['video_preset']} + libmp3lame VBR 2 · 원본 파일 보존")
        runner.run(video_command(source, audio, output, settings), cwd=work)
        if not output.is_file() or not output.stat().st_size:
            raise backend.AppError("FFmpeg가 영상 파일을 만들지 못했습니다.")
        runner.check_cancelled()
        final = backend._publish_unique(output, folder, name, runner)
        try:
            backend._cleanup_work_dir(work, folder)
        except (OSError, backend.AppError):
            runner.emit("log", f"임시 파일 정리가 필요합니다: {work}")
        runner.emit("progress", 100)
        runner.emit("status", "프로젝터 영상 변환 완료")
        runner.emit("log", f"저장 완료: {final}")
        return final
    except (OSError, ValueError) as exc:
        detail = f"영상 저장 실패: {exc}"
        if work and work.exists():
            detail += f"\n미완성 파일 보관 위치: {work}"
        raise backend.AppError(detail) from exc
    except backend.AppError as exc:
        detail = str(exc)
        if work and work.exists():
            try:
                has_files = any(path.is_file() for path in work.rglob("*"))
            except OSError:
                has_files = True
            if has_files:
                detail += f"\n미완성 파일 보관 위치: {work}"
            else:
                try:
                    backend._cleanup_work_dir(work, folder)
                except (OSError, backend.AppError):
                    detail += f"\n임시 폴더 정리가 필요합니다: {work}"
        if settings.get("video_encoder", "libx264") != "libx264":
            detail += "\nGPU 인코더를 사용할 수 없다면 앱 설정에서 libx264를 선택하세요."
        raise type(exc)(detail) from exc
    finally:
        runner.progress_duration = None


def download_scene_video(url: str, number: str, title: str, runner: backend.ProcessRunner, settings: dict) -> Path:
    scene_output_name(number, title)
    runner.check_cancelled()
    settings = _options(settings)
    backend._validate_url(url)
    backend._executable("ffmpeg.exe")
    info = backend.fetch_formats(url, runner)
    runner.check_cancelled()
    available = [fmt for fmt in info.video_formats
                 if fmt.kind == "video" and fmt.format_id
                 and fmt.raw.get("vcodec") not in (None, "none")
                 and not fmt.raw.get("has_drm")
                 and fmt.ext.lower() not in {"mhtml", "jpg", "jpeg", "png", "webp"}
                 and fmt.raw.get("protocol") != "mhtml"]
    if not available:
        raise backend.AppError("다운로드 가능한 영상 형식이 없습니다.")
    video = max(available, key=lambda fmt: (_positive_number(fmt.raw.get("height")),
                                          _positive_number(fmt.raw.get("fps")),
                                          _positive_number(fmt.raw.get("tbr"))))
    # Some sites provide only a muxed video, or include unusable/DRM audio-only
    # entries. In those cases keep the selected video's own audio, if present.
    audio_candidates = [fmt for fmt in info.audio_formats
                        if fmt.kind == "audio" and fmt.raw.get("vcodec") in (None, "none")
                        and fmt.raw.get("acodec") not in (None, "none")
                        and not fmt.raw.get("has_drm")]
    audio_info = backend.MediaInfo(info.url, info.title, info.duration, audio_candidates, info.video_formats)
    audio = _select_audio(audio_info, runner) if audio_candidates else None
    runner.emit("log", f"자동 선택: 영상 ID {video.format_id} · {video.resolution}")
    runner.progress_duration = info.duration
    def sources(work):
        return (backend._download_format(info, video, work, runner),
                backend._download_format(info, audio, work, runner) if audio else None)
    return _produce(number, title, runner, settings, sources)


def convert_scene_video(source: Path, number: str, title: str, runner: backend.ProcessRunner, settings: dict) -> Path:
    scene_output_name(number, title)
    runner.check_cancelled()
    settings = _options(settings)
    try:
        source = Path(source).expanduser().resolve(strict=True)
        if not source.is_file() or not source.stat().st_size:
            raise backend.AppError("변환할 영상 파일을 선택하세요.")
    except (OSError, RuntimeError) as exc:
        raise backend.AppError(f"변환할 영상 파일을 읽을 수 없습니다.\n{source}\n{exc}") from exc
    return _produce(number, title, runner, settings, lambda _work: (source, None))
