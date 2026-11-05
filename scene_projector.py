"""Clocked, letterboxed FFmpeg video output to a secondary Windows monitor.

Each playback owns its processes and PCM audio. Every seek gets a fresh decoder
queue; stale workers never touch newer playback. Tk and MCI stay on Tk's thread.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import math
from pathlib import Path
import queue
import re
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import wave

from PIL import Image, ImageEnhance, ImageOps, ImageTk

from backend import AppError, _creation_flags, _executable
from scene_audio import MciPlayer
from scene_blackscreen import choose_secondary, list_monitors

FPS = 25


def _finite(value, name, maximum=float("inf")):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AppError(f"{name}: 숫자를 입력하세요.") from exc
    if isinstance(value, bool) or not math.isfinite(number) or not 0 <= number <= maximum:
        raise AppError(f"{name}: 0~{maximum:g} 범위의 숫자를 입력하세요.")
    return number


def _duration(log):
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", log)
    return (int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])) if match else 0.0


@dataclass(eq=False)
class _DecodeJob:
    offset: float
    cancel: threading.Event = field(default_factory=threading.Event)
    frames: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=4))
    process: subprocess.Popen | None = None
    thread: threading.Thread | None = None


@dataclass(eq=False)
class _Session:
    path: Path
    size: tuple[int, int]
    folder: Path
    cancel: threading.Event = field(default_factory=threading.Event)
    ready: threading.Event = field(default_factory=threading.Event)
    events: queue.Queue = field(default_factory=queue.Queue)
    lock: threading.Lock = field(default_factory=threading.Lock)
    processes: set = field(default_factory=set)
    threads: list = field(default_factory=list)
    jobs: list = field(default_factory=list)
    audio: Path | None = None
    duration: float = 0
    error: str = ""


def _put(session, job, value):
    while not session.cancel.is_set() and not job.cancel.is_set():
        try:
            job.frames.put(value, timeout=.1)
            return True
        except queue.Full:
            pass
    return False


def _spawn(session, command, job=None, **kwargs):
    with session.lock:
        if session.cancel.is_set() or (job is not None and job.cancel.is_set()):
            return None
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, creationflags=_creation_flags(), **kwargs)
        session.processes.add(process)
        if job is not None:
            job.process = process
        return process


def _release(session, process):
    if process is None:
        return
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass
    with session.lock:
        session.processes.discard(process)


def _prepare(session):
    """Extract full PCM once; seeks reuse it rather than re-extracting audio."""
    process = None
    try:
        audio = session.folder / "sound.wav"
        with tempfile.TemporaryFile() as diagnostics:
            process = _spawn(session, [str(_executable("ffmpeg.exe")), "-hide_banner", "-loglevel", "info", "-nostdin", "-y",
                                      "-i", str(session.path), "-map", "0:a:0?", "-vn", "-c:a", "pcm_s16le",
                                      "-ar", "44100", "-ac", "2", str(audio)],
                             stdout=subprocess.DEVNULL, stderr=diagnostics)
            if process is None:
                return
            code = process.wait()
            diagnostics.seek(0)
            log = diagnostics.read(65536).decode("utf-8", errors="replace")
        if session.cancel.is_set():
            return
        session.duration = _duration(log)
        if code:
            if "does not contain any stream" not in log:
                raise AppError(log[-1800:] or "영상 오디오를 준비할 수 없습니다.")
        elif audio.is_file() and audio.stat().st_size > 44:
            session.audio = audio
            with wave.open(str(audio), "rb") as pcm:
                session.duration = max(session.duration, pcm.getnframes() / pcm.getframerate())
    except Exception as exc:
        session.error = str(exc)
    finally:
        _release(session, process)
        session.ready.set()
        if not session.cancel.is_set():
            session.events.put(("error", session.error) if session.error else ("ready", None))


def _decode(session, job):
    """Read captured frame size and start offset; never read mutable GUI state."""
    process = None
    try:
        while not session.ready.wait(.1):
            if session.cancel.is_set() or job.cancel.is_set():
                return
        if session.error or session.cancel.is_set() or job.cancel.is_set():
            return
        w, h = session.size
        filters = f"fps={FPS},scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        with tempfile.TemporaryFile() as diagnostics:
            command = [str(_executable("ffmpeg.exe")), "-hide_banner", "-loglevel", "error", "-nostdin",
                       "-ss", f"{job.offset:.6f}", "-i", str(session.path), "-map", "0:v:0", "-an",
                       "-vf", filters, "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
            process = _spawn(session, command, job, stdout=subprocess.PIPE, stderr=diagnostics)
            if process is None:
                return
            index, frame_size = 0, w * h * 3
            while not session.cancel.is_set() and not job.cancel.is_set():
                data = process.stdout.read(frame_size)
                if len(data) != frame_size:
                    break
                if not _put(session, job, (job.offset + index / FPS, data)):
                    return
                index += 1
            process.stdout.close()
            if session.cancel.is_set() or job.cancel.is_set():
                return
            code = process.wait(timeout=10)
            diagnostics.seek(0)
            detail = diagnostics.read(4096).decode("utf-8", errors="replace")
        if code or (index == 0 and (not session.duration or job.offset < session.duration - 1 / FPS)):
            raise AppError(detail[-1800:] or "영상 프레임이 없습니다.")
        _put(session, job, ("end", max(session.duration, job.offset + index / FPS)))
    except Exception as exc:
        _put(session, job, ("error", str(exc)))
    finally:
        if process is not None and process.stdout is not None and not process.stdout.closed:
            process.stdout.close()
        _release(session, process)


def _cleanup(session):
    # Joins and exact-file cleanup happen off Tk after cancellation releases
    # decoder backpressure. Only this session's temporary directory is touched.
    for thread in session.threads:
        if thread is not threading.current_thread():
            thread.join()
    for path in session.folder.iterdir() if session.folder.exists() else ():
        try:
            path.unlink()
        except OSError:
            pass
    try:
        session.folder.rmdir()
    except OSError:
        pass


class ProjectorController:
    def __init__(self, root, on_status=None, *, clock=None, player_factory=None):
        self.root = root
        self.on_status = on_status or (lambda value: None)
        self.clock = clock or time.monotonic
        self.player = (player_factory or MciPlayer)()
        self.window = None
        self.path = None
        self._session = self._job = None
        self._generation = self._fade_generation = 0
        self._timer = self._fade_timer = None
        self._started = self._paused_at = self._pending = None
        self._offset = 0.0
        self._audio_open = False
        self._audio_clock_end = None
        self._fade_spec = None
        self._next_monitor_check = 0
        self._monitor = None
        self.volume, self.opacity = 100.0, 1.0
        self.held_black = False
        self._photo = self._last_image = None

    @property
    def running(self):
        return self.window is not None

    @property
    def duration(self):
        return self._session.duration if self._session else 0.0

    @property
    def position(self):
        if self._started is None:
            return self._offset
        at = self._paused_at if self._paused_at is not None else self.clock()
        if self._audio_open:
            # Exact PCM audio is the master clock to prevent long-video A/V drift.
            if self._audio_clock_end is None:
                position = self.player.position()
                if position < self.player.duration - .02 or self.player.mode() == "playing":
                    return position
                self._audio_clock_end = (at, position)
            ended, position = self._audio_clock_end
            return position + max(0, at - ended)
        return max(self._offset, self._offset + at - self._started)

    def status_snapshot(self):
        state = "stopped" if not self.running else "black" if self.held_black else "paused" if self._paused_at is not None else "preparing" if self._started is None else "playing"
        return {"state": state, "position": self.position, "duration": self.duration, "volume": self.volume}

    def _place_window(self, window, target):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL
        # winfo_id may be Tk's client HWND; move its outer root in physical
        # monitor coordinates, including negative origins and mixed DPI.
        hwnd = user32.GetAncestor(window.winfo_id(), 2) or window.winfo_id()
        if not user32.SetWindowPos(hwnd, wintypes.HWND(-1), target.left, target.top,
                                  target.right - target.left, target.bottom - target.top, 0x0040 | 0x0010):
            raise ctypes.WinError(ctypes.get_last_error())

    def play(self, path):
        path = Path(path).resolve()
        if not path.is_file():
            raise AppError(f"영상 파일을 찾을 수 없습니다.\n{path}")
        target = choose_secondary(list_monitors())
        if target is None:
            raise AppError("보조 화면을 연결하고 Windows 화면 모드를 '확장'으로 설정하세요.")
        if self.running and self.path == path:
            self.resume()
            return
        self.stop()
        self.path, self._monitor = path, target
        self._started = self._paused_at = self._pending = None
        self._offset = 0.0
        self._audio_clock_end = None
        self.volume, self.opacity = 100.0, 1.0
        self.held_black = False
        w, h = target.right - target.left, target.bottom - target.top
        scale = min(1.0, 1920 / w, 1080 / h)
        size = (max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2))
        session = self._session = _Session(path, size, Path(tempfile.mkdtemp(prefix="scene-projector-")))
        try:
            window = self.window = tk.Toplevel(self.root)
            window.configure(background="black")
            window.overrideredirect(True)
            window.attributes("-topmost", True)
            window.update_idletasks()
            self._place_window(window, target)
            self.surface = tk.Label(window, bg="black", bd=0)
            self.surface.pack(fill="both", expand=True)
            window.bind("<Escape>", lambda _event: self.stop())
            window.bind("<Alt-F4>", lambda _event: self.stop())
            window.protocol("WM_DELETE_WINDOW", self.stop)
            self._screen_size = (w, h)
            self._next_monitor_check = self.clock() + 1
            thread = threading.Thread(target=_prepare, args=(session,), name="scene-video-audio", daemon=True)
            session.threads.append(thread)
            thread.start()
            self._start_decoder(0)
            self.on_status("영상 준비 중 · " + path.name)
            self._schedule_tick()
        except Exception:
            self.stop()
            raise

    def _start_decoder(self, offset):
        session = self._session
        if self._job:
            self._job.cancel.set()
            with session.lock:
                process = self._job.process
                if process is not None and process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        pass
        job = self._job = _DecodeJob(offset)
        session.jobs.append(job)
        thread = job.thread = threading.Thread(target=_decode, args=(session, job), name="scene-video-frames", daemon=True)
        session.threads.append(thread)
        thread.start()

    def _schedule_tick(self):
        generation = self._generation
        self._timer = self.root.after(15, lambda: self._tick(generation))

    def _start_playback(self):
        session = self._session
        paused = self._paused_at is not None
        if session.audio:
            if not self._audio_open:
                self.player.open(session.audio)
                self._audio_open = True
            self.player.set_volume(self.volume)
            self.player.seek(min(self._offset, self.player.duration))
            if not paused:
                self.player.play()
        self._started = self.clock()
        self._paused_at = self._started if paused else None
        self.on_status(("영상 일시정지 · " if paused else "재생 중 · ") + self.path.name)
        if self._fade_spec and not paused:
            self._begin_fade()

    def _tick(self, generation=None):
        if generation is not None and generation != self._generation:
            return
        self._timer = None
        if not self.running:
            return
        try:
            if self.clock() >= self._next_monitor_check:
                monitors = list_monitors()
                target = next((m for m in monitors if m.device == self._monitor.device and not m.primary), None)
                if target is None:
                    self.stop()
                    self.on_status("보조 화면 연결이 끊겨 영상을 정지했습니다.")
                    return
                if target != self._monitor:
                    self._monitor = target
                    self._screen_size = (target.right - target.left, target.bottom - target.top)
                    self._place_window(self.window, target)
                self._next_monitor_check = self.clock() + 1
            while True:
                try:
                    event, value = self._session.events.get_nowait()
                except queue.Empty:
                    break
                if event == "error":
                    raise AppError(value)
                if self.duration and self._offset > self.duration:
                    raise AppError("재생 위치가 영상 길이를 초과합니다.")
            image = None
            for _ in range(8):
                if self._pending is None:
                    try:
                        self._pending = self._job.frames.get_nowait()
                    except queue.Empty:
                        break
                when, data = self._pending
                if when == "error":
                    raise AppError(data)
                if when == "end":
                    # Hold the last frame for its full duration.
                    if self._started is None or self.position + .001 >= data:
                        self.stop()
                        self.on_status("영상 재생 완료")
                        return
                    break
                if self._started is None:
                    self._start_playback()
                    if not self.running:
                        return
                if when > self.position + .003:
                    break
                image = Image.frombytes("RGB", self._session.size, data)
                self._pending = None
                if self._paused_at is not None:
                    break
            if image is not None:
                self._last_image = image
                self._draw()
        except Exception as exc:
            self.stop()
            self.on_status("영상 오류 · " + str(exc))
            return
        self._schedule_tick()

    def _draw(self):
        if self._last_image is None or not self.running:
            return
        frame = self._last_image
        if self.opacity < .999:
            frame = ImageEnhance.Brightness(frame).enhance(self.opacity)
        if frame.size != self._screen_size:
            # A monitor resolution/aspect change must not stretch the picture.
            frame = ImageOps.pad(frame, self._screen_size, method=Image.Resampling.BILINEAR, color="black")
        self._photo = ImageTk.PhotoImage(frame, master=self.window)
        self.surface.configure(image=self._photo)

    def pause(self):
        if self.running and self._paused_at is None:
            pending_fade = self._fade_spec
            self._cancel_fade()
            self._fade_spec = pending_fade
            self._paused_at = self.clock()
            if self._audio_open:
                self.player.pause()
            self.on_status("영상 일시정지")

    def resume(self):
        if self.running and self.held_black:
            self.held_black = False
            self.opacity = 1.0
            self._draw()
        if self.running and self._paused_at is not None:
            if self._started is not None:
                paused_duration = self.clock() - self._paused_at
                self._started += paused_duration
                if self._audio_clock_end is not None:
                    ended, position = self._audio_clock_end
                    self._audio_clock_end = (ended + paused_duration, position)
            self._paused_at = None
            if self._audio_open and self._started is not None:
                self.player.play()
            if self._fade_spec and self._started is not None:
                self._begin_fade()
            self.on_status("영상 재생 중")

    def seek(self, value):
        seconds = _finite(value, "재생 위치", self.duration if self.duration > 0 else float("inf"))
        if not self.running:
            raise AppError("프로젝터에서 영상을 먼저 재생하세요.")
        self._cancel_fade()
        paused = self._paused_at is not None
        if self._audio_open:
            self.player.pause()
        self._offset = seconds
        self._audio_clock_end = None
        self._started = self._pending = None
        self._paused_at = self.clock() if paused else None
        self._start_decoder(seconds)
        self.on_status(f"영상 이동 중 · {seconds:g}초")

    def _apply_volume(self, value):
        self.volume = value
        if self._audio_open:
            self.player.set_volume(value)

    def set_volume(self, value):
        value = _finite(value, "볼륨", 100)
        self._cancel_fade()
        self._apply_volume(value)

    def _cancel_fade(self):
        self._fade_generation += 1
        self._fade_spec = None
        if self._fade_timer is not None:
            try:
                self.root.after_cancel(self._fade_timer)
            except tk.TclError:
                pass
            self._fade_timer = None

    def fade(self, seconds, start, end):
        seconds, start, end = _finite(seconds, "페이드 시간", 600), _finite(start, "시작 볼륨", 100), _finite(end, "종료 볼륨", 100)
        if not self.running:
            raise AppError("페이드할 영상을 먼저 재생하세요.")
        self._cancel_fade()
        self._apply_volume(start)
        self.opacity = start / 100
        self._draw()
        if self.held_black:
            # A fade-in from held black resumes transport without the normal
            # resume path restoring full picture brightness over its start.
            self.held_black = False
            self.resume()
        self._fade_spec = (seconds, start, end)
        if self._started is not None and self._paused_at is None:
            self._begin_fade()

    def _begin_fade(self):
        seconds, start, end = self._fade_spec
        self._fade_spec = None
        began, generation = self.clock(), self._fade_generation

        def step():
            if generation != self._fade_generation or not self.running:
                return
            self._fade_timer = None
            try:
                fraction = min(1.0, max(0, (self.clock() - began) / seconds)) if seconds else 1
                value = start + (end - start) * fraction
                self._apply_volume(value)
                self.opacity = value / 100
                self._draw()
                if fraction < 1:
                    self._fade_timer = self.root.after(25, step)
                elif end == 0:
                    self.pause()
                    self.held_black = True
                    self.on_status("영상 암전 · " + self.path.name)
            except Exception as exc:
                self.stop()
                self.on_status("영상 오류 · " + str(exc))

        step()

    def stop(self):
        self._generation += 1
        self._cancel_fade()
        if self._timer is not None:
            try:
                self.root.after_cancel(self._timer)
            except tk.TclError:
                pass
            self._timer = None
        session, self._session = self._session, None
        self._job = None
        if session:
            session.cancel.set()
            for job in session.jobs:
                job.cancel.set()
            with session.lock:
                for process in session.processes:
                    if process.poll() is None:
                        try:
                            process.kill()
                        except OSError:
                            pass
        if self._audio_open:
            self.player.close()
            self._audio_open = False
        if self.window:
            self.window.destroy()
            self.window = None
        self._photo = self._last_image = None
        self._started = self._paused_at = self._pending = None
        self._offset = 0
        self._audio_clock_end = None
        self.held_black = False
        if session:
            threading.Thread(target=_cleanup, args=(session,), name="scene-video-cleanup", daemon=True).start()
        self.on_status("영상 정지")

    close = stop

