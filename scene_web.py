"""Native Edge WebView2 embedding and deterministic cleanup for Tk panels."""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import tkinter as tk

from backend import AppError


WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/microsoft-edge/webview2/#download-section"
_RUNTIME_KEY = r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def webview2_runtime_version() -> str | None:
    """Check both per-user and per-machine Evergreen registrations."""
    if sys.platform != "win32":
        return None
    import winreg

    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(root, _RUNTIME_KEY, 0, winreg.KEY_READ | view) as key:
                    version, _kind = winreg.QueryValueEx(key, "pv")
                if isinstance(version, str) and re.fullmatch(r"\d+(?:\.\d+){3}", version) and any(int(n) for n in version.split(".")):
                    return version
            except OSError:
                continue
    return None


def create_browser(parent):
    """Lazily load tkwebview so local audio/scripts need no browser runtime."""
    if sys.platform != "win32":
        raise AppError("앱 안의 웹 화면은 Windows에서 지원합니다. 브라우저에서 열기를 사용하세요.")
    if not webview2_runtime_version():
        raise AppError("Microsoft Edge WebView2 Runtime이 필요합니다.\n"
                       "WebView2 설치 버튼으로 설치한 뒤 열기를 다시 누르세요.\n" + WEBVIEW2_DOWNLOAD_URL)

    # Both stage panels share a writable, persistent profile, even in an
    # installed/frozen app whose executable directory may be read-only.
    profile = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "SCENE-App" / "WebView2"
    os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", str(profile))
    from tkwebview import TkWebview

    class EmbeddedBrowser(TkWebview):
        def __init__(self, master):
            self._disposed = False
            self._focus_binding = None
            self._top = master.winfo_toplevel()
            try:
                super().__init__(master, width=640, height=480)
                # Upstream WebView2 can retain focus after a click in Tk.
                # A toplevel binding covers dynamically created CTk controls
                # without replacing their own click handlers.
                self._focus_binding = self._top.bind("<Button-1>", self._return_tk_focus, add="+")
            except Exception:
                self.destroy()
                raise

        @staticmethod
        def _return_tk_focus(event):
            try:
                event.widget.focus_force()
            except tk.TclError:
                pass

        def destroy(self):
            if self._disposed:
                return
            self._disposed = True
            if self._focus_binding:
                self._top.unbind("<Button-1>", self._focus_binding)
                self._focus_binding = None
            native = getattr(self, "webview", None)
            if native is not None:
                # TkWebview.destroy_webview() only destroys its Tk Frame in
                # embedded mode. Release the native controller first, while
                # the parent HWND still exists, instead of waiting for GC.
                native.destroy()
            if hasattr(self, "_w"):
                super().destroy()

    return EmbeddedBrowser(parent)
