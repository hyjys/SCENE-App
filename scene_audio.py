"""Stage cue list, Windows audio transport, and cancellable Tk volume fades.

The transport changes this application's stream volume, never the system mixer.
All transport and Tk callbacks stay on the Tk thread. No playback subprocess is
required on Windows; a failed codec reports a useful error instead of skipping a cue.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
import ctypes
import hashlib
import json
import math
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Callable
import uuid

import customtkinter as ctk

from backend import AppError, app_dir
from ui_theme import ACCENT, BACKGROUND, button, font, label


AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a", ".aac", ".wma", ".flac", ".ogg", ".opus", ".aif", ".aiff"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".m4v", ".avi", ".mov", ".mkv", ".wmv", ".webm"})
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
CUE_SETTINGS_FILE = ".scene-audio.json"


def cue_number(path: Path | str) -> Decimal | None:
    match = re.match(r"^bgm\s*([0-9]+(?:\.[0-9]+)?)(?:_|\s|$)", Path(path).stem, re.IGNORECASE)
    return Decimal(match.group(1)) if match else None


def cue_sort_key(path: Path | str) -> tuple:
    path = Path(path)
    number = cue_number(path)
    # Type-tag every natural component so arbitrary filenames remain comparable.
    natural = tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                    for part in re.split(r"([0-9]+)", path.name))
    return (number is None, number if number is not None else Decimal(0), natural)


def list_media(folder: Path) -> list[Path]:
    """List each directory's cues before its alphabetically ordered subfolders.

    Linked directories are not followed: a junction back to a show's parent must
    not duplicate its cues or recurse forever.
    """
    def visit(directory: Path) -> list[Path]:
        try:
            entries = list(directory.iterdir())
            tracks = sorted((p for p in entries if p.suffix.lower() in MEDIA_EXTENSIONS and p.is_file()),
                            key=lambda p: (cue_sort_key(p), p.name))
            children = sorted((p for p in entries if p.is_dir() and not p.is_symlink()
                               and not getattr(p, "is_junction", lambda: False)()),
                              key=lambda p: (p.name.casefold(), p.name))
        except OSError as exc:
            raise AppError(f"음원 폴더를 읽을 수 없습니다.\n{directory}\n{exc}") from exc
        for child in children:
            tracks.extend(visit(child))
        return tracks

    return visit(Path(folder))


def _number(value: object, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise AppError(f"{name}: 숫자를 입력하세요.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AppError(f"{name}: 숫자를 입력하세요.") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise AppError(f"{name}: {minimum:g}~{maximum:g} 범위로 입력하세요.")
    return result


@dataclass(frozen=True)
class TrackSettings:
    default_volume: float = 100
    fade_in_seconds: float = 3
    fade_in_from: float = 0
    fade_in_to: float = 100
    fade_out_seconds: float = 3
    fade_out_from: float = 100
    fade_out_to: float = 0

    @classmethod
    def from_dict(cls, data: dict | None = None, defaults: TrackSettings | None = None) -> TrackSettings:
        values = asdict(defaults or cls())
        if isinstance(data, dict):
            for key in values:
                if key in data:
                    values[key] = _number(data[key], key, 0, 600 if key.endswith("seconds") else 100)
        return cls(**values)


class MciPlayer:
    """Small Unicode MCI digital-video transport (including MP3 and WAV audio)."""

    def __init__(self) -> None:
        self.alias = "scene_" + uuid.uuid4().hex
        self.path: Path | None = None
        self.duration = 0.0
        self._winmm = None
        self.prepared_paths: dict[Path, Path] = {}

    def _send(self, command: str) -> str:
        if sys.platform != "win32":
            raise AppError("무대 음원 재생은 Windows에서 지원됩니다.")
        if self._winmm is None:
            self._winmm = ctypes.WinDLL("winmm")
            self._winmm.mciSendStringW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
            self._winmm.mciSendStringW.restype = ctypes.c_uint
            self._winmm.mciGetErrorStringW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
            self._winmm.mciGetErrorStringW.restype = ctypes.c_int
        buffer = ctypes.create_unicode_buffer(1024)
        code = self._winmm.mciSendStringW(command, buffer, len(buffer), None)
        if code:
            error = ctypes.create_unicode_buffer(1024)
            self._winmm.mciGetErrorStringW(code, error, len(error))
            raise AppError(f"음원 재생 오류: {error.value or code}\nMP3/WAV로 변환 후 다시 시도하세요.")
        return buffer.value

    def open(self, path: Path) -> None:
        path = Path(path).resolve()
        if not path.is_file():
            raise AppError(f"음원 파일을 찾을 수 없습니다.\n{path}")
        self.close()
        playback_path = self.prepared_paths.get(path, path)
        self._send(f'open "{playback_path}" type mpegvideo alias {self.alias}')
        self.path = path
        try:
            self._send(f"set {self.alias} time format milliseconds")
            self.duration = int(self._send(f"status {self.alias} length")) / 1000
        except Exception:
            self.close()
            raise

    def play(self) -> None:
        if self.path:
            self._send(f"play {self.alias}")

    def pause(self) -> None:
        if self.path:
            self._send(f"pause {self.alias}")

    def stop(self) -> None:
        if self.path:
            self._send(f"stop {self.alias}")
            self._send(f"seek {self.alias} to start")

    def seek(self, seconds: float, playing: bool = False) -> None:
        if self.path:
            point = int(max(0, min(self.duration, seconds)) * 1000)
            self._send(f"seek {self.alias} to {point}")
            if playing:
                self.play()

    def set_volume(self, percent: float) -> None:
        if self.path:
            self._send(f"setaudio {self.alias} volume to {round(max(0, min(100, percent)) * 10)}")

    def position(self) -> float:
        return int(self._send(f"status {self.alias} position")) / 1000 if self.path else 0

    def mode(self) -> str:
        return self._send(f"status {self.alias} mode") if self.path else "stopped"

    def close(self) -> None:
        if self.path:
            try:
                self._send(f"close {self.alias}")
            except AppError:
                # Device removal must not prevent application shutdown.
                pass
            finally:
                self.path = None
                self.duration = 0


class AudioPreparation:
    """Prepare PCM in a worker, since Windows MCI misreports VBR MP3 timelines.

    A per-session cache avoids modifying sources or accumulating a permanent copy
    of an entire show. Messages are consumed by Tk; the worker never calls Tk.
    """

    def __init__(self) -> None:
        self.events: queue.Queue[tuple[Path, Path | None, str]] = queue.Queue()
        self._jobs: queue.PriorityQueue = queue.PriorityQueue()
        self._counter = 0
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._paths: dict[Path, Path] = {}
        self._signatures: dict[Path, tuple[int, int]] = {}
        self._queued: set[Path] = set()
        self._running: Path | None = None
        self._process: subprocess.Popen | None = None
        self._directory = Path(tempfile.mkdtemp(prefix="sceneapp-audio-"))
        self._worker = threading.Thread(target=self._run, name="scene-audio-cache", daemon=True)
        self._worker.start()

    def cached(self, path: Path) -> Path | None:
        path = path.resolve()
        # PCM WAV already has an accurate native timeline and needs no copy.
        if path.suffix.lower() == ".wav":
            return path
        with self._lock:
            cached = self._paths.get(path)
            signature = self._signatures.get(path)
        try:
            source = path.stat()
            unchanged = signature == (source.st_mtime_ns, source.st_size)
        except OSError:
            unchanged = False
        return cached if cached and cached.is_file() and unchanged else None

    def request(self, path: Path, *, urgent: bool = False) -> None:
        path = path.resolve()
        cached = self.cached(path)
        if cached:
            self.events.put((path, cached, ""))
            return
        with self._lock:
            if self._closed.is_set() or path == self._running:
                return
            if path in self._queued and not urgent:
                return
            self._queued.add(path)
            self._counter += 1
            self._jobs.put((0 if urgent else 10, self._counter, path))

    def _run(self) -> None:
        try:
            while not self._closed.is_set():
                try:
                    _priority, _counter, path = self._jobs.get(timeout=.2)
                except queue.Empty:
                    continue
                with self._lock:
                    self._queued.discard(path)
                    self._running = path
                if self.cached(path):
                    with self._lock:
                        self._running = None
                    continue
                result = None
                error = ""
                output = None
                try:
                    source = path.stat()
                    signature = (source.st_mtime_ns, source.st_size)
                    identity = str(path) + repr(signature)
                    output = self._directory / (hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".wav")
                    executable = app_dir() / "ffmpeg.exe"
                    if not executable.is_file():
                        raise AppError(f"음원 준비에 필요한 ffmpeg.exe를 찾을 수 없습니다.\n{executable}")
                    command = [str(executable), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(path),
                               "-map", "0:a:0", "-vn", "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2", str(output)]
                    # A temporary diagnostic file avoids a full PIPE or unbounded
                    # stderr memory if a damaged input repeats decoder messages.
                    with tempfile.TemporaryFile() as diagnostics:
                        with self._lock:
                            if self._closed.is_set():
                                break
                            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=diagnostics,
                                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                            self._process = process
                        code = process.wait()
                        diagnostics.seek(0)
                        detail = diagnostics.read(4096).decode("utf-8", errors="replace").strip()
                    if code or not output.is_file() or output.stat().st_size <= 44:
                        raise AppError(f"음원을 준비하지 못했습니다: {path.name}\n{detail or '오디오 트랙을 확인하세요.'}")
                    result = output
                    with self._lock:
                        self._paths[path] = output
                        self._signatures[path] = signature
                except (OSError, AppError) as exc:
                    error = str(exc)
                    if output:
                        try:
                            output.unlink(missing_ok=True)
                        except OSError:
                            pass
                finally:
                    with self._lock:
                        self._process = None
                        self._running = None
                if not self._closed.is_set():
                    self.events.put((path, result, error))
        finally:
            # Only exact files made by this instance are removed. No recursive
            # deletion, folder glob from user input, or source paths are involved.
            for output in self._directory.iterdir():
                try:
                    output.unlink()
                except OSError:
                    pass
            try:
                self._directory.rmdir()
            except OSError:
                pass

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                try:
                    self._process.terminate()
                except OSError:
                    pass


class AudioTransport:
    """Single-track transport whose fades are invalidated by later operator input."""

    def __init__(self, scheduler, player=None, *, clock: Callable[[], float] = time.monotonic,
                 on_change: Callable[[], None] | None = None,
                 on_error: Callable[[Exception], None] | None = None) -> None:
        self.scheduler = scheduler
        self.player = player or MciPlayer()
        self.clock = clock
        self.on_change = on_change or (lambda: None)
        self.on_error = on_error
        self.path: Path | None = None
        self.state = "stopped"
        self.volume = 100.0
        self._fade_id = None
        self._generation = 0

    def cancel_fade(self) -> None:
        self._generation += 1
        if self._fade_id is not None:
            try:
                self.scheduler.after_cancel(self._fade_id)
            except tk.TclError:
                pass
            self._fade_id = None

    def _apply_volume(self, value: float) -> None:
        self.player.set_volume(value)
        self.volume = value
        self.on_change()

    def set_volume(self, value: float) -> None:
        value = _number(value, "볼륨", 0, 100)
        self.cancel_fade()
        self._apply_volume(value)

    def play(self, path: Path | None = None, volume: float | None = None) -> None:
        self.cancel_fade()
        if path is not None and Path(path).resolve() != self.path:
            self.path = None
            self.state = "stopped"
            self.player.open(Path(path))
            self.path = Path(path).resolve()
        if self.path is None:
            raise AppError("재생할 음원을 선택하세요.")
        if volume is not None:
            self._apply_volume(_number(volume, "볼륨", 0, 100))
        if self.state == "stopped":
            self.player.seek(0)
        self.player.play()
        self.state = "playing"
        self.on_change()

    def pause(self) -> None:
        self.cancel_fade()
        if self.path and self.state == "playing":
            self.player.pause()
            self.state = "paused"
            self.on_change()

    def stop(self) -> None:
        self.cancel_fade()
        self.player.stop()
        self.state = "stopped"
        self.on_change()

    def seek(self, seconds: float) -> None:
        if self.path:
            self.player.seek(_number(seconds, "재생 위치", 0, self.player.duration), self.state == "playing")

    def fade(self, start: float, end: float, seconds: float, *, stop_at_zero: bool = False) -> None:
        start = _number(start, "시작 볼륨", 0, 100)
        end = _number(end, "종료 볼륨", 0, 100)
        seconds = _number(seconds, "페이드 시간", 0, 600)
        if self.path is None:
            raise AppError("페이드할 음원을 먼저 재생하세요.")
        self.cancel_fade()
        self._apply_volume(start)
        generation, started = self._generation, self.clock()

        def tick() -> None:
            if generation != self._generation:
                return
            self._fade_id = None
            try:
                fraction = min(1.0, max(0.0, (self.clock() - started) / seconds)) if seconds else 1.0
                self._apply_volume(start + (end - start) * fraction)
                if fraction < 1:
                    self._fade_id = self.scheduler.after(30, tick)
                elif stop_at_zero and end == 0:
                    self.stop()
            except Exception as exc:
                self.cancel_fade()
                if self.on_error:
                    self.on_error(exc)
                else:
                    raise

        tick()

    def close(self) -> None:
        self.cancel_fade()
        self.player.close()
        self.path = None
        self.state = "stopped"


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class StageAudioFrame(ctk.CTkFrame):
    """Local stage media list; constructor does not open a device or folder dialog."""

    def __init__(self, parent, settings: dict, on_video=None, on_error=None, **kwargs) -> None:
        super().__init__(parent, fg_color="white", corner_radius=12, **kwargs)
        self.on_video = on_video
        self.on_video_action = None
        self.video_status = None
        self.on_error = on_error
        self.folder: Path | None = None
        self.tracks: list[Path] = []
        self.selected: Path | None = None
        self.overrides: dict[str, dict] = {}
        self._rows: dict[Path, ctk.CTkFrame] = {}
        self._folder_groups: dict[Path, tuple[ctk.CTkButton, ctk.CTkFrame]] = {}
        self._expanded_folders: set[Path] = set()
        self._closed = False
        self._poll_id = None
        self._video_active = False
        self._video_path: Path | None = None
        self._pending: tuple[str, Path, float | None] | None = None
        self._preparation = AudioPreparation()
        self.update_settings(settings)
        self.transport = AudioTransport(self, on_change=self._refresh_transport, on_error=self._error)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
        top.columnconfigure(0, weight=1)
        label(top, text="음향 제어반", size=20, bold=True).grid(row=0, column=0, sticky="w")
        button(top, text="폴더 선택", compact=True, command=self._choose_folder).grid(row=0, column=1)
        button(top, text="새로고침", compact=True, command=self._reload).grid(row=0, column=2, padx=(6, 0))
        self.folder_var = tk.StringVar(self, "음원은 BGM 번호순, 하위 폴더는 이름순으로 표시합니다.")
        label(self, textvariable=self.folder_var, muted=True, wraplength=430).grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        self.list_frame = ctk.CTkScrollableFrame(self, fg_color=BACKGROUND, corner_radius=8)
        self.list_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self.list_frame.columnconfigure(0, weight=1)
        self._empty = label(self.list_frame, text="음원 / 영상 폴더를 선택하세요. 하위 폴더도 함께 불러옵니다.", muted=True, wraplength=400)
        self._empty.grid(row=0, column=0, padx=12, pady=20)
        current = ctk.CTkFrame(self, fg_color="#eaf1fc", corner_radius=8)
        current.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))
        current.columnconfigure(0, weight=1)
        self.current_var = tk.StringVar(self, "현재 재생 · 선택한 음원 없음")
        label(current, textvariable=self.current_var, bold=True, wraplength=430).grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
        button(current, text="음원 설정", compact=True, command=self._settings_selected).grid(row=0, column=1, padx=(4, 10), pady=(8, 0))
        self.seek_slider = ctk.CTkSlider(current, from_=0, to=1, command=self._seek, height=16)
        self.seek_slider.set(0)
        self.seek_slider.grid(row=1, column=0, columnspan=2, sticky="ew", padx=14, pady=(4, 0))
        self.time_var = tk.StringVar(self, "0:00 / 0:00")
        label(current, textvariable=self.time_var, muted=True, size=12).grid(row=2, column=0, columnspan=2, sticky="e", padx=14)
        controls = ctk.CTkFrame(current, fg_color="transparent")
        controls.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=(2, 6))
        for col, (text, action) in enumerate((("페이드↑", "fade_in"), ("▶", "play"), ("Ⅱ", "pause"), ("■", "stop"), ("페이드↓", "fade_out"))):
            controls.columnconfigure(col, weight=1)
            control = button(controls, text=text, compact=True, command=lambda a=action: self._run(a))
            control.configure(width=46)
            control.grid(row=0, column=col, sticky="ew", padx=2)
        volume = ctk.CTkFrame(current, fg_color="transparent")
        volume.grid(row=4, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 10))
        volume.columnconfigure(1, weight=1)
        self.volume_var = tk.StringVar(self, "100%")
        label(volume, textvariable=self.volume_var, size=12).grid(row=0, column=0, padx=(0, 8))
        self.volume_slider = ctk.CTkSlider(volume, from_=0, to=100, command=self._volume)
        self.volume_slider.set(100)
        self.volume_slider.grid(row=0, column=1, sticky="ew")
        self._poll_id = self.after(200, self._poll)
        initial_folder = settings.get("audio_folder", "")
        if initial_folder:
            try:
                self.load_folder(Path(initial_folder))
            except AppError as exc:
                self.folder_var.set(str(exc))

    def update_settings(self, settings: dict) -> None:
        audio = settings.get("audio", settings)
        self.defaults = TrackSettings.from_dict(audio)

    def _error(self, error: Exception) -> None:
        if self.on_error:
            self.on_error(str(error))
        elif not self._closed:
            messagebox.showerror("음향 제어", str(error), parent=self.winfo_toplevel())

    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self.winfo_toplevel(), title="무대 음원 / 영상 폴더", initialdir=str(self.folder) if self.folder else None)
        if folder:
            try:
                self.load_folder(Path(folder))
            except AppError as exc:
                self._error(exc)

    def _reload(self) -> None:
        if self.folder:
            try:
                self.load_folder(self.folder)
            except AppError as exc:
                self._error(exc)

    def load_folder(self, folder: Path) -> None:
        folder = Path(folder).resolve()
        tracks = list_media(folder)
        overrides: dict[str, dict] = {}
        for directory in sorted({folder, *(path.parent for path in tracks)}):
            for name, data in self._read_directory_settings(directory).items():
                overrides[(directory.relative_to(folder) / name).as_posix()] = data
        if self.folder != folder:
            self._expanded_folders.clear()
        self.folder, self.tracks, self.overrides = folder, tracks, overrides
        if self.selected not in tracks:
            self.selected = None
        self._pending = None
        self.folder_var.set(f"{folder} · {len(tracks)}개")
        for path in tracks:
            if path.suffix.lower() in AUDIO_EXTENSIONS:
                self._preparation.request(path)
        for child in self.list_frame.winfo_children():
            child.destroy()
        self._rows.clear()
        self._folder_groups.clear()
        if not tracks:
            label(self.list_frame, text="지원하는 음원 / 영상 파일이 없습니다.", muted=True).grid(row=0, column=0, padx=12, pady=20)
        grouped: dict[Path, list[Path]] = {folder: []}
        for path in tracks:
            grouped.setdefault(path.parent, []).append(path)
            directory = path.parent
            while directory != folder:
                grouped.setdefault(directory, [])
                directory = directory.parent
        children: dict[Path, list[Path]] = {directory: [] for directory in grouped}
        for directory in grouped:
            if directory != folder:
                children[directory.parent].append(directory)
        self._expanded_folders.intersection_update(grouped)

        def render(directory: Path, parent) -> None:
            for index, path in enumerate(grouped[directory]):
                self._make_track_row(parent, index, path)
            index = len(grouped[directory])
            for child in sorted(children[directory], key=lambda p: (p.name.casefold(), p.name)):
                expanded = child in self._expanded_folders
                header = button(parent, text=f"{'▼' if expanded else '▶'} {child.name}", compact=True,
                                anchor="w", command=lambda p=child: self._toggle_folder(p))
                header.grid(row=index, column=0, sticky="ew", pady=(6, 3))
                body = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
                body.grid(row=index + 1, column=0, sticky="ew", padx=(14, 0))
                body.columnconfigure(0, weight=1)
                self._folder_groups[child] = (header, body)
                render(child, body)
                if not expanded:
                    body.grid_remove()
                index += 2

        render(folder, self.list_frame)
        self._highlight_selected()

    def _make_track_row(self, parent, index: int, path: Path) -> None:
        row = ctk.CTkFrame(parent, fg_color="white", corner_radius=6)
        row.grid(row=index, column=0, sticky="ew", pady=3)
        row.columnconfigure(0, weight=1)
        name = ("영상 · " if path.suffix.lower() in VIDEO_EXTENSIONS else "") + path.stem
        title = label(row, text=name, bold=True, wraplength=230)
        title.grid(row=0, column=0, sticky="ew", padx=(10, 4), pady=10)
        tools = ctk.CTkFrame(row, fg_color="transparent")
        tools.grid(row=0, column=1, sticky="e", padx=(0, 6), pady=8)
        for col, (text, action) in enumerate((("페이드↑", "fade_in"), ("▶", "play"), ("Ⅱ", "pause"), ("■", "stop"), ("페이드↓", "fade_out"))):
            tools.columnconfigure(col, weight=1)
            control = button(tools, text=text, compact=True, command=lambda a=action, p=path: self._run(a, p))
            control.configure(width=40 if action in {"fade_in", "fade_out"} else 28)
            control.grid(row=0, column=col, sticky="ew", padx=2)
        row.bind("<Configure>", lambda event, target=title: target.configure(wraplength=max(65, event.width - 250)), add="+")
        for widget in (row, title):
            widget.bind("<Button-1>", lambda _event, p=path: self._select(p), add="+")
            widget.bind("<Double-Button-1>", lambda _event, p=path: self._run("play", p), add="+")
            widget.bind("<Button-3>", lambda event, p=path: self._context(event, p), add="+")
        self._rows[path] = row

    def _toggle_folder(self, directory: Path) -> None:
        header, body = self._folder_groups[directory]
        if directory in self._expanded_folders:
            self._expanded_folders.remove(directory)
            body.grid_remove()
            header.configure(text=f"▶ {directory.name}")
        else:
            self._expanded_folders.add(directory)
            body.grid()
            header.configure(text=f"▼ {directory.name}")

    def _select(self, path: Path) -> None:
        self.selected = path
        for directory in reversed(path.parents):
            if directory in self._folder_groups and directory not in self._expanded_folders:
                self._toggle_folder(directory)
        self._highlight_selected()
        self._refresh_transport()

    def _highlight_selected(self) -> None:
        for path, row in self._rows.items():
            row.configure(border_width=2 if path == self.selected else 0, border_color=ACCENT)

    def _context(self, event, path: Path) -> None:
        self._select(path)
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="이 음원 설정", command=lambda: self._settings_dialog(path))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def track_settings(self, path: Path) -> TrackSettings:
        if self.folder and path.is_relative_to(self.folder):
            values = self.overrides.get(self._track_key(path))
        else:
            # Playback can continue from a previous show after choosing a new
            # folder. Its settings still belong to its actual source directory.
            values = self._read_directory_settings(path.parent).get(path.name)
        return TrackSettings.from_dict(values, self.defaults)

    def _read_directory_settings(self, directory: Path) -> dict[str, dict]:
        settings_file = directory / CUE_SETTINGS_FILE
        try:
            raw = json.loads(settings_file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("설정은 JSON 객체여야 합니다.")
            for name, data in raw.items():
                if not isinstance(data, dict):
                    raise ValueError(f"{name}: 음원 설정을 읽을 수 없습니다.")
                TrackSettings.from_dict(data, self.defaults)
            return raw
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, AppError) as exc:
            raise AppError(f"음원별 설정 파일을 확인하세요.\n{settings_file}\n{exc}") from exc

    def _track_key(self, path: Path) -> str:
        try:
            return path.relative_to(self.folder).as_posix() if self.folder else path.name
        except ValueError:
            return path.name

    def _save_track_settings(self, path: Path, values: dict | None) -> None:
        """Keep same-name cues independent and retain per-directory settings files."""
        local = self._read_directory_settings(path.parent)
        if values is None:
            local.pop(path.name, None)
        else:
            local[path.name] = asdict(TrackSettings.from_dict(values))
        destination = path.parent / CUE_SETTINGS_FILE
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_text(json.dumps(local, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(destination)
        if self.folder and path.is_relative_to(self.folder):
            updated = dict(self.overrides)
            key = self._track_key(path)
            if values is None:
                updated.pop(key, None)
            else:
                updated[key] = local[path.name]
            self.overrides = updated

    def _settings_selected(self) -> None:
        path = self.selected or self.transport.path
        if path:
            self._settings_dialog(path)

    def _settings_dialog(self, path: Path) -> None:
        try:
            values = asdict(self.track_settings(path))
        except AppError as exc:
            self._error(exc)
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("이 음원 설정")
        dialog.geometry("440x510")
        dialog.transient(self.winfo_toplevel())
        dialog.columnconfigure(1, weight=1)
        label(dialog, text=path.name, bold=True, wraplength=400).grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=14)
        descriptions = {"default_volume": "일반 재생 기본 볼륨 (%)", "fade_in_seconds": "페이드인 시간 (초)",
                        "fade_in_from": "페이드인 시작 (%)", "fade_in_to": "페이드인 종료 (%)",
                        "fade_out_seconds": "페이드아웃 시간 (초)", "fade_out_from": "페이드아웃 시작 (%)",
                        "fade_out_to": "페이드아웃 종료 (%)"}
        variables = {}
        for row_index, (key, value) in enumerate(values.items(), start=1):
            label(dialog, text=descriptions[key]).grid(row=row_index, column=0, padx=16, pady=7, sticky="w")
            variable = tk.StringVar(dialog, f"{value:g}")
            ctk.CTkEntry(dialog, textvariable=variable, width=100, font=font()).grid(row=row_index, column=1, padx=16, pady=7, sticky="ew")
            variables[key] = variable
        error_var = tk.StringVar(dialog, "설정은 이 폴더의 .scene-audio.json에 저장됩니다.")
        label(dialog, textvariable=error_var, size=12, wraplength=400).grid(row=8, column=0, columnspan=2, padx=16, pady=8)

        def save(reset=False):
            try:
                self._save_track_settings(path, None if reset else {k: v.get() for k, v in variables.items()})
                dialog.destroy()
            except (OSError, AppError) as exc:
                error_var.set(str(exc))

        button(dialog, text="전역 기본값 사용", command=lambda: save(True)).grid(row=9, column=0, padx=16, pady=10, sticky="ew")
        button(dialog, text="저장", accent=True, command=save).grid(row=9, column=1, padx=16, pady=10, sticky="ew")
        dialog.after(50, dialog.grab_set)

    def _resolve_target(self, target: str) -> Path | None:
        if not target:
            return (self._video_path if self._video_active else self.transport.path) or self.selected
        target = target.strip().replace("\\", "/")
        if "/" in target and self.__dict__.get("folder"):
            relative_target = target.removeprefix("./").casefold()
            qualified = [p for p in self.tracks if self._track_key(p).casefold() == relative_target
                         or Path(self._track_key(p)).with_suffix("").as_posix().casefold() == relative_target]
            if len(qualified) == 1:
                return qualified[0]
        exact = [p for p in self.tracks if p.name.casefold() == target.casefold() or p.stem.casefold() == target.casefold()]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise AppError(f"같은 이름의 음원이 여러 개입니다: {target}\n하위 폴더를 포함한 파일명을 지정하세요. (예: 오프닝/{exact[0].name})")
        number_text = re.sub(r"^bgm", "", target.strip(), flags=re.IGNORECASE)
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", number_text):
            matches = [p for p in self.tracks if cue_number(p) == Decimal(number_text)]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise AppError(f"BGM {number_text}번이 여러 개입니다. 정확한 파일명을 지정하세요.")
        raise AppError(f"연결한 음원을 찾을 수 없습니다: {target}\n음원 폴더와 BGM 번호를 확인하세요.")

    def execute_cue(self, action: str, target: str = "", value: float | None = None) -> None:
        aliases = {"fadein": "fade_in", "fadeout": "fade_out", "resume": "play"}
        action = aliases.get(action, action)
        if action not in {"play", "pause", "stop", "fade_in", "fade_out", "volume", "seek"}:
            raise AppError(f"지원하지 않는 음원 동작입니다: {action}")
        path = self._resolve_target(target)
        if path is None:
            raise AppError("음원 폴더에서 재생할 음원을 선택하세요.")
        self._perform(action, path, value)

    def _run(self, action: str, path: Path | None = None) -> None:
        try:
            if path is not None:
                self._perform(action, path)
            else:
                self.execute_cue(action)
        except (AppError, OSError, ValueError) as exc:
            self._error(exc)

    def _perform(self, action: str, path: Path, value: float | None = None) -> None:
        config = self.track_settings(path)
        is_video = path.suffix.lower() in VIDEO_EXTENSIONS
        if action in {"volume", "seek"}:
            value = _number(value, "볼륨" if action == "volume" else "재생 위치", 0,
                            100 if action == "volume" else float("inf"))
        if self._pending and action in {"stop", "pause"}:
            pending_path = self._pending[1]
            self._pending = None
            if pending_path == path and self.transport.path != path.resolve():
                self.folder_var.set(f"{self.folder} · {len(self.tracks)}개 · 재생 대기 취소")
                return
        if action in {"play", "fade_in"}:
            # Any later GO supersedes pending playback, even if its source is
            # already cached or is a projector video.
            self._pending = None
        if is_video:
            if action == "play":
                if not self.on_video:
                    raise AppError("프로젝터 영상 재생기가 연결되지 않았습니다.")
                self.transport.stop()
                if self._video_active and self._video_path == path and self.on_video_action:
                    self.on_video_action("play", path, None)
                else:
                    self.on_video(path)
                self._video_active = True
                self._video_path = path
            elif self.on_video_action:
                if action == "fade_in" and (not self._video_active or self._video_path != path):
                    if not self.on_video:
                        raise AppError("프로젝터 영상 재생기가 연결되지 않았습니다.")
                    self.transport.stop()
                    self.on_video(path)
                    self._video_active = True
                    self._video_path = path
                elif self._video_path != path:
                    raise AppError(f"현재 재생 중인 영상이 아닙니다: {path.name}")
                self.on_video_action(action, path, value)
                if action == "stop":
                    self._video_active = False
            else:
                raise AppError("이 영상 제어 기능을 사용할 수 없습니다.")
            self._select(path)
            return
        if action in {"play", "fade_in"}:
            prepared = self._preparation.cached(path)
            if prepared is None:
                self._pending = (action, path, value)
                self._select(path)
                self.folder_var.set(f"음원 준비 중 · {path.name} (준비되면 재생합니다. ■로 취소)")
                self._preparation.request(path, urgent=True)
                return
            self.transport.player.prepared_paths[path.resolve()] = prepared
        # A row's pause/stop/out button must never operate a different live cue.
        if action in {"pause", "stop", "fade_out", "volume", "seek"} and self.transport.path != path.resolve():
            raise AppError(f"현재 재생 중인 음원이 아닙니다: {path.name}")
        if action in {"play", "fade_in"} and self._video_active and self.on_video_action:
            self.on_video_action("stop", self._video_path, None)
            self._video_active = False
        self._select(path)
        if action == "play":
            # Paused streams resume at the operator's volume; new/restarted cues
            # receive their normal-play default.
            volume = None if self.transport.path == path.resolve() and self.transport.state == "paused" else config.default_volume
            self.transport.play(path, volume)
        elif action == "pause":
            self.transport.pause()
        elif action == "stop":
            self.transport.stop()
        elif action == "fade_in":
            self.transport.play(path, config.fade_in_from)
            self.transport.fade(config.fade_in_from, config.fade_in_to, config.fade_in_seconds)
        elif action == "fade_out":
            self.transport.fade(config.fade_out_from, config.fade_out_to, config.fade_out_seconds, stop_at_zero=True)
        elif action == "volume":
            self.transport.set_volume(value)
        elif action == "seek":
            self.transport.seek(value)

    def _refresh_transport(self) -> None:
        if self._closed or not hasattr(self, "current_var"):
            return
        path = self.transport.path
        state = {"playing": "재생 중", "paused": "일시정지", "stopped": "정지"}.get(self.transport.state, "정지")
        if self._video_active and self._video_path:
            self.current_var.set(f"프로젝터 영상 · {self._video_path.stem}")
        elif path:
            self.current_var.set(f"{state} · {path.stem}")
        elif self.selected:
            self.current_var.set(f"선택 · {self.selected.stem}")
        else:
            self.current_var.set("현재 재생 · 선택한 음원 없음")
        self.volume_var.set(f"{self.transport.volume:.0f}%")
        self.volume_slider.set(self.transport.volume)

    def _volume(self, value: float) -> None:
        try:
            if self._video_active and self.on_video_action:
                self.on_video_action("volume", self._video_path, value)
                self.volume_var.set(f"{value:.0f}%")
            else:
                self.transport.set_volume(value)
        except AppError as exc:
            self._error(exc)

    def _seek(self, value: float) -> None:
        try:
            if self._video_active and self.on_video_action:
                self.on_video_action("seek", self._video_path, value)
            else:
                self.transport.seek(value)
        except AppError as exc:
            self._error(exc)

    def _poll(self) -> None:
        self._poll_id = None
        if self._closed:
            return
        while True:
            try:
                path, prepared, error = self._preparation.events.get_nowait()
            except queue.Empty:
                break
            if prepared:
                self.transport.player.prepared_paths[path] = prepared
            if self._pending and self._pending[1].resolve() == path:
                action, pending_path, value = self._pending
                self._pending = None
                if self.folder:
                    self.folder_var.set(f"{self.folder} · {len(self.tracks)}개")
                if error:
                    self._error(AppError(error))
                else:
                    try:
                        self._perform(action, pending_path, value)
                    except (AppError, OSError) as exc:
                        self._error(exc)
        try:
            if self._video_active and self.video_status:
                snapshot = self.video_status()
                if snapshot.get("state") == "stopped":
                    self._video_active = False
                    self._video_path = None
                    self._refresh_transport()
                else:
                    duration = float(snapshot.get("duration", 0))
                    position = float(snapshot.get("position", 0))
                    volume = float(snapshot.get("volume", 100))
                    self.seek_slider.configure(to=max(1, duration))
                    self.seek_slider.set(position)
                    self.volume_slider.set(volume)
                    self.volume_var.set(f"{volume:.0f}%")
                    self.time_var.set(f"{format_time(position)} / {format_time(duration)}")
                    self._poll_id = self.after(200, self._poll)
                    return
            player = self.transport.player
            duration = player.duration
            position = player.position()
            if self.transport.state == "playing" and player.mode() == "stopped":
                self.transport.cancel_fade()
                self.transport.state = "stopped"
                self._refresh_transport()
            self.seek_slider.configure(to=max(1, duration))
            self.seek_slider.set(position)
            self.time_var.set(f"{format_time(position)} / {format_time(duration)}")
        except AppError as exc:
            # Close a failed device so repeated polling cannot produce a dialog loop.
            try:
                self.transport.close()
            except AppError:
                pass
            self._error(exc)
        self._poll_id = self.after(200, self._poll)

    def stop_all(self) -> None:
        """Unconditional mode-leave/installer transport stop, including pending GO."""
        self._pending = None
        self.transport.stop()
        if self._video_active and self.on_video_action:
            self.on_video_action("stop", self._video_path, None)
        self._video_active = False
        self._video_path = None
        self._refresh_transport()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except tk.TclError:
                pass
            self._poll_id = None
        self.transport.close()
        self._pending = None
        self._preparation.close()

    def destroy(self) -> None:
        self.close()
        super().destroy()
