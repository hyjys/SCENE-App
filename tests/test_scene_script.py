"""Document text fidelity, safe annotation persistence and explicit cue execution."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scene_script import (ScriptDocument, ScriptError, ScriptViewerFrame, annotation_path,
                          load_annotations, read_script, save_annotations, validate_annotation)


class ScriptDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def test_txt_decodes_utf8_bom_utf16_and_korean_windows_without_changing_source(self):
        for encoding in ("utf-8-sig", "utf-16", "cp949"):
            with self.subTest(encoding=encoding):
                path = self.folder / f"대본-{encoding}.txt"
                data = "음악 시작\r\n배우: 안녕하세요!".encode(encoding)
                path.write_bytes(data)
                document = read_script(path)
                self.assertEqual(document.text, "음악 시작\n배우: 안녕하세요!")
                self.assertEqual(document.digest, hashlib.sha256(data).hexdigest())
                self.assertEqual(path.read_bytes(), data)

    def test_docx_preserves_paragraph_table_order_run_color_and_highlight(self):
        try:
            from docx import Document
            from docx.enum.text import WD_COLOR_INDEX
            from docx.shared import RGBColor
        except ImportError:
            self.skipTest("python-docx is not installed")
        path = self.folder / "공연.docx"
        source = Document()
        run = source.add_paragraph().add_run("첫 장면")
        run.bold = True
        run.font.color.rgb = RGBColor.from_string("1234AB")
        run.font.highlight_color = WD_COLOR_INDEX.YELLOW
        source.add_table(rows=1, cols=1).cell(0, 0).text = "탁자 안 대사"
        source.add_paragraph("마지막 대사")
        source.save(path)
        before = path.read_bytes()
        document = read_script(path)
        self.assertLess(document.text.index("첫 장면"), document.text.index("탁자 안 대사"))
        self.assertLess(document.text.index("탁자 안 대사"), document.text.index("마지막 대사"))
        style = document.styles[0]
        self.assertEqual(style["foreground"], "#1234AB")
        self.assertEqual(style["background"], "#fff59d")
        self.assertTrue(style["bold"])
        self.assertEqual(document.text[style["start"]:style["end"]], "첫 장면")
        self.assertEqual(path.read_bytes(), before)

    def test_annotation_round_trip_and_cue_does_not_modify_original(self):
        path = self.folder / "대본.txt"
        path.write_text("시작\n대사와 음악\n끝", encoding="utf-8")
        before = path.read_bytes()
        document = read_script(path)
        items = [{"id": "cue1", "kind": "cue", "start": 3, "end": 8,
                  "target": "2.5", "action": "fade_in"},
                 {"id": "hl1", "kind": "highlight", "start": 0, "end": 2, "color": "#fff59d"}]
        save_annotations(document, items)
        self.assertEqual(load_annotations(document), items)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.folder.glob(".scene-notes-*")), [])

    def test_edited_original_refuses_old_offsets_and_leaves_sidecar_intact(self):
        path = self.folder / "대본.txt"
        path.write_text("원본", encoding="utf-8")
        document = read_script(path)
        save_annotations(document, [{"id": "a", "kind": "color", "start": 0, "end": 2, "color": "#123456"}])
        before = annotation_path(document).read_bytes()
        path.write_text("추가된 대사와 원본", encoding="utf-8")
        with self.assertRaisesRegex(ScriptError, "원본이 변경"):
            load_annotations(read_script(path))
        self.assertEqual(annotation_path(document).read_bytes(), before)

    def test_invalid_persisted_cue_cannot_reach_callback(self):
        document = ScriptDocument(self.folder / "a.txt", "digest", "대사")
        base = {"id": "safe", "kind": "cue", "start": 0, "end": 1, "action": "play", "target": "1"}
        for invalid in ({"action": "exec"}, {"start": -1}, {"end": 999}, {"id": "evil;tag"}, {"target": []}):
            with self.subTest(invalid=invalid), self.assertRaises(ScriptError):
                validate_annotation({**base, **invalid}, document)
        cue = {**base, "target": "  3  "}
        self.assertEqual(validate_annotation(cue, document)["target"], "3")

    def test_pdf_rectangles_validate_normalized_page_coordinates(self):
        document = ScriptDocument(self.folder / "a.pdf", "digest")
        item = {"id": "pdf1", "kind": "highlight", "page": 2,
                "rect": [.1, .2, .8, .3], "color": "#abcdef"}
        self.assertEqual(validate_annotation(item, document), item)
        for invalid in ({"page": -1}, {"rect": [0, 0, float("nan"), 1]}, {"rect": [0, 0, 2, 1]}, {"rect": [.5, .5, .1, .9]}):
            with self.subTest(invalid=invalid), self.assertRaises(ScriptError):
                validate_annotation({**item, **invalid}, document)

    def test_volume_and_seek_cues_reject_nan_negative_and_out_of_range_values(self):
        document = ScriptDocument(self.folder / "a.txt", "digest", "대사")
        base = {"id": "value", "kind": "cue", "start": 0, "end": 1, "action": "volume", "target": "1", "value": 50}
        self.assertEqual(validate_annotation(base, document)["value"], 50)
        for value in (float("nan"), float("inf"), -1, 101, True, "50", None):
            with self.subTest(volume=value), self.assertRaises(ScriptError):
                validate_annotation({**base, "value": value}, document)
        for value in (float("nan"), float("inf"), -1, False, "20", None):
            with self.subTest(seek=value), self.assertRaises(ScriptError):
                validate_annotation({**base, "action": "seek", "value": value}, document)
        self.assertEqual(validate_annotation({**base, "action": "seek", "value": 123.5}, document)["value"], 123.5)

    def test_numeric_cue_passes_value_to_audio_callback(self):
        frame = Mock()
        frame.document = ScriptDocument(self.folder / "a.txt", "digest", "大本")
        cue = {"id": "v", "kind": "cue", "start": 0, "end": 1, "action": "volume", "target": "2", "value": 51}
        ScriptViewerFrame._execute_cue(frame, cue)
        frame.on_cue.assert_called_once_with("volume", "2", 51)

    def test_atomic_save_failure_preserves_previous_annotations(self):
        path = self.folder / "대본.txt"
        path.write_text("음향", encoding="utf-8")
        document = read_script(path)
        items = [{"id": "cue", "kind": "cue", "start": 0, "end": 2, "target": "1", "action": "stop"}]
        save_annotations(document, items)
        original = annotation_path(document).read_bytes()
        with patch("scene_script.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                save_annotations(document, [])
        self.assertEqual(annotation_path(document).read_bytes(), original)
        self.assertEqual(list(self.folder.glob(".scene-notes-*")), [])

    def test_selection_only_marks_and_go_explicitly_calls_audio(self):
        frame = Mock()
        frame.annotations = [{"id": "a", "kind": "cue", "target": "13.5", "action": "fade_out"}]
        ScriptViewerFrame._select_cue(frame, "a")
        frame.on_cue.assert_not_called()
        self.assertEqual(frame._selected_cue, "a")
        ScriptViewerFrame._execute_cue(frame, frame.annotations[0])
        frame.on_cue.assert_called_once_with("fade_out", "13.5")


class ScriptViewerGuiTests(unittest.TestCase):
    def setUp(self):
        import customtkinter as ctk
        from ui_theme import prepare_ui
        prepare_ui()
        self.root = ctk.CTk()
        self.root.withdraw()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.callback = Mock()
        self.viewer = ScriptViewerFrame(self.root, self.callback, on_error=self.errors.append)
        self.viewer.pack(fill="both", expand=True)
        self.root.update_idletasks()

    def tearDown(self):
        self.viewer.close()
        for timer in self.root.tk.call("after", "info"):
            self.root.tk.call("after", "cancel", timer)
        self.root.destroy()
        self.assertEqual(self.errors, [])

    def test_text_highlight_cue_and_reopen_persist_without_playback(self):
        path = self.folder / "대본.txt"
        path.write_text("첫 대사\n음악 시작\n마지막 대사", encoding="utf-8")
        self.viewer.open_file(path)
        self.viewer.textbox._textbox.tag_add("sel", "2.0", "2.5")
        with patch("scene_script.colorchooser.askcolor", return_value=((255, 255, 0), "#ffff00")):
            self.viewer._add_style("highlight")
        self.assertEqual(len(self.viewer.annotations), 1)
        cue = {"id": "cue", "kind": "cue", "start": 5, "end": 10, "target": "3", "action": "play"}
        self.viewer.annotations.append(cue)
        self.viewer._persist()
        self.viewer._apply_styles()
        self.viewer._refresh_cues()
        self.viewer._show_cue(cue)
        self.callback.assert_not_called()
        self.viewer.open_file(path)
        self.assertEqual(len(self.viewer.annotations), 2)
        self.callback.assert_not_called()
        self.viewer._execute_cue(cue)
        self.callback.assert_called_once_with("play", "3")

    def test_pdf_renders_real_page_styles_and_closes_without_touching_source(self):
        try:
            import pymupdf as fitz
        except ImportError:
            self.skipTest("PyMuPDF is not installed")
        path = self.folder / "대본.pdf"
        with fitz.open() as source:
            source.new_page(width=300, height=400).insert_text((30, 40), "Scene 1. Music start.")
            source.new_page(width=400, height=300).insert_text((30, 40), "Scene 2.")
            source.save(path)
        original = path.read_bytes()
        self.viewer.open_file(path)
        self.assertIsNotNone(self.viewer.pdf)
        self.viewer.annotations = [
            {"id": "hl", "kind": "highlight", "page": 0, "rect": [.05, .05, .95, .2], "color": "#ffff00"},
            {"id": "color", "kind": "color", "page": 0, "rect": [.05, .2, .95, .3], "color": "#ff0000"},
            {"id": "cue", "kind": "cue", "page": 0, "rect": [.05, .3, .95, .4], "target": "1", "action": "fade_in"},
        ]
        self.viewer._persist()
        self.viewer._apply_styles()
        self.viewer.pdf._render()
        width, height = self.viewer.pdf.image_size
        self.assertAlmostEqual(width / height, .75, places=2)
        self.viewer.pdf.show_page(1)
        self.viewer.pdf._render()
        width, height = self.viewer.pdf.image_size
        self.assertAlmostEqual(width / height, 4 / 3, places=2)
        self.callback.assert_not_called()
        self.assertEqual(path.read_bytes(), original)
        self.viewer.close()
        self.viewer.close()


if __name__ == "__main__":
    unittest.main()
