"""SCENE App: stage audio preparation and secondary-display blackscreen."""

from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
import traceback

import customtkinter as ctk
from ui_translations import tr, get_language, set_language
from ui_theme import VERSION, BACKGROUND, prepare_ui, configure_fonts, font, font_report, button, label, CheckBox, fit_window, enable_dpi_awareness

from backend import AppError, Cancelled, ProcessRunner, _validate_url, app_dir
from scene_blackscreen import BlackScreenController
from scene_backend import convert_scene_file, download_scene_audio, scene_output_name
from scene_video import convert_scene_video, download_scene_video
from scene_settings import DEFAULTS, load_settings, save_settings, validate_settings
from scene_updates import check_for_update, download_update, launch_installer


class SceneApp(ctk.CTk):
    """Tk stays on the main thread; downloads and encoding use a worker."""

    def __init__(self, *, show_dialogs: bool = True) -> None:
        prepare_ui()
        super().__init__()
        self.title(f"SCENE App v{VERSION}")
        self.configure(fg_color=BACKGROUND)
        self._show_dialogs = show_dialogs
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._blackscreen = BlackScreenController(
            lambda state, detail: self._events.put(("blackscreen", (state, detail))))
        self._blackscreen_state = "off"
        self._blackscreen_error = ""
        self._runner: ProcessRunner | None = None
        self._worker: threading.Thread | None = None
        self._busy = False
        self._cancel_requested = False
        self._closing = False
        self._progress_running = False
        self.last_output: Path | None = None
        self.last_error: str | None = None
        self.settings = load_settings() if show_dialogs else dict(DEFAULTS)
        self.stage = None
        self._settings_dialog = None
        self._update_release = None
        self._update_path = None
        self._update_busy = False
        self._update_cancel = threading.Event()
        self.app_mode = "준비 모드"

        self.number_var = tk.StringVar(self)
        self.title_var = tk.StringVar(self)
        self.url_var = tk.StringVar(self)
        self.file_var = tk.StringVar(self)
        self.filename_var = tk.StringVar(self, tr("bgm번호_제목.mp3"))
        self.status_var = tk.StringVar(self, tr("번호와 제목을 입력한 뒤 음원을 가져오세요."))
        self.show_log_var = tk.BooleanVar(self, False)
        self.video_var = tk.BooleanVar(self, False)
        self.update_status_var = tk.StringVar(self, "")
        self.blackscreen_status_var = tk.StringVar(self, tr("OFF · 보조 화면을 그대로 표시합니다."))

        self._configure_styles()
        self._build_interface()
        self.number_var.trace_add("write", self._update_preview)
        self.title_var.trace_add("write", self._update_preview)
        self.bind("<Return>", lambda _event: self._begin())
        self.bind("<Escape>", lambda _event: self._request_cancel())
        self.bind("<Control-l>", self._focus_url)
        self.bind("<Control-Tab>", self._switch_mode)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.update_idletasks()
        self._fit_window()
        self._update_controls()
        self._handle_blackscreen_state("off", "")
        self.after(60, self._poll_events)
        self.after(120, self._check_dependencies)
        if show_dialogs and self.settings["check_updates"]:
            self.after(1800, self._check_updates)
        self.number_entry.focus_set()

    def _configure_styles(self) -> None:
        configure_fonts(self)

    def _build_interface(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = ctk.CTkFrame(self, fg_color="white", corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.mode_selector = ctk.CTkSegmentedButton(header, values=["준비 모드", "무대 모드"], font=font(14), command=self._select_app_mode)
        self.mode_selector.set(self.app_mode)
        self.mode_selector.grid(row=0, column=0, sticky="w", padx=14, pady=10)
        label(header, textvariable=self.update_status_var, size=12, muted=True).grid(row=1, column=0, columnspan=3, sticky="w", padx=14)
        self.update_button = button(header, text="업데이트 확인", command=self._update_action)
        self.update_button.grid(row=0,column=1,padx=4,pady=10)
        button(header, text="앱 설정", command=self._open_settings).grid(row=0,column=2,padx=(4,14),pady=10)
        self.preparation_frame = ctk.CTkFrame(self, fg_color=BACKGROUND, corner_radius=0)
        self.preparation_frame.grid(row=1, column=0, sticky="nsew")
        self.preparation_frame.columnconfigure(0,weight=1)
        self.preparation_frame.rowconfigure(2,weight=1)
        banner = ctk.CTkFrame(self.preparation_frame, fg_color="#dbeafe", corner_radius=12)
        banner.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 10))
        banner.columnconfigure(0, weight=1)
        label(banner, text="SCENE App", size=30, bold=True).grid(row=0, column=0, sticky="w", padx=18, pady=(12, 0))
        label(banner, text=f"v{VERSION}", muted=True).grid(row=0, column=1, padx=18, pady=(12, 0))
        label(banner, text="음원·영상 다운로드와 공연 큐 파일 준비", muted=True).grid(row=1, column=0, columnspan=2, sticky="w", padx=18, pady=(0, 12))

        # CustomTkinter handles form scrolling and high-DPI mouse wheel input.
        outer = ctk.CTkScrollableFrame(self.preparation_frame, width=712, height=660, fg_color=BACKGROUND, corner_radius=0)
        outer.grid(row=2, column=0, sticky="nsew", padx=14, pady=(10, 12))
        outer.columnconfigure(0, weight=1)
        self.canvas = outer._parent_canvas
        outer.bind("<Configure>", self._on_canvas_resize, add="+")

        naming = ctk.CTkFrame(outer, fg_color="transparent")
        naming.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        naming.columnconfigure(1, weight=1)
        label(naming, text=tr("1. 저장할 이름"), size=15, bold=True).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        label(naming, text=tr("음향 번호"), muted=True).grid(row=1, column=0, sticky="w", pady=(0, 4))
        label(naming, text=tr("제목"), muted=True).grid(row=1, column=1, sticky="w", padx=(12, 0), pady=(0, 4))
        self.number_entry = ctk.CTkEntry(naming, textvariable=self.number_var, width=140, height=38, font=font(15))
        self.number_entry.grid(row=2, column=0, sticky="ew")
        self.title_entry = ctk.CTkEntry(naming, textvariable=self.title_var, height=38, font=font())
        self.title_entry.grid(row=2, column=1, sticky="ew", padx=(12, 0))
        self.preview_label = label(naming, textvariable=self.filename_var, size=16, bold=True, wraplength=650)
        self.preview_label.configure(text_color="#2563eb")
        self.preview_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(9, 0))
        label(naming, text=tr("예: 번호 13.5 + 제목 오프닝 → bgm13.5_오프닝.mp3"), muted=True).grid(row=4, column=0, columnspan=2, sticky="w", pady=(3, 0))

        label(outer, text=tr("2. 음원 가져오기"), size=15, bold=True).grid(row=2, column=0, sticky="w")
        self.modes = (tr("링크에서 다운로드"), tr("파일을 MP3로 변환"))
        self.notebook = ctk.CTkTabview(outer, height=164, fg_color="white", segmented_button_font=font(),
                                      command=self._on_mode_changed, anchor="w")
        self.notebook.grid(row=3, column=0, sticky="ew")
        link_tab = self.notebook.add(self.modes[0])
        file_tab = self.notebook.add(self.modes[1])
        link_tab.columnconfigure(0, weight=1)
        file_tab.columnconfigure(0, weight=1)
        label(link_tab, text=tr("동영상 / 음원 링크"), muted=True).grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.url_entry = ctk.CTkEntry(link_tab, textvariable=self.url_var, height=38, font=font())
        self.url_entry.grid(row=1, column=0, sticky="ew")
        self.paste_button = button(link_tab, text=tr("붙여넣기"), command=self._paste_url)
        self.paste_button.grid(row=1, column=1, padx=(8, 0))
        self.link_hint = label(link_tab, text=tr("오디오 전용 형식 중 가장 높은 비트레이트를 골라 MP3로 저장합니다."), muted=True, wraplength=620)
        self.link_hint.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 4))
        label(file_tab, text=tr("가지고 있는 음원 파일"), muted=True).grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.file_entry = ctk.CTkEntry(file_tab, textvariable=self.file_var, height=38, font=font())
        self.file_entry.grid(row=1, column=0, sticky="ew")
        self.browse_button = button(file_tab, text=tr("파일 선택"), command=self._browse_file)
        self.browse_button.grid(row=1, column=1, padx=(8, 0))
        self.file_hint = label(file_tab, text=tr("WAV, M4A, FLAC 등 음원과 영상의 오디오를 MP3로 변환합니다."), muted=True, wraplength=620)
        self.file_hint.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 4))
        self.video_toggle = CheckBox(naming, text="영상으로 저장 (H.264 + MP3 · 기본 OFF)", variable=self.video_var, font=font(), command=self._on_video_changed)
        self.video_toggle.grid(row=5,column=0,columnspan=2,sticky="w",pady=(10,0))

        actions = ctk.CTkFrame(outer, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="ew", pady=(16, 0))
        actions.columnconfigure(0, weight=1)
        self.action_button = button(actions, text=tr("다운로드 + MP3 저장"), accent=True, command=self._begin)
        self.action_button.configure(height=42)
        self.action_button.grid(row=0, column=0, sticky="ew")
        self.cancel_button = button(actions, text=tr("취소"), command=self._request_cancel)
        self.cancel_button.grid(row=0, column=1, padx=(8, 0))
        self.progress = ctk.CTkProgressBar(outer, mode="determinate", height=8)
        self.progress.set(0)
        self.progress.grid(row=5, column=0, sticky="ew", pady=(15, 7))
        self.status_label = label(outer, textvariable=self.status_var, wraplength=650)
        self.status_label.grid(row=6, column=0, sticky="w")

        footer = ctk.CTkFrame(outer, fg_color="transparent")
        footer.grid(row=7, column=0, sticky="ew", pady=(14, 0))
        footer.columnconfigure(0, weight=1)
        label(footer, text=tr("저장 위치: 실행 파일 옆 Downloads 폴더"), muted=True).grid(row=0, column=0, sticky="w")
        self.open_button = button(footer, text=tr("저장 폴더 열기"), command=self._open_downloads)
        self.open_button.grid(row=0, column=1)
        CheckBox(footer, text=tr("작업 로그"), variable=self.show_log_var, font=font(), command=self._toggle_log).grid(row=1, column=0, sticky="w", pady=(10, 0))
        button(footer, text=tr("로그 복사"), command=self._copy_log).grid(row=1, column=1, pady=(10, 0))
        self.log_frame = ctk.CTkFrame(outer, fg_color="transparent")
        self.log_frame.grid(row=8, column=0, sticky="ew", pady=(8, 0))
        self.log_frame.columnconfigure(0, weight=1)
        self.log_text = ctk.CTkTextbox(self.log_frame, height=145, wrap="word", state="disabled", fg_color="#eaf0f7", text_color="#33445c", font=font(12))
        self.log_text.grid(row=0, column=0, sticky="ew")
        self.log_frame.grid_remove()

    def _fit_window(self) -> None:
        fit_window(self, width=800, height=880, min_width=600, min_height=540)

    def _stage_error(self, text):
        self._append_log(str(text))
        if self.stage is not None:
            self.stage.projector_status.set(str(text))
        if self._show_dialogs:
            messagebox.showerror("SCENE · 무대 제어", str(text), parent=self)

    def _select_app_mode(self, value):
        if value == self.app_mode:
            return
        if self._busy or self._update_busy:
            self.mode_selector.set(self.app_mode)
            self.status_var.set("진행 중인 준비 작업을 완료하거나 취소한 뒤 전환하세요.")
            return
        if value == "무대 모드":
            try:
                if self.stage is None:
                    from scene_stage import StageWorkspace
                    self.stage = StageWorkspace(self, self.settings, on_error=self._stage_error,
                        blackscreen_on=self._turn_blackscreen_on, blackscreen_off=self._turn_blackscreen_off)
                    self._handle_blackscreen_state(self._blackscreen_state, "")
                self.preparation_frame.grid_remove()
                self.stage.grid(row=1,column=0,sticky="nsew")
                self.minsize(1000, 620)
                self.state("zoomed")
            except Exception as exc:
                self.preparation_frame.grid()
                self.mode_selector.set(self.app_mode)
                self._stage_error(str(exc))
                return
        else:
            if self.stage is not None:
                # Mode changes deliberately stop sound and projector output.
                self.stage.audio.stop_all()
                self.stage.projector.stop()
                self._turn_blackscreen_off()
                self.stage.grid_remove()
            self.preparation_frame.grid()
            self.state("normal")
            self._fit_window()
        self.app_mode = value
        self.mode_selector.set(value)

    def _open_settings(self):
        if self._settings_dialog is not None and self._settings_dialog.winfo_exists():
            self._settings_dialog.lift()
            return
        from scene_stage import SettingsDialog
        def save(values):
            self.settings = save_settings(values) if self._show_dialogs else validate_settings(values)
            if self.stage is not None:
                self.stage.update_settings(self.settings)
        self._settings_dialog = SettingsDialog(self, self.settings, save)

    def _check_updates(self):
        if self._update_busy or self._closing or self.app_mode != "준비 모드":
            return
        self._update_busy = True
        self.update_status_var.set("새 버전 확인 중…")
        def worker():
            try:
                self._events.put(("update_checked", check_for_update(VERSION)))
            except Exception as exc:
                self._events.put(("update_failed", str(exc)))
        threading.Thread(target=worker,daemon=True,name="scene-update-check").start()

    def _update_action(self):
        if self._update_busy:
            if self._update_release:
                self._update_cancel.set()
            return
        if self.app_mode != "준비 모드" or self._busy:
            self.update_status_var.set("업데이트 설치는 준비 모드에서 작업을 마친 뒤 진행하세요.")
            return
        if self._update_path is not None:
            try:
                # Stop transports before invoking Inno's CloseApplications.
                if self.stage:
                    self.stage.close()
                    self.stage = None
                self._blackscreen.close()
                launch_installer(self._update_path)
                self.destroy()
            except Exception as exc:
                self.update_status_var.set(str(exc))
            return
        if self._update_release is None:
            self._check_updates()
            return
        release = self._update_release
        self._update_busy = True
        self._update_cancel.clear()
        self.update_button.configure(text="다운로드 취소")
        def worker():
            try:
                result = download_update(release,cancel=self._update_cancel,
                    progress=lambda done,total:self._events.put(("update_progress",(done,total))))
                self._events.put(("update_downloaded",result))
            except Exception as exc:
                self._events.put(("update_failed",str(exc)))
        threading.Thread(target=worker,daemon=True,name="scene-update-download").start()

    def _handle_update_event(self,event,payload):
        if event=="update_progress":
            done,total=payload
            self.update_status_var.set(f"업데이트 다운로드 · {done/total*100:.0f}%" if total else f"업데이트 다운로드 · {done//1024} KB")
            return
        self._update_busy=False
        if event=="update_checked":
            self._update_release=payload
            self.update_status_var.set(f"v{payload.version} 업데이트를 사용할 수 있습니다." if payload else f"v{VERSION} · 최신 버전입니다.")
            self.update_button.configure(text="업데이트 다운로드" if payload else "업데이트 확인")
        elif event=="update_downloaded":
            self._update_path=Path(payload)
            self.update_status_var.set("설치 파일 다운로드 완료 · 버튼을 누르면 앱을 종료하고 설치합니다.")
            self.update_button.configure(text="앱 종료 후 설치")
        else:
            self.update_status_var.set("업데이트 확인 / 다운로드 실패 · " + str(payload))
            self.update_button.configure(text="업데이트 다운로드" if self._update_release else "업데이트 확인")

    def _on_canvas_resize(self, event: tk.Event) -> None:
        available = max(220, event.width - 65)
        for label in (self.preview_label, self.status_label, self.link_hint, self.file_hint):
            label.configure(wraplength=available)

    def _turn_blackscreen_on(self) -> None:
        if self._closing or self._blackscreen.running or self._blackscreen_state not in {"off", "error"}:
            return
        self._blackscreen_error = ""
        self._handle_blackscreen_state("starting", "")
        self._blackscreen.start()

    def _turn_blackscreen_off(self) -> None:
        if self._blackscreen.running:
            self._handle_blackscreen_state("stopping", "")
            self._blackscreen.stop()

    def _handle_blackscreen_state(self, state: str, detail: str) -> None:
        if self._blackscreen_state == "stopping" and state in {"starting", "on", "waiting"}:
            return
        self._blackscreen_state = state
        messages = {
            "starting": tr("블랙스크린을 켜고 있습니다…"),
            "on": tr("ON · {display} 화면을 검정으로 표시합니다.", display=detail),
            "waiting": tr("ON · 보조 화면 연결을 기다리고 있습니다."),
            "stopping": tr("블랙스크린을 끄고 있습니다…"),
            "off": self._blackscreen_error or tr("OFF · 보조 화면을 그대로 표시합니다."),
        }
        if state == "error":
            errors = {
                "no_secondary_monitor": tr("보조 모니터가 없습니다. 연결 후 Windows 화면을 '확장'으로 설정하세요."),
                "already_running": tr("다른 블랙스크린이 실행 중입니다. 해당 프로그램에서 OFF한 뒤 다시 켜세요."),
            }
            self._blackscreen_error = errors.get(detail, tr("블랙스크린 오류: {error}", error=detail))
            messages[state] = self._blackscreen_error
            self._append_log(self._blackscreen_error)
        self.blackscreen_status_var.set(messages[state])
        if self.stage is not None:
            self.stage.blackscreen_on_button.configure(state="normal" if state in {"off", "error"} and not self._closing else "disabled")
            self.stage.blackscreen_off_button.configure(state="normal" if state in {"starting", "on", "waiting"} and not self._closing else "disabled")
            self.stage.blackscreen_status_var.set(self.blackscreen_status_var.get())

    def destroy(self) -> None:
        self._update_cancel.set()
        if self.stage is not None:
            self.stage.close()
            self.stage = None
        self._blackscreen.close()
        super().destroy()

    def _update_preview(self, *_args: object) -> None:
        try:
            self.filename_var.set(scene_output_name(self.number_var.get(), self.title_var.get()))
            if self.video_var.get():
                self.filename_var.set(str(Path(self.filename_var.get()).with_suffix(".mp4")))
        except AppError:
            self.filename_var.set(tr("bgm번호_제목.mp3 · 번호와 제목을 입력하세요"))

    def _on_mode_changed(self, _event: tk.Event | None = None) -> None:
        if self.notebook.get():
            self.action_button.configure(text=tr("다운로드 + MP3 저장") if self.notebook.get() == self.modes[0] else tr("MP3로 변환 + 저장"))
            if self.video_var.get():
                self.action_button.configure(text="다운로드 + MP4 저장" if self.notebook.get() == self.modes[0] else "MP4로 변환 + 저장")

    def _on_video_changed(self):
        self._update_preview()
        self._on_mode_changed()
        self.link_hint.configure(text="최고 해상도 영상을 H.264 + MP3 오디오의 MP4로 저장합니다." if self.video_var.get() else tr("오디오 전용 형식 중 가장 높은 비트레이트를 골라 MP3로 저장합니다."))
        self.file_hint.configure(text="영상 원본을 보존하고 프로젝터용 MP4로 변환합니다." if self.video_var.get() else tr("WAV, M4A, FLAC 등 음원과 영상의 오디오를 MP3로 변환합니다."))

    def _switch_mode(self, _event: tk.Event | None = None) -> str:
        if not self._busy:
            self.notebook.set(self.modes[1] if self.notebook.get() == self.modes[0] else self.modes[0])
            self._on_mode_changed()
        return "break"

    def _check_dependencies(self) -> None:
        missing = [name for name in ("ffmpeg.exe",) if not (app_dir() / name).is_file()]
        if missing and not self._busy:
            text = tr("앱과 같은 폴더에 필요한 파일을 넣어 주세요: ") + ", ".join(missing)
            self.status_var.set(text)
            self._append_log(text)

    def _focus_url(self, _event: tk.Event | None = None) -> str:
        if not self._busy:
            self.notebook.set(self.modes[0])
            self.url_entry.focus_set()
            self.url_entry.selection_range(0, "end")
        return "break"

    def _paste_url(self) -> None:
        if self._busy:
            return
        try:
            self.url_var.set(self.clipboard_get().strip())
            self.url_entry.icursor("end")
        except tk.TclError:
            self.status_var.set(tr("클립보드에 복사된 링크가 없습니다."))

    def _browse_file(self) -> None:
        if self._busy:
            return
        selected = filedialog.askopenfilename(parent=self, title="MP4로 변환할 영상 선택" if self.video_var.get() else tr("MP3로 변환할 음원 선택"), filetypes=[(tr("음원 / 영상 파일"), "*.wav *.m4a *.aac *.flac *.ogg *.opus *.wma *.aiff *.aif *.mp3 *.mp4 *.mkv *.webm *.mov"), (tr("모든 파일"), "*.*")])
        if selected:
            self.file_var.set(selected)
            if not self.title_var.get().strip():
                self.title_var.set(Path(selected).stem)

    def _begin(self) -> None:
        if self._busy or self._closing or self.app_mode != "준비 모드":
            return
        number, title = self.number_var.get().strip(), self.title_var.get().strip()
        try:
            scene_output_name(number, title)
            mode = self.modes.index(self.notebook.get())
            if mode == 0:
                url = _validate_url(self.url_var.get())
                dependencies = ("ffmpeg.exe",)
                operation = (lambda runner: download_scene_video(url, number, title, runner, dict(self.settings))) if self.video_var.get() else (lambda runner: download_scene_audio(url, number, title, runner))
            else:
                source = Path(self.file_var.get().strip()).expanduser()
                if not self.file_var.get().strip() or not source.is_file():
                    raise AppError(tr("MP3로 변환할 음원 파일을 선택해 주세요."))
                source = source.resolve()
                dependencies = ("ffmpeg.exe",)
                operation = (lambda runner: convert_scene_video(source, number, title, runner, dict(self.settings))) if self.video_var.get() else (lambda runner: convert_scene_file(source, number, title, runner))
            for name in dependencies:
                if not (app_dir() / name).is_file():
                    raise AppError(tr("{name} 파일을 앱과 같은 폴더에 넣어 주세요.\n{folder}", name=name, folder=app_dir()))
        except (AppError, OSError) as error:
            self.last_error = str(error)
            self.status_var.set(str(error))
            return
        self.status_var.set(tr("최고 비트레이트 오디오를 찾고 있습니다…") if mode == 0 else tr("MP3 변환을 준비하고 있습니다…"))
        self._append_log(tr("\n── 링크 다운로드 + MP3 ──") if mode == 0 else tr("\n── 파일 MP3 변환 ──"))
        output_name = scene_output_name(number, title)
        if self.video_var.get():
            output_name = Path(output_name).with_suffix(".mp4").name
            self.status_var.set("프로젝터용 영상 다운로드 / 변환을 준비하고 있습니다…")
            self._append_log("영상 모드 · H.264 + libmp3lame VBR 2")
        self._append_log(tr("저장할 이름: ") + output_name)
        self._start_job(operation)

    def _start_job(self, operation: Callable[[ProcessRunner], Path]) -> None:
        self._busy = True
        self._cancel_requested = False
        self.last_error = None
        self.last_output = None
        self._runner = ProcessRunner(lambda event, payload: self._events.put((event, payload)))
        runner = self._runner
        self._set_progress(None)
        self._update_controls()

        def work() -> None:
            try:
                self._events.put(("completed", operation(runner)))
            except Cancelled as error:
                self._events.put(("cancelled", str(error)))
            except AppError as error:
                self._events.put(("failed", str(error)))
            except Exception as error:
                self._events.put(("log", traceback.format_exc()))
                self._events.put(("failed", tr("예기치 않은 오류가 발생했습니다.\n{error}", error=error)))

        self._worker = threading.Thread(target=work, name="scene-audio", daemon=True)
        self._worker.start()

    def _update_controls(self) -> None:
        for widget in (self.number_entry, self.title_entry, self.url_entry, self.file_entry, self.paste_button, self.browse_button, self.action_button):
            widget.configure(state="disabled" if self._busy else "normal")
        # CTkTabview retains the active page while its mode selector is disabled.
        self.notebook.configure(state="disabled" if self._busy else "normal")
        self.cancel_button.configure(state="normal" if self._busy and not self._cancel_requested else "disabled")
        self.video_toggle.configure(state="disabled" if self._busy else "normal")

    def _request_cancel(self) -> None:
        if not self._busy or self._runner is None or self._cancel_requested:
            return
        self._cancel_requested = True
        self.status_var.set(tr("작업을 취소하고 있습니다…"))
        self._update_controls()
        self._runner.cancel()

    def _poll_events(self) -> None:
        try:
            for _ in range(400):
                event, payload = self._events.get_nowait()
                if event == "blackscreen":
                    self._handle_blackscreen_state(*payload)
                elif event.startswith("update_"):
                    self._handle_update_event(event, payload)
                elif event == "log":
                    self._append_log(str(payload))
                elif event == "status" and not self._cancel_requested:
                    self.status_var.set(str(payload))
                elif event == "progress":
                    self._set_progress(payload)
                elif event == "completed":
                    self.last_output = Path(payload)
                    self._finish_job()
                    self.status_var.set(tr("저장 완료 · {name}", name=self.last_output.name))
                    self._append_log(tr("저장 완료: {path}", path=self.last_output))
                    self._set_progress(100)
                elif event in {"cancelled", "failed"}:
                    self.last_error = str(payload)
                    self._finish_job()
                    self.status_var.set(tr("작업을 취소했습니다.") if event == "cancelled" else tr("작업에 실패했습니다. 로그를 확인해 주세요."))
                    self._append_log(str(payload))
                    self.show_log_var.set(True)
                    self._toggle_log()
                    if event == "failed" and self._show_dialogs and not self._closing:
                        messagebox.showerror(tr("SCENE · 작업 오류"), str(payload), parent=self)
        except queue.Empty:
            pass
        if self._closing and not self._busy and (self._worker is None or not self._worker.is_alive()):
            self.destroy()
            return
        self.after(60, self._poll_events)

    def _finish_job(self) -> None:
        self._busy = False
        self._cancel_requested = False
        self._runner = None
        self._set_progress(0)
        self._update_controls()

    def _set_progress(self, value: object) -> None:
        if value is None:
            if not self._progress_running:
                self.progress.configure(mode="indeterminate")
                self.progress.start()
                self._progress_running = True
        else:
            if self._progress_running:
                self.progress.stop()
                self._progress_running = False
            self.progress.configure(mode="determinate")
            self.progress.set(max(0, min(100, float(value))) / 100)

    def _append_log(self, value: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", value.rstrip() + "\n")
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 1400:
            self.log_text.delete("1.0", f"{lines-1100}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _toggle_log(self) -> None:
        if self.show_log_var.get():
            self.log_frame.grid()
        else:
            self.log_frame.grid_remove()

    def _copy_log(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.log_text.get("1.0", "end-1c"))
        if not self._busy:
            self.status_var.set(tr("작업 로그를 복사했습니다."))

    def _open_downloads(self) -> None:
        try:
            downloads = app_dir() / "Downloads"
            downloads.mkdir(exist_ok=True)
            os.startfile(downloads)
        except OSError as error:
            if self._show_dialogs:
                messagebox.showerror(tr("폴더 열기 오류"), str(error), parent=self)

    def _on_close(self) -> None:
        if self._closing:
            return
        if self._busy:
            if self._show_dialogs and not messagebox.askyesno(tr("작업 종료"), tr("진행 중인 작업을 취소하고 창을 닫을까요?"), parent=self):
                return
            self._closing = True
            self._blackscreen.stop()
            self._request_cancel()
        else:
            self.destroy()


def _packaging_self_test(report_path: Path, *, operation: tuple[str, str, str, str] | None = None) -> None:
    """Opt-in release verification exercises this full UI and its event queue."""
    from backend import _js_runtime_args

    report: dict[str, object] = {"ok": False, "variant": "SCENE App", "frozen": bool(getattr(sys, "frozen", False)), "python": sys.version.split()[0], "app_dir": str(app_dir())}
    app: SceneApp | None = None
    try:
        app = SceneApp(show_dialogs=False)
        app.withdraw()
        app.update_idletasks()
        report["tk"] = app.tk.call("info", "patchlevel")
        report["ui"] = type(app).__name__
        report["customtkinter"] = ctk.__version__
        report["version"] = VERSION
        from scene_stage import StageWorkspace
        from scene_script import ScriptViewerFrame
        import pymupdf
        import pythonmonkey
        report["stage_available"] = StageWorkspace is not None
        report["script_available"] = ScriptViewerFrame is not None
        report["pdf_available"] = bool(pymupdf.VersionBind)
        from tkinterweb import HtmlFrame
        web_probe = HtmlFrame(app, javascript_enabled=True, messages_enabled=False)
        try:
            web_probe.load_html('<p id="check">before</p><script>document.getElementById("check").textContent="JS works";</script>')
            report["web_javascript"] = (pythonmonkey.eval("6 * 7") == 42 and
                web_probe.document.getElementById("check").textContent == "JS works")
            if not report["web_javascript"]:
                raise RuntimeError("Bundled PythonMonkey DOM JavaScript failed.")
        finally:
            web_probe.destroy()
        report["blackscreen_available"] = isinstance(app._blackscreen, BlackScreenController)
        report["language"] = get_language()
        report["ui_text"] = {"status": app.status_var.get(), "action": app.action_button.cget("text"), "modes": app.modes}
        report["fonts"] = font_report(app)
        runner = ProcessRunner(lambda _event, _payload: None)
        if operation is None:
            runtime_spec = _js_runtime_args()[-1]
            runtime_name, runtime_path = runtime_spec.split(":", 1)
            if runtime_name != "deno":
                raise RuntimeError("The bundle must use its own Deno runtime.")
            report["runtime"] = runtime_path
            report["javascript"] = runner.run([runtime_path, "eval", "console.log(6 * 7)"])
            if report["javascript"] != ["42"]:
                raise RuntimeError("Bundled JavaScript evaluation failed.")
            import yt_dlp
            report["yt_dlp"] = yt_dlp.version.__version__
            import yt_dlp_ejs
            report["ejs_scripts"] = len(list(Path(yt_dlp_ejs.__file__).parent.rglob("*.js")))
            if report["ejs_scripts"] < 2:
                raise RuntimeError("The embedded EJS challenge scripts are missing.")
            with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
                report["python_api"] = type(ydl).__name__
            report["ffmpeg"] = runner.run([str(app_dir() / "ffmpeg.exe"), "-hide_banner", "-version"])[0]
        else:
            kind, source, number, title = operation
            app.number_var.set(number)
            app.title_var.set(title)
            if kind == "convert":
                app.notebook.set(app.modes[1])
                app.file_var.set(source)
            else:
                app.notebook.set(app.modes[0])
                app.url_var.set(source)
            app._begin()
            deadline = time.monotonic() + 90
            while app._busy and time.monotonic() < deadline:
                app.update()
                time.sleep(0.01)
            if app._busy:
                app._request_cancel()
                raise RuntimeError("Packaged workflow timed out.")
            if app.last_error or app.last_output is None:
                raise RuntimeError(app.last_error or "The GUI did not produce output.")
            report["output"] = str(app.last_output)
            report["bytes"] = app.last_output.stat().st_size
            report["log"] = app.log_text.get("1.0", "end-1c")
            if not report["bytes"] or app.last_output.suffix.lower() != ".mp3":
                raise RuntimeError("The GUI did not produce a nonempty MP3.")
        report["ok"] = True
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if app is not None:
            if app._busy and app._runner is not None:
                app._runner.cancel()
                if app._worker is not None:
                    app._worker.join(timeout=10)
            for timer in app.tk.call("after", "info"):
                app.tk.call("after", "cancel", timer)
            app.destroy()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not report["ok"]:
        raise SystemExit(1)


def main() -> None:
    if len(sys.argv) == 4 and sys.argv[1] == "--self-test-language" and sys.argv[2] in {"ko", "en"}:
        set_language(sys.argv[2])
        _packaging_self_test(Path(sys.argv[3]))
        return
    if (len(sys.argv) > 3 and sys.argv[1] == "--self-test-language"
            and sys.argv[2] in {"ko", "en"} and sys.argv[3].startswith("--self-test")):
        set_language(sys.argv[2])
        del sys.argv[1:3]
    enable_dpi_awareness()
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        _packaging_self_test(Path(sys.argv[2]))
        return
    if len(sys.argv) == 6 and sys.argv[1] in {"--self-test-convert", "--self-test-download"}:
        kind = "convert" if sys.argv[1] == "--self-test-convert" else "download"
        _packaging_self_test(Path(sys.argv[5]), operation=(kind, sys.argv[2], sys.argv[3], sys.argv[4]))
        return
    app = SceneApp()
    app.mainloop()


if __name__ == "__main__":
    main()
