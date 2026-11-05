"""Korean/English messages selected automatically from the OS UI language."""

from __future__ import annotations

import ctypes
import locale
import sys


def _windows_ui_language() -> int:
    return int(ctypes.windll.kernel32.GetUserDefaultUILanguage())


def detect_language() -> str:
    """Use Windows display language, rather than regional date/number settings."""
    if sys.platform == "win32":
        try:
            return "ko" if _windows_ui_language() & 0x3FF == 0x12 else "en"
        except (AttributeError, OSError):
            pass
    try:
        language = locale.getlocale()[0] or ""
    except (ValueError, TypeError):
        language = ""
    primary = language.lower().replace("-", "_").split("_", 1)[0]
    return "ko" if primary in {"ko", "korean"} else "en"


_language = detect_language()
_english: dict[str, str] = {
    "작업을 취소했습니다.": "Operation cancelled.",
    "실행할 수 없습니다: {name}\n{error}": "Cannot run {name}:\n{error}",
    "{name} 실행 실패 (코드 {code})\n{detail}": "{name} failed (exit code {code})\n{detail}",
    "{name} 파일을 찾을 수 없습니다.\n앱과 같은 폴더에 놓아 주세요:\n{directory}": "Cannot find {name}.\nPlace it beside the application:\n{directory}",
    "올바른 http:// 또는 https:// 동영상 링크를 입력해 주세요.": "Enter a valid http:// or https:// media URL.",
    "경고: {message}": "Warning: {message}",
    "내장 JavaScript 런타임(Deno)을 실행할 수 없습니다.\n앱을 다시 빌드하거나 정상적인 sceneapp.exe로 교체해 주세요.": "The bundled JavaScript runtime (Deno) cannot run.\nRebuild the application or replace it with a working release executable.",
    "재생목록 전체 대신 개별 동영상 링크를 입력해 주세요.": "Enter a single video URL instead of a playlist.",
    "내장 오디오는 제외": "Embedded audio excluded",
    "다운로드할 수 있는 오디오/비디오 형식을 찾지 못했습니다.": "No downloadable audio or video formats were found.",
    "동영상": "Video",
    "동영상 정보와 형식 목록을 불러오는 중…": "Loading media information and formats…",
    "yt-dlp Python 모듈 {version}: 오디오 / 비디오 형식 조회": "yt-dlp Python module {version}: fetching audio / video formats",
    "yt-dlp의 동영상 정보를 해석할 수 없습니다.": "Cannot read the media information returned by yt-dlp.",
    "동영상 정보를 불러오지 못했습니다.\n{error}": "Could not load media information.\n{error}",
    "형식 목록을 불러왔습니다.": "Formats loaded.",
    "비디오": "Video",
    "오디오": "Audio",
    "{kind} 다운로드 중 · ID {format_id}": "Downloading {kind} · ID {format_id}",
    "{kind} 다운로드 · {format_id} / {ext}": "Downloading {kind} · {format_id} / {ext}",
    "선택한 형식 ID {format_id}가 더 이상 제공되지 않습니다. 목록을 다시 조회해 주세요.": "Format ID {format_id} is no longer available. Reload the format list.",
    "남은 시간 {seconds}초": "ETA {seconds}s",
    "{kind} 다운로드 중 · {details}": "Downloading {kind} · {details}",
    "{kind} 다운로드에 실패했습니다.\n{error}": "Could not download {kind}.\n{error}",
    "다운로드된 {kind} 파일을 찾을 수 없습니다.": "Cannot find the downloaded {kind} file.",
    "안전한 임시 폴더인지 확인할 수 없어 정리하지 않았습니다: {directory}": "Temporary folder was not removed because its safety could not be verified: {directory}",
    "저장 파일명에 사용할 수 없는 문자가 있습니다.": "The output filename contains invalid characters.",
    "오디오 또는 비디오를 하나 이상 선택해 주세요.": "Select at least one audio or video format.",
    "비디오 선택이 현재 형식 목록과 일치하지 않습니다. 목록을 다시 불러와 주세요.": "The selected video is no longer in the format list. Reload the list.",
    "오디오 선택이 현재 형식 목록과 일치하지 않습니다. 목록을 다시 불러와 주세요.": "The selected audio is no longer in the format list. Reload the list.",
    "다운로드 폴더에 파일을 쓸 수 없습니다.\n{directory}\n{error}": "Cannot write to the Downloads folder.\n{directory}\n{error}",
    "작업 폴더: {directory}": "Working folder: {directory}",
    "MP4 변환 중…": "Converting to MP4…",
    "MP3 변환 중…": "Converting to MP3…",
    "선택한 스트림을 합치는 중…": "Merging selected streams…",
    "비디오 트랙을 추출하는 중…": "Extracting the video track…",
    "원본 코덱 유지": "Preserving original codecs",
    "FFmpeg가 결과 파일을 만들지 못했습니다.": "FFmpeg did not create an output file.",
    "임시 파일 정리가 필요합니다: {directory}": "Temporary files need cleanup: {directory}",
    "다운로드 완료": "Download complete",
    "저장 완료: {path}": "Saved: {path}",
    "{error}\n\n다운로드한 파일 / 미완성 파일은 여기에 보관했습니다:\n{directory}": "{error}\n\nDownloaded / partial files were kept here:\n{directory}",
    "\n임시 폴더 정리가 필요합니다: {directory}": "\nTemporary folder needs cleanup: {directory}",
    "음향 번호를 소수점 제외 1~12자리 숫자로 입력해 주세요. (예: 13.5)": "Enter a cue number with 1–12 digits, excluding the decimal point (for example, 13.5).",
    "저장할 음향 제목을 입력해 주세요.": "Enter a title for the audio file.",
    "오디오 전용(audio only) 형식이 없습니다. 다른 링크를 입력해 주세요.": "No audio-only format is available. Try another URL.",
    "자동 선택: 오디오 전용 ID {format_id} · {bitrate:g} kbps (표시된 비트레이트 중 최고)": "Auto-selected: audio-only ID {format_id} · {bitrate:g} kbps (highest reported bitrate)",
    "일부 형식은 비트레이트 정보가 없어 수치가 있는 형식끼리 비교했습니다.": "Some formats have no bitrate information; only formats with reported bitrates were compared.",
    "모든 오디오 전용 형식에 비트레이트 정보가 없어 샘플레이트·파일 크기 기준으로 ID {format_id}를 선택했습니다.": "No audio-only format reports a bitrate; selected ID {format_id} by sample rate and file size.",
    "저장 파일명: {name}": "Output filename: {name}",
    "변환할 음원 파일이 없거나 비어 있습니다. 파일을 다시 선택해 주세요.": "The input audio file is missing or empty. Select another file.",
    "음원 파일을 읽을 수 없습니다.\n{path}\n{error}": "Cannot read the audio file.\n{path}\n{error}",
    "원본 음원: {path}": "Source audio: {path}",
    "외부 음원을 MP3로 변환 중…": "Converting the local audio file to MP3…",
    "FFmpeg: MP3 (libmp3lame, VBR 2) · 원본 파일 보존": "FFmpeg: MP3 (libmp3lame, VBR 2) · source file preserved",
    "FFmpeg가 MP3 결과 파일을 만들지 못했습니다.": "FFmpeg did not create an MP3 output file.",
    "MP3 변환 완료": "MP3 conversion complete",
    "\n\n미완성 파일은 여기에 보관했습니다:\n{directory}": "\n\nPartial files were kept here:\n{directory}",
}


def get_language() -> str:
    return _language


def set_language(language: str) -> None:
    """Set the process language; used by tests and in-process integrations."""
    if language not in {"ko", "en"}:
        raise ValueError("language must be 'ko' or 'en'")
    global _language
    _language = language


def register_translations(translations: dict[str, str]) -> None:
    """Add another module's English messages without changing its source text."""
    _english.update(translations)


def tr(korean_template: str, **kwargs: object) -> str:
    template = _english.get(korean_template, korean_template) if _language == "en" else korean_template
    return template.format(**kwargs) if kwargs else template
