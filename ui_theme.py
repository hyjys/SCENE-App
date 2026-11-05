"""Shared CustomTkinter appearance and privately loaded Korean fonts."""

from __future__ import annotations

import ctypes
from pathlib import Path
import sys
from tkinter import font as tkfont

import customtkinter as ctk
from ui_translations import tr


VERSION = "0.4"
FONT_FAMILY = "NanumGothic"
BACKGROUND = "#f3f6fa"
TEXT = "#17253d"
MUTED = "#66758c"
ACCENT = "#2563eb"
_loaded_fonts: list[Path] = []


def enable_dpi_awareness() -> None:
    """Set awareness before Tk caches the display's pixel dimensions."""
    if sys.platform == "win32":
        try:
            # Match CustomTkinter's per-monitor awareness, but run before its
            # Tk superclass creates the first window and caches screen sizes.
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass


def resource_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def prepare_ui() -> None:
    """Register bundled fonts before creating Tk; never install system fonts."""
    enable_dpi_awareness()
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    if _loaded_fonts:
        return
    for name in ("NanumGothic-Regular.ttf", "NanumGothic-Bold.ttf"):
        path = resource_dir() / "assets" / "fonts" / name
        if not path.is_file():
            raise RuntimeError(tr("동봉된 글꼴 파일을 찾을 수 없습니다: {path}", path=path))
        if sys.platform == "win32":
            add_font = ctypes.windll.gdi32.AddFontResourceExW
            add_font.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
            add_font.restype = ctypes.c_int
            loaded = add_font(str(path), 0x10, None)  # FR_PRIVATE: this process only.
        else:
            loaded = ctk.FontManager.load_font(str(path))
        if not loaded:
            raise RuntimeError(tr("동봉된 글꼴을 불러올 수 없습니다: {path}", path=path))
        _loaded_fonts.append(path)


def configure_fonts(root) -> None:
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkFixedFont"):
        tkfont.nametofont(name, root=root).configure(family=FONT_FAMILY, size=10)
    # CustomTkinter's widget defaults use pixel sizes.
    ctk.ThemeManager.theme["CTkFont"]["family"] = FONT_FAMILY


def fit_window(root, *, width: int, height: int, min_width: int, min_height: int) -> None:
    """Fit logical CTk dimensions inside the physical Windows work area."""
    left, top = 0, 0
    right, bottom = root.winfo_screenwidth(), root.winfo_screenheight()
    if sys.platform == "win32":
        from ctypes import wintypes
        area = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0):
            left, top, right, bottom = area.left, area.top, area.right, area.bottom
    scale = root._get_window_scaling()
    logical_width = max(320, int((right - left - 48) / scale))
    logical_height = max(320, int((bottom - top - 76) / scale))
    width, height = min(width, logical_width), min(height, logical_height)
    root.minsize(min(min_width, width), min(min_height, height))
    x = left + max(8, int((right - left - width * scale) / 2))
    y = top + max(8, int((bottom - top - height * scale - 38) / 2))
    root.geometry(f"{width}x{height}+{x}+{y}")


def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)


def font_report(root) -> dict:
    regular = tkfont.Font(root=root, family=FONT_FAMILY, size=12)
    bold = tkfont.Font(root=root, family=FONT_FAMILY, size=12, weight="bold")
    if regular.actual("family").lower() != FONT_FAMILY.lower():
        raise RuntimeError(tr("동봉된 나눔고딕 글꼴이 적용되지 않았습니다."))
    return {"family": regular.actual("family"), "bold_family": bold.actual("family"),
            "files": [str(path) for path in _loaded_fonts],
            "korean_width": regular.measure("한글 음원 다운로드")}


def button(master, *, accent: bool = False, compact: bool = False, **kwargs) -> ctk.CTkButton:
    widget = ctk.CTkButton(
        master, height=kwargs.pop("height", 28 if compact else 36), width=kwargs.pop("width", 84 if compact else 100),
        font=font(12 if compact else 13, "bold" if accent else "normal"),
        fg_color=ACCENT if accent else "#e3eaf5",
        hover_color="#1d4ed8" if accent else "#d4deed",
        text_color="white" if accent else TEXT,
        text_color_disabled="#7d8da6", **kwargs,
    )
    widget._canvas.configure(takefocus=True)
    def activate(_event):
        widget.invoke()
        return "break"
    widget.bind("<Return>", activate)
    widget.bind("<space>", activate)
    return widget


class CheckBox(ctk.CTkCheckBox):
    """Expose CTk's pointer-only checkbox to keyboard focus and activation."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._canvas.configure(takefocus=self.cget("state") == "normal")
        self._text_label.configure(highlightthickness=1,
                                   highlightbackground=self._text_label.cget("background"))
        self.bind("<space>", self._activate_from_keyboard)
        self.bind("<Return>", self._activate_from_keyboard)
        self.bind("<FocusIn>", lambda _event: self._text_label.configure(highlightbackground=ACCENT))
        self.bind("<FocusOut>", lambda _event: self._text_label.configure(
            highlightbackground=self._text_label.cget("background")))

    def _activate_from_keyboard(self, _event=None) -> str:
        self.toggle()  # CTkCheckBox.toggle respects the disabled state.
        return "break"

    def configure(self, **kwargs):
        super().configure(**kwargs)
        if "state" in kwargs and hasattr(self, "_canvas"):
            self._canvas.configure(takefocus=kwargs["state"] == "normal")


def label(master, *, muted: bool = False, size: int = 13, bold: bool = False, **kwargs) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, font=font(size, "bold" if bold else "normal"),
                        text_color=MUTED if muted else TEXT, anchor="w", height=22, **kwargs)
