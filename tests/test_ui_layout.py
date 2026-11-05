"""Bilingual UI rendering and DPI-aware layout regressions."""

from pathlib import Path
import ctypes
import sys
import unittest

from ui_theme import enable_dpi_awareness
from i18n import get_language, set_language
from scene_app import SceneApp


def close_app(app):
    for timer in app.tk.call("after", "info"):
        app.tk.call("after", "cancel", timer)
    app.destroy()


class BilingualLayoutTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(set_language, get_language())
        enable_dpi_awareness()

    def assert_window_fits_work_area(self, app):
        if sys.platform != "win32":
            self.assertLessEqual(app.winfo_y() + app.winfo_height(), app.winfo_screenheight())
            return
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        area, frame = wintypes.RECT(), wintypes.RECT()
        self.assertTrue(user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0))
        # Check the native outer frame, including title bar and borders, in
        # physical pixels; Tk may retain virtual screen sizes from an old root.
        hwnd = user32.GetAncestor(app.winfo_id(), 2)
        self.assertTrue(user32.GetWindowRect(hwnd, ctypes.byref(frame)))
        self.assertGreaterEqual(frame.left, area.left)
        self.assertGreaterEqual(frame.top, area.top)
        self.assertLessEqual(frame.right, area.right)
        self.assertLessEqual(frame.bottom, area.bottom)

    def assert_visible_in_root(self, app, widget):
        self.assertTrue(widget.winfo_ismapped(), str(widget))
        left = widget.winfo_rootx() - app.winfo_rootx()
        top = widget.winfo_rooty() - app.winfo_rooty()
        self.assertGreaterEqual(left, 0)
        self.assertGreaterEqual(top, 0)
        self.assertLessEqual(left + widget.winfo_width(), app.winfo_width())
        self.assertLessEqual(top + widget.winfo_height(), app.winfo_height())

    def assert_blackscreen_controls_visible(self, app):
        for widget in (app.blackscreen_panel, app.blackscreen_on_button,
                       app.blackscreen_off_button, app.blackscreen_status_label,
                       app.blackscreen_hint):
            self.assert_visible_in_root(app, widget)
        self.assertLessEqual(
            app.blackscreen_panel.winfo_rooty() + app.blackscreen_panel.winfo_height(),
            app.canvas.winfo_rooty())

    def test_english_scene_validation_modes_and_completion(self):
        set_language("en")
        app = SceneApp(show_dialogs=False)
        self.addCleanup(close_app, app)
        app.withdraw()
        app.update_idletasks()
        self.assertEqual(app.action_button.cget("text"), "Download + save MP3")
        self.assertEqual(app.modes[1], "Convert a file to MP3")
        app._begin()
        self.assertIn("cue number", app.status_var.get())
        app._events.put(("completed", Path("bgm1_Opening.mp3")))
        app._poll_events()
        self.assertEqual(app.status_var.get(), "Saved · bgm1_Opening.mp3")
        self.assertIn("Saved:", app.log_text.get("1.0", "end"))

    def test_both_languages_fit_work_area_at_default_and_minimum_size(self):
        for language in ("ko", "en"):
            with self.subTest(language=language):
                set_language(language)
                app = SceneApp(show_dialogs=False)
                try:
                    app.update()
                    self.assert_window_fits_work_area(app)
                    self.assert_blackscreen_controls_visible(app)
                    app.geometry("600x540")
                    app.update()
                    self.assert_window_fits_work_area(app)
                    self.assert_blackscreen_controls_visible(app)
                    self.assertGreater(app.canvas.winfo_height(), 100)
                finally:
                    close_app(app)

    def test_blackscreen_panel_stays_visible_while_audio_form_scrolls(self):
        for language in ("ko", "en"):
            with self.subTest(language=language):
                set_language(language)
                app = SceneApp(show_dialogs=False)
                try:
                    app.geometry("600x540")
                    app.show_log_var.set(True)
                    app._toggle_log()
                    app.update()
                    app.canvas.yview_moveto(0)
                    app.update()
                    panel_position = (app.blackscreen_panel.winfo_rootx(),
                                      app.blackscreen_panel.winfo_rooty())
                    self.assertEqual(app.canvas.yview()[0], 0)
                    self.assert_blackscreen_controls_visible(app)
                    app.canvas.yview_moveto(1)
                    app.update()
                    self.assertEqual(app.canvas.yview()[1], 1)
                    self.assertGreater(app.canvas.yview()[0], 0)
                    self.assert_blackscreen_controls_visible(app)
                    self.assertEqual(panel_position, (app.blackscreen_panel.winfo_rootx(),
                                                      app.blackscreen_panel.winfo_rooty()))
                    self.assert_visible_in_root(app, app.log_frame)
                finally:
                    close_app(app)

    def test_blackscreen_text_and_buttons_fit_narrow_window_in_both_languages(self):
        for language in ("ko", "en"):
            with self.subTest(language=language):
                set_language(language)
                app = SceneApp(show_dialogs=False)
                try:
                    app.geometry("600x540")
                    app._handle_blackscreen_state("error", "no_secondary_monitor")
                    app.update()
                    self.assert_blackscreen_controls_visible(app)
                    for widget in (app.blackscreen_hint, app.blackscreen_status_label):
                        text = widget._label
                        self.assertEqual(widget.cget("font").actual("family"), "NanumGothic")
                        self.assertLessEqual(text.winfo_reqwidth(), widget.winfo_width())
                        self.assertLessEqual(text.winfo_reqheight(), widget.winfo_height())
                    for widget in (app.blackscreen_on_button, app.blackscreen_off_button):
                        text = widget._text_label
                        self.assertLessEqual(text.winfo_reqwidth(), widget.winfo_width())
                        self.assertLessEqual(text.winfo_reqheight(), widget.winfo_height())
                finally:
                    close_app(app)


if __name__ == "__main__":
    unittest.main()
