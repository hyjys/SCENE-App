"""Two independent local/web panels, show controls, and application settings."""
from __future__ import annotations

import hashlib
from pathlib import Path
import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import webbrowser

import customtkinter as ctk

from backend import AppError
from scene_audio import StageAudioFrame
from scene_script import ScriptViewerFrame
from scene_projector import ProjectorController
from scene_settings import DEFAULTS, ENCODERS, PRESETS, settings_path
from scene_web import WEBVIEW2_DOWNLOAD_URL, create_browser
from ui_theme import VERSION, font, button, label, BACKGROUND


def web_url(value):
    value = value.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise AppError("http:// 또는 https:// 주소를 입력하세요.")
    return value


class WebPanel(ctk.CTkFrame):
    def __init__(self, parent, url, on_error, on_import=None):
        super().__init__(parent, fg_color="white")
        self.on_error, self.on_import = on_error, on_import
        self.url = tk.StringVar(self, url)
        self.browser = None
        self._closed = False
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ctk.CTkEntry(self, textvariable=self.url, font=font(), height=32).grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        button(self, text="열기", width=60, command=self.load).grid(row=0, column=1, padx=(0,8))
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8)
        button(bar, text="브라우저에서 열기", width=135, command=self.external).pack(side="left", padx=(0,5))
        self.runtime_button = button(bar, text="WebView2 설치", width=115,
                                     command=lambda: webbrowser.open(WEBVIEW2_DOWNLOAD_URL))
        if on_import:
            button(bar, text="Google 대본 가져오기", width=150, command=lambda: on_import(self.url.get())).pack(side="left")
        self.host = ctk.CTkFrame(self, fg_color="white")
        self.host.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=8, pady=8)
        self.placeholder = label(self.host, text="주소를 입력하고 열기를 누르세요.\nMicrosoft Edge WebView2", wraplength=380, muted=True)
        self.placeholder.pack(padx=12, pady=24)

    def load(self):
        if self._closed:
            return
        try:
            url = web_url(self.url.get())
            if self.browser is None:
                self.browser = create_browser(self.host)
                self.browser.pack(fill="both", expand=True)
            self.browser.navigate(url)
            self.placeholder.pack_forget()
            self.runtime_button.pack_forget()
        except Exception as exc:
            if self.browser is None:
                self.runtime_button.pack(side="left", padx=5)
            self.on_error(str(exc))

    def external(self):
        try:
            webbrowser.open(web_url(self.url.get()))
        except Exception as exc:
            self.on_error(str(exc))

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.suspend()

    def suspend(self):
        """Dispose hidden web media; retain the entered URL and shared profile."""
        if self.browser is not None:
            self.browser.destroy()
            self.browser = None
        self.placeholder.pack(padx=12, pady=24)

    def destroy(self):
        self.close()
        super().destroy()


class StageWorkspace(ctk.CTkFrame):
    def __init__(self, parent, settings, *, on_error, blackscreen_on, blackscreen_off):
        super().__init__(parent, fg_color=BACKGROUND, corner_radius=0)
        self.settings = settings
        self.on_error = on_error
        self._events = queue.Queue()
        self._closed = False
        self.columnconfigure((0, 1), weight=1, uniform="stage")
        self.rowconfigure(0, weight=1)
        self.left, self.right = self._side(0, "음향 제어반"), self._side(1, "대본 뷰어")
        self.projector_status = tk.StringVar(self, "프로젝터 · 대기")
        self.blackscreen_status_var = tk.StringVar(self, "블랙스크린 OFF")
        self.projector = ProjectorController(self, self.projector_status.set)
        self.audio = StageAudioFrame(self.left[1], settings, on_video=self.play_video, on_error=on_error)
        self.audio.on_video_action = self.video_action
        self.audio.video_status = self.projector.status_snapshot
        self.script = ScriptViewerFrame(self.right[1], on_cue=self.execute_cue, on_error=on_error)
        self.web_audio = WebPanel(self.left[1], settings["audio_url"], on_error)
        self.web_script = WebPanel(self.right[1], settings["script_url"], on_error, self.import_google_script)
        for side, local, web in ((self.left, self.audio, self.web_audio), (self.right, self.script, self.web_script)):
            local.grid(row=0, column=0, sticky="nsew")
            web.grid(row=0, column=0, sticky="nsew")
            side[0].configure(command=lambda value, s=side, l=local, w=web: self._show(s,l,w,value))
        panel = ctk.CTkFrame(self, fg_color="white")
        self.blackscreen_panel = panel
        panel.grid(row=1, column=1, sticky="ew", padx=(5,12), pady=(4,12))
        panel.columnconfigure(0, weight=1)
        label(panel, text="프로젝터", size=14, bold=True).grid(row=0, column=0, sticky="w", padx=10, pady=(8,2))
        controls = ctk.CTkFrame(panel, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", padx=8)
        for index, (text, cmd) in enumerate((("암전 ON", lambda: self._blackout(blackscreen_on)), ("암전 OFF", blackscreen_off),
                          ("영상 열기", self.choose_video), ("Ⅱ", self.projector.pause),
                          ("▶", self._resume_video), ("■", self.projector.stop))):
            control = button(controls, text=text, width=54 if len(text)<2 else 78, command=cmd)
            control.pack(side="left", padx=2, pady=3)
            if index == 0:
                self.blackscreen_on_button = control
            elif index == 1:
                self.blackscreen_off_button = control
        self.blackscreen_status_label = label(panel, textvariable=self.blackscreen_status_var, muted=True, wraplength=500)
        self.blackscreen_status_label.grid(row=2, column=0, sticky="ew", padx=10)
        label(panel, textvariable=self.projector_status, muted=True, wraplength=500).grid(row=3, column=0, sticky="ew", padx=10, pady=(2,8))
        self._blackscreen_off = blackscreen_off
        self.update_settings(settings)
        self._timer = self.after(80, self._poll)

    def _side(self, column, title):
        frame = ctk.CTkFrame(self, fg_color="white")
        frame.grid(row=0, column=column, rowspan=2 if column==0 else 1, sticky="nsew", padx=(12,5) if column==0 else (5,12), pady=(8,12) if column==0 else (8,4))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        label(header, text=title, size=17, bold=True).pack(side="left")
        switch = ctk.CTkSegmentedButton(header, values=["로컬", "웹 / Google"], font=font(12))
        switch.pack(side="right")
        host = ctk.CTkFrame(frame, fg_color="white", corner_radius=0)
        host.grid(row=1, column=0, sticky="nsew")
        host.columnconfigure(0, weight=1)
        host.rowconfigure(0, weight=1)
        return switch, host

    @staticmethod
    def _show(side, local, web, value):
        if value == "로컬":
            web.suspend()
            web.grid_remove()
            local.grid()
        else:
            local.grid_remove()
            web.grid()
        side[0].set(value)

    def update_settings(self, settings):
        self.settings = settings
        self.audio.update_settings(settings)
        self.script.update_settings(settings)
        self.web_audio.url.set(settings["audio_url"])
        self.web_script.url.set(settings["script_url"])
        self._show(self.left, self.audio, self.web_audio, "로컬" if settings["audio_source"]=="local" else "웹 / Google")
        self._show(self.right, self.script, self.web_script, "로컬" if settings["script_source"]=="local" else "웹 / Google")

    def execute_cue(self, action, target="", value=None):
        if value is None:
            self.audio.execute_cue(action, target)
        else:
            self.audio.execute_cue(action, target, value)

    def _blackout(self, callback):
        self.projector.stop()
        callback()

    def choose_video(self):
        path = filedialog.askopenfilename(parent=self, title="프로젝터에 표시할 영상", filetypes=[("영상", "*.mp4 *.mkv *.mov *.webm *.avi"),("모든 파일","*.*")])
        if path:
            try:
                self.play_video(path)
            except Exception as exc:
                self.on_error(str(exc))

    def play_video(self, path):
        self._blackscreen_off()
        self.projector.play(path)
        self.projector.set_volume(self.audio.track_settings(Path(path)).default_volume)

    def _resume_video(self):
        if self.projector.running and self.projector.path:
            try:
                self.video_action("play", self.projector.path)
            except Exception as exc:
                self.on_error(str(exc))

    def video_action(self, action, path, value=None):
        if action == "stop":
            self.projector.stop()
        elif action == "pause":
            self.projector.pause()
        elif action == "play":
            if getattr(self.projector, "held_black", False):
                self.projector.set_volume(self.audio.track_settings(Path(path)).default_volume)
            self.projector.resume()
        elif action in {"fade_in", "fade_out"}:
            if not self.projector.running or self.projector.path != Path(path):
                self.play_video(path)
            cfg = self.audio.track_settings(Path(path))
            prefix = action
            if action == "fade_in":
                self.projector.resume()
            self.projector.fade(getattr(cfg,prefix+"_seconds"), getattr(cfg,prefix+"_from"), getattr(cfg,prefix+"_to"))
        elif action == "volume":
            self.projector.set_volume(value)
        elif action == "seek":
            self.projector.seek(value)

    def import_google_script(self, value):
        try:
            url = web_url(value)
            parsed = urlsplit(url)
            match = re.match(r"/document/d/([A-Za-z0-9_-]+)(?:/|$)", parsed.path)
            if parsed.hostname != "docs.google.com" or not match:
                raise AppError("Google Docs의 /document/d/… 공유 링크를 입력하세요.")
            document_id = match[1]
        except AppError as exc:
            self.on_error(str(exc))
            return
        self.projector_status.set("Google 대본을 가져오고 있습니다…")
        def worker():
            try:
                req = Request(f"https://docs.google.com/document/d/{document_id}/export?format=txt", headers={"User-Agent":f"SCENE-App/{VERSION}"})
                with urlopen(req, timeout=20) as response:
                    data = response.read(10*1024*1024+1)
                    if len(data)>10*1024*1024 or "text/html" in response.headers.get("Content-Type", ""):
                        raise AppError("대본을 가져올 수 없습니다. 링크 공유 권한을 확인하세요.")
                folder = settings_path().parent / "Google 대본"
                folder.mkdir(parents=True, exist_ok=True)
                destination = folder / (hashlib.sha256(document_id.encode()).hexdigest()[:16]+".txt")
                temporary = destination.with_suffix(".tmp")
                temporary.write_bytes(data)
                temporary.replace(destination)
                self._events.put(("script", destination))
            except Exception as exc:
                self._events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        if self._closed:
            return
        try:
            while True:
                event, value = self._events.get_nowait()
                if event == "script":
                    self.script.open_file(value)
                    self._show(self.right, self.script, self.web_script, "로컬")
                    self.projector_status.set("Google 대본 가져오기 완료 · 로컬 큐를 설정하세요.")
                else:
                    self.projector_status.set("Google 대본 가져오기 실패")
                    self.on_error(value)
        except queue.Empty:
            pass
        self._timer = self.after(80, self._poll)

    def close(self):
        self._closed = True
        self.after_cancel(self._timer)
        self.audio.close()
        self.script.close()
        self.web_audio.close()
        self.web_script.close()
        self.projector.close()


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent, settings, on_save):
        super().__init__(parent)
        self.title("SCENE · 전역 앱 설정")
        self.geometry("670x750")
        self.minsize(550, 450)
        self.transient(parent)
        self.vars = {}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        content = ctk.CTkScrollableFrame(self, fg_color=BACKGROUND)
        content.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        content.columnconfigure(1, weight=1)
        fields = [("audio_source","음향 소스",("local","web")), ("audio_url","음향 웹 / Google Drive 주소",None),
                  ("script_source","대본 소스",("local","web")), ("script_url","대본 웹 / Google Docs 주소",None),
                  ("audio_folder","기본 음향 폴더",None), ("default_volume","일반 재생 기본 볼륨 (%)",None),
                  ("fade_in_seconds","페이드인 시간 (초)",None), ("fade_in_from","페이드인 시작 (%)",None),
                  ("fade_in_to","페이드인 끝 (%)",None), ("fade_out_seconds","페이드아웃 시간 (초)",None),
                  ("fade_out_from","페이드아웃 시작 (%)",None), ("fade_out_to","페이드아웃 끝 (%)",None),
                  ("video_encoder","영상 인코더",ENCODERS), ("video_preset","영상 속도 프리셋",PRESETS)]
        for row,(key,title,choices) in enumerate(fields):
            label(content, text=title).grid(row=row, column=0, sticky="w", padx=8, pady=6)
            value = tk.StringVar(self, str(settings.get(key,DEFAULTS[key])))
            self.vars[key] = value
            widget = ctk.CTkOptionMenu(content, variable=value, values=list(choices), font=font()) if choices else ctk.CTkEntry(content, textvariable=value, font=font())
            widget.grid(row=row, column=1, sticky="ew", padx=8, pady=6)
        self.updates = tk.BooleanVar(self, settings["check_updates"])
        ctk.CTkCheckBox(content, text="준비 모드 시작 시 업데이트 자동 확인", variable=self.updates, font=font()).grid(row=len(fields), column=0,columnspan=2,padx=8,pady=10,sticky="w")
        label(content,text="libx264: CRF 20 · 기본 veryslow / MP3 VBR 2\nNVENC: p7(느린 프리셋)·p4 / QSV: veryslow·medium\nGPU 인코딩에는 지원 장치와 드라이버가 필요합니다.", muted=True,wraplength=580).grid(row=len(fields)+1,column=0,columnspan=2,sticky="ew",padx=8,pady=6)
        self.error = tk.StringVar(self)
        label(content,textvariable=self.error,wraplength=580).grid(row=len(fields)+2,column=0,columnspan=2,sticky="ew",padx=8)
        def save():
            values = {key: value.get() for key,value in self.vars.items()}
            values["check_updates"] = self.updates.get()
            try:
                on_save(values)
                self.destroy()
            except (ValueError, OSError) as exc:
                self.error.set(str(exc))
        button(self,text="설정 저장",accent=True,command=save).grid(row=1,column=0,sticky="e",padx=18,pady=(0,12))
