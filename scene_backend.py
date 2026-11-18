"""SCENE's one-step audio download and local-file MP3 conversion services."""

from __future__ import annotations

from os import SEEK_END
from pathlib import Path
import re
import tempfile
import wave

import backend
from i18n import tr


def is_midi_source(source: str | Path) -> bool:
    return Path(source).suffix.lower() in {".mid", ".midi"}


def scene_output_name(number: str, title: str) -> str:
    """Keep integer/decimal cue text, with at most 12 digits excluding the dot."""
    number = number.strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", number) or len(number.replace(".", "")) > 12:
        raise backend.AppError(tr("음향 번호를 소수점 제외 1~12자리 숫자로 입력해 주세요. (예: 13.5)"))
    title = title.strip()
    if not title:
        raise backend.AppError(tr("저장할 음향 제목을 입력해 주세요."))
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title)
    title = re.sub(r"\s+", " ", title).strip(" .")
    if not title:
        raise backend.AppError(tr("저장할 음향 제목을 입력해 주세요."))
    # Leave room for the working directory and a duplicate-name suffix even
    # on Windows systems without long-path support. Count UTF-16 code units.
    prefix = f"bgm{number}_"
    budget = 120 - len(prefix) - len(".mp3")
    title = title.encode("utf-16-le", errors="replace")[:budget * 2].decode("utf-16-le", errors="ignore").rstrip(" .")
    return f"{prefix}{title}.mp3"


def _positive_number(value: object) -> float:
    number = backend._number(value)
    return number if number is not None and number > 0 else 0.0


def _audio_bitrate(fmt: backend.MediaFormat) -> float:
    return _positive_number(fmt.raw.get("abr")) or _positive_number(fmt.raw.get("tbr"))


def _select_audio(info: backend.MediaInfo, runner: backend.ProcessRunner) -> backend.MediaFormat:
    candidates = [fmt for fmt in info.audio_formats
                  if fmt.kind == "audio" and fmt.raw.get("vcodec") in (None, "none")
                  and not fmt.raw.get("has_drm")]
    if not candidates:
        raise backend.AppError(tr("오디오 전용(audio only) 형식이 없습니다. 다른 링크를 입력해 주세요."))
    selected = max(candidates, key=lambda fmt: (
        _audio_bitrate(fmt), _positive_number(fmt.raw.get("asr")),
        _positive_number(fmt.raw.get("filesize")) or _positive_number(fmt.raw.get("filesize_approx")),
    ))
    bitrate = _audio_bitrate(selected)
    if bitrate:
        runner.emit("log", tr("자동 선택: 오디오 전용 ID {format_id} · {bitrate:g} kbps (표시된 비트레이트 중 최고)", format_id=selected.format_id, bitrate=bitrate))
        if any(not _audio_bitrate(fmt) for fmt in candidates):
            runner.emit("log", tr("일부 형식은 비트레이트 정보가 없어 수치가 있는 형식끼리 비교했습니다."))
    else:
        runner.emit("log", tr("모든 오디오 전용 형식에 비트레이트 정보가 없어 샘플레이트·파일 크기 기준으로 ID {format_id}를 선택했습니다.", format_id=selected.format_id))
    return selected


def download_scene_audio(url: str, number: str, title: str, runner: backend.ProcessRunner) -> Path:
    """Fetch once, choose the highest reported audio-only bitrate, then Make MP3."""
    output_name = scene_output_name(number, title)
    runner.check_cancelled()
    backend._validate_url(url)
    backend._executable("ffmpeg.exe")
    info = backend.fetch_formats(url, runner)
    runner.check_cancelled()
    audio = _select_audio(info, runner)
    runner.emit("log", tr("저장 파일명: {name}", name=output_name))
    return backend.download_media(info, None, audio, True, False, False, runner,
                                  output_name=output_name)


def _read_local_audio(source: Path) -> Path:
    try:
        source = Path(source).expanduser().resolve(strict=True)
        if not source.is_file() or not source.stat().st_size:
            raise backend.AppError(tr("변환할 음원 파일이 없거나 비어 있습니다. 파일을 다시 선택해 주세요."))
    except (OSError, RuntimeError) as exc:
        raise backend.AppError(tr("음원 파일을 읽을 수 없습니다.\n{path}\n{error}", path=source, error=exc)) from exc
    return source


def _validate_midi_chunks(source: Path) -> None:
    # FluidSynth can return a short, silent WAV if the declared track is missing.
    invalid = backend.AppError(tr("MIDI 파일이 손상되었거나 형식이 올바르지 않습니다.\n{path}", path=source))
    with source.open("rb") as midi:
        file_size = midi.seek(0, SEEK_END)
        midi.seek(0)
        header = midi.read(14)
        header_size = int.from_bytes(header[4:8], "big")
        tracks_remaining = int.from_bytes(header[10:12], "big")
        if len(header) != 14 or header[:4] != b"MThd" or header_size < 6 or not tracks_remaining:
            raise invalid
        midi.seek(8 + header_size)
        while tracks_remaining:
            chunk = midi.read(8)
            chunk_size = int.from_bytes(chunk[4:], "big")
            end = midi.tell() + chunk_size
            if len(chunk) != 8 or end > file_size:
                raise invalid
            if chunk[:4] == b"MTrk":
                if chunk_size < 4:
                    raise invalid
                tracks_remaining -= 1
            midi.seek(end)


def _render_midi(source: Path, destination: Path, runner: backend.ProcessRunner) -> Path:
    runner.check_cancelled()
    _validate_midi_chunks(source)
    runtime = backend.app_dir() / "vendor" / "fluidsynth"
    synth = runtime / "fluidsynth.exe"
    soundfont = runtime / "FluidR3_GM.sf3"
    for path in (synth, soundfont):
        if not path.is_file():
            raise backend.AppError(tr("내장 MIDI 구성 요소를 찾을 수 없습니다.\n{path}", path=path))
    if destination.exists() or destination.is_symlink():
        raise backend.AppError(tr("MIDI 임시 파일이 이미 있습니다.\n{path}", path=destination))

    runner.emit("status", tr("FluidR3 음색으로 MIDI 합성 중…"))
    runner.emit("progress", None)
    command = [str(synth), "-n", "-i", "-F", str(destination), "-T", "wav", "-O", "s16",
               "-r", "44100", "-o", "synth.dynamic-sample-loading=1", str(soundfont), str(source)]
    # FluidSynth automatically loads configuration from these Windows folders.
    # Omit them only in this child so installed configs cannot replace FluidR3.
    lines = runner.run(command, cwd=destination.parent, without_env=("USERPROFILE", "PROGRAMDATA"))
    runner.check_cancelled()
    # Some FluidSynth render failures are reported only on stderr, with exit 0.
    errors = [line for line in lines if line.startswith(("fluidsynth: error:", "fluidsynth: panic:"))]
    if errors:
        raise backend.AppError(tr("FluidSynth로 MIDI를 합성할 수 없습니다.\n{error}", error="\n".join(errors[-16:])))
    try:
        with wave.open(str(destination), "rb") as rendered:
            if (rendered.getnframes() and rendered.getnchannels() == 2
                    and rendered.getsampwidth() == 2 and rendered.getframerate() == 44100):
                return destination
    except (OSError, EOFError, wave.Error):
        pass
    raise backend.AppError(tr("FluidSynth가 재생할 수 있는 WAV 파일을 만들지 못했습니다."))


def render_midi_preview(source: Path, destination: Path, runner: backend.ProcessRunner) -> Path:
    """Render MIDI to a fresh WAV in the preview player's temporary directory."""
    runner.check_cancelled()
    if not is_midi_source(source):
        raise backend.AppError(tr("미리 들을 MIDI 파일(.mid, .midi)을 선택해 주세요."))
    try:
        return _render_midi(_read_local_audio(source), Path(destination).absolute(), runner)
    except OSError as exc:
        raise backend.AppError(tr("FluidSynth로 MIDI를 합성할 수 없습니다.\n{error}", error=exc)) from exc


def convert_scene_file(source: Path, number: str, title: str, runner: backend.ProcessRunner) -> Path:
    """Convert a local media file using the original Make MP3 codec settings."""
    output_name = scene_output_name(number, title)
    runner.check_cancelled()
    midi = is_midi_source(source)
    source = _read_local_audio(source)
    backend._executable("ffmpeg.exe")
    downloads = backend.app_dir() / "Downloads"
    try:
        downloads.mkdir(exist_ok=True)
        work_dir = Path(tempfile.mkdtemp(prefix=".gui-yt-dlp-", dir=downloads))
    except OSError as exc:
        raise backend.AppError(tr("다운로드 폴더에 파일을 쓸 수 없습니다.\n{directory}\n{error}", directory=downloads, error=exc)) from exc
    runner.emit("log", tr("원본 음원: {path}", path=source))
    runner.emit("log", tr("작업 폴더: {directory}", directory=work_dir))
    try:
        audio_input = _render_midi(source, work_dir / "rendered.wav", runner) if midi else source
        converted = work_dir / "converted.mp3"
        runner.emit("status", tr("외부 음원을 MP3로 변환 중…"))
        runner.emit("progress", None)
        runner.emit("log", tr("FFmpeg: MP3 (libmp3lame, VBR 2) · 원본 파일 보존"))
        runner.progress_duration = None
        runner.run(backend._ffmpeg_command(None, audio_input, converted, True, False, False), cwd=work_dir)
        if not converted.is_file() or not converted.stat().st_size:
            raise backend.AppError(tr("FFmpeg가 MP3 결과 파일을 만들지 못했습니다."))
        runner.check_cancelled()
        final_path = backend._publish_unique(converted, downloads, output_name, runner)
        try:
            backend._cleanup_work_dir(work_dir, downloads)
        except (OSError, backend.AppError):
            runner.emit("log", tr("임시 파일 정리가 필요합니다: {directory}", directory=work_dir))
        runner.emit("progress", 100.0)
        runner.emit("status", tr("MP3 변환 완료"))
        runner.emit("log", tr("저장 완료: {path}", path=final_path))
        return final_path
    except (backend.AppError, OSError) as exc:
        try:
            has_files = any(path.is_file() for path in work_dir.rglob("*"))
        except OSError:
            has_files = True
        message = str(exc)
        if has_files:
            message += tr("\n\n미완성 파일은 여기에 보관했습니다:\n{directory}", directory=work_dir)
        else:
            try:
                backend._cleanup_work_dir(work_dir, downloads)
            except (OSError, backend.AppError):
                message += tr("\n임시 폴더 정리가 필요합니다: {directory}", directory=work_dir)
        if isinstance(exc, backend.Cancelled):
            raise backend.Cancelled(message) from exc
        raise backend.AppError(message) from exc
    finally:
        runner.progress_duration = None
