"""Local stage scripts, persistent visual notes and explicit audio cue triggers.

The PDF widget follows CTkPDFViewer's CustomTkinter + PyMuPDF approach and public
name. This maintained adaptation renders a single page at a time on the Tk
thread, preserves page aspect ratios, and adds rectangle annotations. Upstream:
https://github.com/Akascape/CTkPDFViewer (Akash Bora, MIT).

CTkPDFViewer notice:
Copyright (c) 2023 Akash Bora
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import tkinter as tk
from tkinter import colorchooser, filedialog
from typing import Callable
import uuid

import customtkinter as ctk

from ui_theme import FONT_FAMILY, button, font, label


ACTIONS = {"play": "재생", "pause": "일시정지", "stop": "정지",
           "fade_in": "오토 페이드인", "fade_out": "오토 페이드아웃",
           "volume": "볼륨 변경", "seek": "재생 위치 이동"}
_COLORS = {"YELLOW": "#fff59d", "BRIGHT_GREEN": "#a5d6a7", "TURQUOISE": "#80deea",
           "PINK": "#f48fb1", "BLUE": "#90caf9", "RED": "#ef9a9a",
           "DARK_BLUE": "#7986cb", "TEAL": "#80cbc4", "GREEN": "#81c784",
           "VIOLET": "#ce93d8", "DARK_RED": "#e57373", "DARK_YELLOW": "#dce775",
           "GRAY_50": "#bdbdbd", "GRAY_25": "#e0e0e0", "BLACK": "#757575"}


class ScriptError(ValueError):
    """An actionable local-document or annotation error."""


@dataclass
class ScriptDocument:
    path: Path
    digest: str
    text: str = ""
    styles: list[dict] = field(default_factory=list)


def read_script(path: str | Path) -> ScriptDocument:
    """Read text without changing the original, retaining DOCX run styles/order."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ScriptError("대본 파일을 찾을 수 없습니다.")
    data = path.read_bytes()
    document = ScriptDocument(path, hashlib.sha256(data).hexdigest())
    if path.suffix.lower() in {".txt", ".text"}:
        encodings = ("utf-16",) if data.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "cp949")
        for encoding in encodings:
            try:
                document.text = data.decode(encoding)
                break
            except UnicodeError:
                continue
        else:
            raise ScriptError("텍스트 인코딩을 읽을 수 없습니다. UTF-8로 저장해 주세요.")
        document.text = document.text.replace("\r\n", "\n").replace("\r", "\n")
    elif path.suffix.lower() == ".docx":
        try:
            from docx import Document
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except ImportError as exc:
            raise ScriptError("DOCX 보기에 python-docx가 필요합니다.") from exc
        try:
            source = Document(path)
            chunks: list[str] = []
            offset = 0

            def append(text: str, style: dict | None = None) -> None:
                nonlocal offset
                if style and text:
                    document.styles.append({"start": offset, "end": offset + len(text), **style})
                chunks.append(text)
                offset += len(text)

            def paragraph_text(paragraph) -> None:
                for item in paragraph.iter_inner_content():
                    runs = item.runs if hasattr(item, "runs") else [item]
                    for run in runs:
                        style = {}
                        if run.bold:
                            style["bold"] = True
                        if run.italic:
                            style["italic"] = True
                        if run.font.color.rgb is not None:
                            style["foreground"] = "#" + str(run.font.color.rgb)
                        if run.font.highlight_color is not None:
                            name = str(run.font.highlight_color).split(" ")[0]
                            if name in _COLORS:
                                style["background"] = _COLORS[name]
                        append(run.text, style)
                append("\n")

            def blocks(container) -> None:
                for block in container.iter_inner_content():
                    if isinstance(block, Paragraph):
                        paragraph_text(block)
                    elif isinstance(block, Table):
                        for row in block.rows:
                            seen = set()
                            for cell in row.cells:
                                if cell._tc in seen:
                                    continue
                                seen.add(cell._tc)
                                blocks(cell)
                                append("\t")
                            append("\n")

            blocks(source)
            document.text = "".join(chunks)
        except Exception as exc:
            raise ScriptError(f"DOCX를 읽을 수 없습니다: {exc}") from exc
    elif path.suffix.lower() != ".pdf":
        raise ScriptError("TXT, DOCX, PDF 대본을 선택해 주세요.")
    return document


def annotation_path(document: ScriptDocument) -> Path:
    return document.path.with_name(document.path.name + ".scene.json")


def validate_annotation(item: dict, document: ScriptDocument) -> dict:
    """Validate persisted input before it reaches Tk tags or cue callbacks."""
    if not isinstance(item, dict) or item.get("kind") not in {"highlight", "color", "cue"}:
        raise ScriptError("지원하지 않는 대본 표시 형식입니다.")
    item = dict(item)
    if not isinstance(item.get("id"), str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", item["id"]):
        raise ScriptError("대본 표시 ID가 잘못되었습니다.")
    if document.path.suffix.lower() == ".pdf":
        if type(item.get("page")) is not int or item["page"] < 0:
            raise ScriptError("PDF 표시 페이지가 잘못되었습니다.")
        rect = item.get("rect")
        if (not isinstance(rect, list) or len(rect) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in rect)
                or rect[0] >= rect[2] or rect[1] >= rect[3]):
            raise ScriptError("PDF 표시 범위가 잘못되었습니다.")
    elif (type(item.get("start")) is not int or type(item.get("end")) is not int
          or not 0 <= item["start"] < item["end"] <= len(document.text)):
        raise ScriptError("대본 표시의 글자 범위가 잘못되었습니다.")
    if item["kind"] == "cue":
        if item.get("action") not in ACTIONS or not isinstance(item.get("target"), str):
            raise ScriptError("오디오 큐의 동작 또는 대상이 잘못되었습니다.")
        item["target"] = item["target"].strip()
        if len(item["target"]) > 300:
            raise ScriptError("오디오 큐 대상이 너무 깁니다.")
        if item["action"] in {"volume", "seek"}:
            value = item.get("value")
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ScriptError("볼륨·재생 위치는 0 이상의 유한한 숫자여야 합니다.")
            if item["action"] == "volume" and value > 100:
                raise ScriptError("볼륨은 0~100% 범위로 입력해 주세요.")
    elif not isinstance(item.get("color"), str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", item["color"]):
        raise ScriptError("표시 색상은 #RRGGBB 형식이어야 합니다.")
    return item


def load_annotations(document: ScriptDocument) -> list[dict]:
    path = annotation_path(document)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ScriptError("지원하지 않는 대본 표시 파일 버전입니다.")
        if data.get("document_sha256") != document.digest:
            raise ScriptError("대본 원본이 변경되어 이전 표시를 적용하지 않았습니다. 표시 파일을 확인해 주세요.")
        items = data.get("annotations")
        if not isinstance(items, list) or len(items) > 10000:
            raise ScriptError("대본 표시 목록이 잘못되었습니다.")
        result = [validate_annotation(item, document) for item in items]
        if len({item["id"] for item in result}) != len(result):
            raise ScriptError("대본 표시 ID가 중복되었습니다.")
        return result
    except (OSError, ValueError, TypeError) as exc:
        raise ScriptError(f"대본 표시 파일을 읽을 수 없습니다: {exc}") from exc


def save_annotations(document: ScriptDocument, annotations: list[dict]) -> None:
    """Atomically publish sidecar notes; never rewrite a script or its PDF."""
    items = [validate_annotation(item, document) for item in annotations]
    payload = {"version": 1, "document_sha256": document.digest, "annotations": items}
    destination = annotation_path(document)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix=".scene-notes-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class CTkPDFViewer(ctk.CTkFrame):
    """CTkPDFViewer adaptation: lazy pages, rectangle selection, original untouched."""

    def __init__(self, master, *, file: str | Path, on_error=None, on_cue_selected=None, **kwargs):
        super().__init__(master, **kwargs)
        try:
            import pymupdf as fitz
        except ImportError as exc:
            self.destroy()
            raise ScriptError("PDF 보기에 PyMuPDF가 필요합니다.") from exc
        self._fitz = fitz
        try:
            self.document = fitz.open(str(file))
            if self.document.needs_pass:
                self.document.close()
                raise ScriptError("암호가 설정된 PDF입니다. 암호를 해제한 사본을 선택해 주세요.")
            if not len(self.document):
                self.document.close()
                raise ScriptError("PDF에 페이지가 없습니다.")
        except Exception as exc:
            self.destroy()
            raise ScriptError(f"PDF를 열 수 없습니다: {exc}") from exc
        self.on_error = on_error or (lambda _message: None)
        self.on_cue_selected = on_cue_selected or (lambda _id: None)
        self.page = 0
        self.zoom = 1.0
        self.annotations: list[dict] = []
        self.selection: list[float] | None = None
        self._photo = None
        self._render_timer = None
        self._drag_start = None
        self._closed = False
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=0, column=0, columnspan=2, sticky="ew", pady=4)
        nav.columnconfigure(1, weight=1)
        button(nav, text="◀ 이전", compact=True, command=lambda: self.show_page(self.page - 1)).grid(row=0, column=0)
        self.page_var = tk.StringVar(self)
        label(nav, textvariable=self.page_var, muted=True).grid(row=0, column=1, padx=8)
        button(nav, text="다음 ▶", compact=True, command=lambda: self.show_page(self.page + 1)).grid(row=0, column=2)
        self.canvas = tk.Canvas(self, bg="#dce3ed", highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        scrollbar = ctk.CTkScrollbar(self, command=self.canvas.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        horizontal = ctk.CTkScrollbar(self, orientation="horizontal", command=self.canvas.xview)
        horizontal.grid(row=2, column=0, sticky="ew")
        self.canvas.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        self.canvas.bind("<Configure>", lambda _event: self.schedule_render())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.schedule_render()

    def _wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120) or (-1 if event.delta > 0 else 1), "units")
        return "break"

    def schedule_render(self):
        if self._closed:
            return
        if self._render_timer is not None:
            self.after_cancel(self._render_timer)
        self._render_timer = self.after(100, self._render)

    def show_page(self, page: int):
        if not 0 <= page < len(self.document):
            return
        self.page = page
        self.selection = None
        self.canvas.yview_moveto(0)
        self.schedule_render()

    def set_annotations(self, annotations: list[dict]):
        self.annotations = annotations
        self.schedule_render()

    def _render(self):
        self._render_timer = None
        if self._closed:
            return
        try:
            from PIL import Image, ImageDraw, ImageOps, ImageTk
            page = self.document[self.page]
            width = max(240, self.canvas.winfo_width() - 20)
            scale = min(4.0, max(0.2, width / page.rect.width * self.zoom))
            pix = page.get_pixmap(matrix=self._fitz.Matrix(scale, scale), alpha=False)
            picture = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            # Color notes recolor ink in the selected region while preserving its
            # raster shape. They are display-only, including for scanned PDFs.
            for item in self.annotations:
                if item["page"] != self.page or item["kind"] == "cue":
                    continue
                box = [round(v * (pix.width if i % 2 == 0 else pix.height)) for i, v in enumerate(item["rect"])]
                if item["kind"] == "color":
                    crop = picture.crop(box).convert("L")
                    picture.paste(ImageOps.colorize(crop, black=item["color"], white="white"), box)
                else:
                    overlay = Image.new("RGBA", picture.size, (0, 0, 0, 0))
                    ImageDraw.Draw(overlay).rectangle(box, fill=item["color"] + "66")
                    picture = Image.alpha_composite(picture.convert("RGBA"), overlay).convert("RGB")
            self._photo = ImageTk.PhotoImage(picture, master=self.canvas)
            self.canvas.delete("all")
            self.canvas.create_image(10, 5, image=self._photo, anchor="nw")
            self.image_size = (pix.width, pix.height)
            self.canvas.configure(scrollregion=(0, 0, pix.width + 20, pix.height + 10))
            for item in self.annotations:
                if item["kind"] != "cue" or item["page"] != self.page:
                    continue
                coordinates = self._canvas_rect(item["rect"])
                tag = "cue_" + item["id"]
                self.canvas.create_rectangle(*coordinates, outline="#2563eb", width=3, tags=(tag,))
                self.canvas.create_text(coordinates[0] + 3, coordinates[1] + 3,
                                        anchor="nw", fill="#1d4ed8", text="♪ " + item["target"],
                                        font=(FONT_FAMILY, 11, "bold"), tags=(tag,))
                self.canvas.tag_bind(tag, "<Button-1>", lambda _event, key=item["id"]: self.on_cue_selected(key))
            self._draw_selection()
            self.page_var.set(f"{self.page + 1} / {len(self.document)} 쪽 · {self.zoom * 100:.0f}%")
        except Exception as exc:
            self.on_error(f"PDF 페이지를 표시할 수 없습니다: {exc}")

    def _canvas_rect(self, rect):
        return [10 + rect[0] * self.image_size[0], 5 + rect[1] * self.image_size[1],
                10 + rect[2] * self.image_size[0], 5 + rect[3] * self.image_size[1]]

    def _point(self, event):
        width, height = getattr(self, "image_size", (1, 1))
        return (min(1, max(0, (self.canvas.canvasx(event.x) - 10) / width)),
                min(1, max(0, (self.canvas.canvasy(event.y) - 5) / height)))

    def _press(self, event):
        self._drag_start = self._point(event)

    def _drag(self, event):
        if self._drag_start is None:
            return
        x, y = self._point(event)
        sx, sy = self._drag_start
        self.selection = [min(x, sx), min(y, sy), max(x, sx), max(y, sy)]
        self._draw_selection()

    def _release(self, event):
        self._drag(event)
        self._drag_start = None
        if self.selection and (self.selection[2] - self.selection[0] < .003 or self.selection[3] - self.selection[1] < .003):
            self.selection = None
            self.canvas.delete("selection")

    def _draw_selection(self):
        self.canvas.delete("selection")
        if self.selection and hasattr(self, "image_size"):
            self.canvas.create_rectangle(*self._canvas_rect(self.selection), outline="#f97316", width=2,
                                         dash=(4, 3), tags=("selection",))

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._render_timer is not None:
            self.after_cancel(self._render_timer)
            self._render_timer = None
        self.document.close()


class ScriptViewerFrame(ctk.CTkFrame):
    """Right-hand local script surface. Cue GO is the only playback trigger."""

    def __init__(self, master, on_cue: Callable[..., None], on_error=None, **kwargs):
        super().__init__(master, fg_color="white", **kwargs)
        self.on_cue = on_cue
        self.on_error = on_error
        self.document: ScriptDocument | None = None
        self.annotations: list[dict] = []
        self.pdf: CTkPDFViewer | None = None
        self.font_size = 18
        self._selected_cue = None
        self._closed = False
        self._annotation_backup_needed = False
        self._style_fonts = []
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        header.columnconfigure(0, weight=1)
        self.name_var = tk.StringVar(self, "TXT · DOCX · PDF")
        label(header, textvariable=self.name_var, size=14, bold=True, wraplength=260).grid(row=0, column=0, sticky="w")
        button(header, text="대본 열기", compact=True, command=self.open_file).grid(row=0, column=1)
        toolbar = ctk.CTkFrame(self, fg_color="#f3f6fa")
        toolbar.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        button(toolbar, text="A−", compact=True, command=lambda: self._resize_font(-2)).grid(row=0, column=0, padx=3, pady=5)
        button(toolbar, text="A+", compact=True, command=lambda: self._resize_font(2)).grid(row=0, column=1, padx=3, pady=5)
        button(toolbar, text="형광펜", compact=True, command=lambda: self._add_style("highlight")).grid(row=0, column=2, padx=3, pady=5)
        button(toolbar, text="글자색", compact=True, command=lambda: self._add_style("color")).grid(row=0, column=3, padx=3, pady=5)
        button(toolbar, text="♪ 오디오 큐 추가", compact=True, accent=True, command=self._add_cue).grid(row=1, column=0, columnspan=2, sticky="ew", padx=3, pady=(0, 5))
        button(toolbar, text="선택 표시 지우기", compact=True, command=self._remove_selection).grid(row=1, column=2, columnspan=2, sticky="ew", padx=3, pady=(0, 5))
        for column in range(4):
            toolbar.columnconfigure(column, weight=1)
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=3, column=0, sticky="nsew", padx=12)
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=1)
        self.textbox = ctk.CTkTextbox(self.body, wrap="word", font=font(self.font_size),
                                      fg_color="#fcfdff", text_color="#17253d")
        self.textbox.grid(row=0, column=0, sticky="nsew")
        self.textbox.insert("1.0", "대본을 열어 주세요.\n\n글자를 드래그해 형광펜·글자색·오디오 큐를 추가할 수 있습니다.\nPDF는 페이지 위에서 사각형으로 범위를 선택합니다.\n\n오디오 큐는 아래 GO 버튼으로 실행합니다.")
        self.textbox.configure(state="disabled")
        self.textbox._textbox.configure(exportselection=False)
        self.status_var = tk.StringVar(self, "표시는 원본 옆 .scene.json 파일에 자동 저장됩니다.")
        label(self, textvariable=self.status_var, size=11, muted=True, wraplength=500).grid(row=4, column=0, sticky="ew", padx=14, pady=(5, 0))
        self.cue_list = ctk.CTkScrollableFrame(self, height=72, fg_color="#eff5ff",
            label_text="오디오 하이라이팅 · GO로 실행", label_font=font(12))
        # CTkScrollableFrame's scrollbar defaults to 200 px and otherwise forces
        # a taller grid row even when the canvas height is set to a small value.
        self.cue_list._scrollbar.configure(height=72)
        self.cue_list.grid(row=5, column=0, sticky="ew", padx=12, pady=(6, 12))
        self.cue_list.columnconfigure(0, weight=1)
        self._refresh_cues()

    def _error(self, message):
        self.status_var.set(str(message))
        if self.on_error is not None:
            self.on_error(str(message))

    def update_settings(self, settings: dict):
        size = settings.get("script_font_size", self.font_size)
        if isinstance(size, (int, float)):
            self.font_size = max(10, min(48, int(size)))
            self._apply_styles()

    def open_file(self, path=None):
        if self._closed:
            return
        if path is None:
            path = filedialog.askopenfilename(parent=self, title="대본 선택", filetypes=[
                ("대본", "*.txt *.docx *.pdf"), ("텍스트", "*.txt"),
                ("Word 문서", "*.docx"), ("PDF", "*.pdf")])
        if not path:
            return
        try:
            document = read_script(path)
            # Validate a PDF before replacing an already-open usable document.
            pdf = CTkPDFViewer(self.body, file=document.path, on_error=self._error,
                              on_cue_selected=self._select_cue) if document.path.suffix.lower() == ".pdf" else None
        except Exception as exc:
            self._error(str(exc))
            return
        if self.pdf is not None:
            self.pdf.close()
            self.pdf.destroy()
        self.document = document
        self.pdf = pdf
        self.annotations = []
        self._selected_cue = None
        self._annotation_backup_needed = False
        annotation_error = ""
        try:
            self.annotations = load_annotations(document)
            if self.pdf is not None:
                self.annotations = [a for a in self.annotations if a["page"] < len(self.pdf.document)]
        except ScriptError as exc:
            annotation_error = str(exc)
            self._annotation_backup_needed = True
        self.name_var.set(document.path.name)
        if pdf is not None:
            self.textbox.grid_remove()
            pdf.grid(row=0, column=0, sticky="nsew")
        else:
            self.textbox.grid()
            self.textbox.configure(state="normal")
            self.textbox.delete("1.0", "end")
            self.textbox.insert("1.0", document.text)
            self.textbox.configure(state="disabled")
            self.textbox.yview_moveto(0)
        self._apply_styles()
        self._refresh_cues()
        self.status_var.set(annotation_error or "범위 선택 → 표시 추가 · 오디오 큐는 GO로 실행합니다.")

    def _resize_font(self, step):
        self.font_size = max(10, min(48, self.font_size + step))
        if self.pdf is not None:
            self.pdf.zoom = max(.5, min(3.0, self.pdf.zoom + step / 10))
            self.pdf.schedule_render()
        else:
            self._apply_styles()

    def _apply_styles(self):
        self.textbox.configure(font=font(self.font_size))
        if self.pdf is not None:
            self.pdf.set_annotations(self.annotations)
            return
        text = self.textbox._textbox
        for name in text.tag_names():
            if name.startswith(("style_", "note_")):
                text.tag_delete(name)
        self._style_fonts = []
        if self.document is None:
            return
        for index, style in enumerate(self.document.styles):
            name = f"style_{index}"
            options = {key: style[key] for key in ("foreground", "background") if key in style}
            if style.get("bold") or style.get("italic"):
                from tkinter import font as tkfont
                # Negative Tk font sizes are pixels, matching CTkFont scaling.
                styled_font = tkfont.Font(root=self, family=FONT_FAMILY,
                    size=-round(self.font_size * self._get_widget_scaling()),
                    weight="bold" if style.get("bold") else "normal",
                    slant="italic" if style.get("italic") else "roman")
                self._style_fonts.append(styled_font)
                options["font"] = styled_font
            text.tag_configure(name, **options)
            text.tag_add(name, f"1.0+{style['start']}c", f"1.0+{style['end']}c")
        for item in self.annotations:
            tag = "note_" + item["id"]
            if item["kind"] == "cue":
                text.tag_configure(tag, background="#dbeafe", foreground="#1d4ed8", underline=True)
                text.tag_bind(tag, "<Button-1>", lambda _event, key=item["id"]: self._select_cue(key))
            else:
                text.tag_configure(tag, **{"background" if item["kind"] == "highlight" else "foreground": item["color"]})
            text.tag_add(tag, f"1.0+{item['start']}c", f"1.0+{item['end']}c")
        text.tag_raise("sel")

    def _selection(self, *, allow_page=False):
        if self.document is None:
            raise ScriptError("대본을 먼저 열어 주세요.")
        if self.pdf is not None:
            rect = self.pdf.selection
            if rect is None and allow_page:
                rect = [0.02, 0.02, .98, .08]
            if rect is None:
                raise ScriptError("PDF 위에서 드래그해 표시할 범위를 선택해 주세요.")
            return {"page": self.pdf.page, "rect": list(rect)}
        ranges = self.textbox._textbox.tag_ranges("sel")
        if len(ranges) != 2:
            raise ScriptError("대본에서 표시할 글자를 드래그해 선택해 주세요.")
        text = self.textbox._textbox
        start = len(text.get("1.0", ranges[0]))
        end = min(len(self.document.text), len(text.get("1.0", ranges[1])))
        if start >= end:
            raise ScriptError("한 글자 이상 선택해 주세요.")
        return {"start": start, "end": end}

    def _persist(self):
        try:
            backup = None
            if self._annotation_backup_needed:
                original = annotation_path(self.document)
                if original.exists():
                    backup = original.with_name(original.name + ".backup-" + uuid.uuid4().hex[:8])
                    with backup.open("xb") as stream:
                        stream.write(original.read_bytes())
                self._annotation_backup_needed = False
            save_annotations(self.document, self.annotations)
            self.status_var.set("대본 표시를 저장했습니다." + (f" 이전 표시 백업: {backup.name}" if backup else " 원본 파일은 그대로 유지됩니다."))
            return True
        except (OSError, ScriptError) as exc:
            self._error(f"표시를 저장하지 못했습니다: {exc}")
            return False

    def _add_style(self, kind):
        try:
            selected = self._selection()
        except ScriptError as exc:
            self._error(str(exc))
            return
        color = colorchooser.askcolor("#fff59d" if kind == "highlight" else "#dc2626",
                                     parent=self, title="형광펜 색" if kind == "highlight" else "글자색")[1]
        if not color:
            return
        item = {"id": uuid.uuid4().hex, "kind": kind, "color": color, **selected}
        self.annotations.append(item)
        self._persist()
        self._apply_styles()

    def _add_cue(self):
        try:
            selected = self._selection(allow_page=True)
        except ScriptError as exc:
            self._error(str(exc))
            return
        window = ctk.CTkToplevel(self)
        window.title("오디오 하이라이팅 추가")
        window.geometry("390x370")
        window.transient(self.winfo_toplevel())
        window.resizable(False, False)
        window.columnconfigure(0, weight=1)
        label(window, text="BGM 번호 또는 목록의 파일명", bold=True).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 4))
        target = ctk.CTkEntry(window, font=font(), placeholder_text="예: 2, bgm2_song.mp3")
        target.grid(row=1, column=0, sticky="ew", padx=20)
        action = ctk.CTkOptionMenu(window, values=list(ACTIONS.values()), font=font())
        action.grid(row=2, column=0, sticky="ew", padx=20, pady=12)
        value_label = label(window, text="수치 입력 (볼륨 % / 재생 위치 초)", muted=True)
        value_label.grid(row=3, column=0, sticky="w", padx=20)
        value_entry = ctk.CTkEntry(window, font=font(), placeholder_text="예: 50 (%) 또는 12.5 (초)", state="disabled")
        value_entry.grid(row=4, column=0, sticky="ew", padx=20, pady=(2, 10))
        action.configure(command=lambda choice: value_entry.configure(
            state="normal" if choice in (ACTIONS["volume"], ACTIONS["seek"]) else "disabled"))
        label(window, text="대상을 비우면 현재 음원에 적용합니다.\n큐는 추가 후 GO 버튼으로 실행합니다.", muted=True).grid(row=5, column=0, sticky="w", padx=20)

        def add():
            key = next(key for key, value in ACTIONS.items() if value == action.get())
            item = {"id": uuid.uuid4().hex, "kind": "cue", "action": key,
                    "target": target.get().strip(), **selected}
            try:
                if key in {"volume", "seek"}:
                    item["value"] = float(value_entry.get())
                item = validate_annotation(item, self.document)
            except (ValueError, ScriptError) as exc:
                self._error(f"큐 수치를 확인해 주세요: {exc}")
                value_entry.focus_set()
                return
            self.annotations.append(item)
            self._persist()
            self._apply_styles()
            self._refresh_cues()
            window.destroy()

        button(window, text="큐 추가", accent=True, command=add).grid(row=6, column=0, sticky="ew", padx=20, pady=15)
        target.focus_set()

    def _remove_selection(self):
        try:
            selected = self._selection()
        except ScriptError as exc:
            self._error(str(exc))
            return
        def overlaps(item):
            if self.pdf is not None:
                a, b = selected["rect"], item["rect"]
                return item["page"] == selected["page"] and a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
            return item["start"] < selected["end"] and selected["start"] < item["end"]
        self.annotations = [item for item in self.annotations if not overlaps(item)]
        self._persist()
        self._apply_styles()
        self._refresh_cues()

    def _select_cue(self, key):
        self._selected_cue = key
        cue = next((item for item in self.annotations if item["id"] == key), None)
        if cue is not None:
            self.status_var.set(f"선택한 큐: {cue['target'] or '현재 음원'} · {ACTIONS[cue['action']]} · 아래 GO로 실행")

    def _show_cue(self, item):
        self._select_cue(item["id"])
        if self.pdf is not None:
            self.pdf.show_page(item["page"])
            self.pdf.selection = list(item["rect"])
        else:
            self.textbox.see(f"1.0+{item['start']}c")
            self.textbox._textbox.tag_remove("sel", "1.0", "end")
            self.textbox._textbox.tag_add("sel", f"1.0+{item['start']}c", f"1.0+{item['end']}c")

    def _execute_cue(self, item):
        try:
            if item["action"] in {"volume", "seek"}:
                item = validate_annotation(item, self.document)
                self.on_cue(item["action"], item["target"], item["value"])
            else:
                self.on_cue(item["action"], item["target"])
            self.status_var.set(f"실행: {item['target'] or '현재 음원'} · {ACTIONS[item['action']]}")
        except Exception as exc:
            self._error(f"큐를 실행할 수 없습니다: {exc}")

    def _delete_cue(self, key):
        self.annotations = [item for item in self.annotations if item["id"] != key]
        self._persist()
        self._apply_styles()
        self._refresh_cues()

    def _refresh_cues(self):
        for widget in self.cue_list.winfo_children():
            widget.destroy()
        cues = [item for item in self.annotations if item["kind"] == "cue"]
        cues.sort(key=lambda item: (item.get("page", 0), item.get("start", item.get("rect", [0, 0])[1])))
        if not cues:
            label(self.cue_list, text="대본 범위를 선택한 뒤 ♪ 오디오 큐 추가", muted=True, size=12).grid(row=0, column=0, sticky="w")
        for row, item in enumerate(cues):
            location = f"{item['page'] + 1}쪽" if "page" in item else f"{self.document.text[:item['start']].count(chr(10)) + 1}행"
            title = f"{location} · {item['target'] or '현재 음원'} · {ACTIONS[item['action']]}"
            if item["action"] in {"volume", "seek"}:
                title += f" {item['value']:g}{'%' if item['action'] == 'volume' else '초'}"
            cue_label = label(self.cue_list, text=title, size=12, wraplength=260)
            cue_label.grid(row=row, column=0, sticky="w", padx=3, pady=3)
            button(self.cue_list, text="위치", compact=True, command=lambda cue=item: self._show_cue(cue)).grid(row=row, column=1, padx=2, pady=3)
            go = button(self.cue_list, text="GO", compact=True, accent=True, command=lambda cue=item: self._execute_cue(cue))
            go.configure(width=44)
            go.grid(row=row, column=2, padx=2, pady=3)
            delete = button(self.cue_list, text="×", compact=True, command=lambda key=item["id"]: self._delete_cue(key))
            delete.configure(width=28)
            delete.grid(row=row, column=3, padx=2, pady=3)

    def close(self):
        self._closed = True
        if self.pdf is not None:
            self.pdf.close()

