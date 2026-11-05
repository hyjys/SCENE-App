"""SCENE's one-step GUI workflow, validation and worker controls."""

from pathlib import Path
import tempfile
import threading
import time
import unittest
from i18n import get_language, set_language
from unittest.mock import Mock, patch

from backend import AppError
import scene_app as scene


class SceneGuiTests(unittest.TestCase):
    def setUp(self):
        previous_language = get_language()
        self.addCleanup(set_language, previous_language)
        set_language("ko")
        self.app = scene.SceneApp(show_dialogs=False)
        self.callback_errors = []
        self.app.report_callback_exception = lambda *error: self.callback_errors.append(error)
        self.app.withdraw()
        self.app.update_idletasks()
        self.app.number_var.set("13")
        self.app.title_var.set("오프닝")

    def tearDown(self):
        if self.app._runner is not None:
            self.app._runner.cancel()
        if self.app._worker is not None:
            self.app._worker.join(timeout=3)
        for timer in self.app.tk.call("after", "info"):
            self.app.tk.call("after", "cancel", timer)
        self.app.destroy()
        self.assertEqual(self.callback_errors, [], "Tk callbacks must not fail silently")

    def wait_for_job(self):
        deadline = time.monotonic() + 3
        while self.app._busy and time.monotonic() < deadline:
            self.app.update()
            time.sleep(0.01)
        self.assertFalse(self.app._busy)

    def open_stage(self):
        self.app._select_app_mode("무대 모드")
        self.assertEqual(self.app.app_mode, "무대 모드")
        self.assertIsNotNone(self.app.stage)
        return self.app.stage

    def test_preparation_has_no_blackscreen_or_projector_panel(self):
        self.assertEqual(self.app.app_mode, "준비 모드")
        self.assertIsNone(self.app.stage)
        self.assertFalse(hasattr(self.app, "blackscreen_panel"))
        self.assertFalse(hasattr(self.app, "blackscreen_on_button"))
        self.assertFalse(hasattr(self.app, "blackscreen_off_button"))

    def test_customtkinter_and_bundled_korean_font(self):
        self.assertIsInstance(self.app, scene.ctk.CTk)
        self.assertEqual(scene.font_report(self.app)["family"], "NanumGothic")
        self.assertEqual(self.app.title_entry.cget("font").actual("family"), "NanumGothic")

    def test_keyboard_mode_switch_changes_action_and_respects_busy_state(self):
        self.app._switch_mode()
        self.assertEqual(self.app.notebook.get(), self.app.modes[1])
        self.assertIn("변환", self.app.action_button.cget("text"))
        self.app._busy = True
        self.app._switch_mode()
        self.assertEqual(self.app.notebook.get(), self.app.modes[1])
        self.app._busy = False

    def test_preview_uses_number_and_title(self):
        self.assertEqual(self.app.filename_var.get(), "bgm13_오프닝.mp3")
        self.app.number_var.set("001")
        self.assertEqual(self.app.filename_var.get(), "bgm001_오프닝.mp3")
        self.app.number_var.set("007.50")
        self.assertEqual(self.app.filename_var.get(), "bgm007.50_오프닝.mp3")

    def test_stage_blackscreen_controls_follow_native_state(self):
        stage = self.open_stage()
        controller = Mock(running=False)
        controller.start.side_effect = lambda: setattr(controller, "running", True)
        self.app._blackscreen = controller
        self.assertEqual(stage.blackscreen_on_button.cget("state"), "normal")
        stage.blackscreen_on_button.invoke()
        controller.start.assert_called_once()
        self.app._turn_blackscreen_on()
        controller.start.assert_called_once()
        self.app._events.put(("blackscreen", ("on", r"\\.\DISPLAY2")))
        self.app._poll_events()
        self.assertIn("ON", self.app.blackscreen_status_var.get())
        self.assertEqual(stage.blackscreen_off_button.cget("state"), "normal")
        stage.blackscreen_off_button.invoke()
        controller.stop.assert_called_once()
        self.app._events.put(("blackscreen", ("on", r"\\.\DISPLAY2")))
        self.app._poll_events()
        self.assertEqual(self.app._blackscreen_state, "stopping")
        self.assertEqual(stage.blackscreen_off_button.cget("state"), "disabled")
        self.app._events.put(("blackscreen", ("off", "")))
        self.app._poll_events()
        self.assertIn("OFF", self.app.blackscreen_status_var.get())
        self.assertEqual(stage.blackscreen_on_button.cget("state"), "normal")

    def test_blackscreen_reconnect_and_alt_f4_off_leave_app_open(self):
        stage = self.open_stage()
        audio_status = self.app.status_var.get()
        for state in ("on", "waiting", "on", "off"):
            self.app._events.put(("blackscreen", (state, r"\\.\DISPLAY2" if state == "on" else "")))
            self.app._poll_events()
        self.assertTrue(self.app.winfo_exists())
        self.assertFalse(self.app._closing)
        self.assertEqual(self.app.status_var.get(), audio_status)
        self.assertEqual(stage.blackscreen_off_button.cget("state"), "disabled")

    def test_blackscreen_startup_error_is_inline_and_allows_retry(self):
        stage = self.open_stage()
        self.app._events.put(("blackscreen", ("error", "no_secondary_monitor")))
        self.app._poll_events()
        self.assertIn("확장", self.app.blackscreen_status_var.get())
        self.assertEqual(stage.blackscreen_on_button.cget("state"), "normal")
        self.assertEqual(stage.blackscreen_off_button.cget("state"), "disabled")
        self.assertIsNone(self.app.last_error)
        self.assertIn("보조 모니터", self.app.log_text.get("1.0", "end"))

    def test_blackscreen_button_enter_does_not_start_audio(self):
        stage = self.open_stage()
        self.app.deiconify()
        self.app.update()
        stage.blackscreen_on_button._canvas.focus_force()
        self.app.update()
        with patch.object(self.app, "_turn_blackscreen_on") as turn_on, patch.object(self.app, "_begin") as begin:
            # CTk retains the original command, so replace it for this key event.
            stage.blackscreen_on_button.configure(command=turn_on)
            stage.blackscreen_on_button._canvas.event_generate("<Return>")
            self.app.update()
        turn_on.assert_called_once()
        begin.assert_not_called()

    def test_close_during_audio_cancellation_also_stops_blackscreen(self):
        self.app._blackscreen = Mock(running=True)
        self.app._busy = True
        with patch.object(self.app, "_request_cancel") as cancel:
            self.app._on_close()
        self.app._blackscreen.stop.assert_called_once()
        cancel.assert_called_once()
        self.assertTrue(self.app._closing)
        self.app._closing = False
        self.app._busy = False

    def test_destroy_closes_native_controller(self):
        with patch.object(self.app._blackscreen, "close") as close, patch.object(scene.ctk.CTk, "destroy"):
            self.app.destroy()
        close.assert_called_once()

    def test_missing_number_is_rejected_before_worker(self):
        self.app.number_var.set("")
        self.app.url_var.set("https://example.com/audio")
        with patch.object(scene, "download_scene_audio") as download:
            self.app._begin()
        download.assert_not_called()
        self.assertFalse(self.app._busy)
        self.assertIsNotNone(self.app.last_error)

    def test_invalid_link_is_rejected_before_worker(self):
        self.app.url_var.set("not a link")
        with patch.object(scene, "download_scene_audio") as download:
            self.app._begin()
        download.assert_not_called()
        self.assertFalse(self.app._busy)

    def test_link_one_action_calls_download_and_publishes_result(self):
        self.app.url_var.set("https://example.com/audio")
        result = Path("Downloads") / "bgm13_오프닝.mp3"
        with patch.object(scene, "download_scene_audio", return_value=result) as download:
            self.app._begin()
            self.wait_for_job()
        self.assertEqual(download.call_count, 1)
        self.assertEqual(download.call_args.args[:3], ("https://example.com/audio", "13", "오프닝"))
        self.assertEqual(self.app.last_output, result)
        self.assertIn("저장 완료", self.app.status_var.get())

    def test_file_conversion_does_not_require_yt_dlp(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "음원.wav"
            source.write_bytes(b"source")
            (folder / "ffmpeg.exe").touch()
            self.app.notebook.set(self.app.modes[1])
            self.app.file_var.set(str(source))
            result = folder / "bgm13_오프닝.mp3"
            with patch.object(scene, "app_dir", return_value=folder), patch.object(scene, "convert_scene_file", return_value=result) as convert, patch.object(scene, "download_scene_audio") as download:
                self.app._begin()
                self.wait_for_job()
            convert.assert_called_once()
            download.assert_not_called()
            self.assertEqual(convert.call_args.args[:3], (source.resolve(), "13", "오프닝"))
            self.assertEqual(self.app.last_output, result)

    def test_busy_disables_form_and_rejects_duplicate_start(self):
        started = threading.Event()
        release = threading.Event()

        def operation(*_args):
            started.set()
            release.wait(2)
            return Path("bgm13_오프닝.mp3")

        self.app.url_var.set("https://example.com/audio")
        with patch.object(scene, "download_scene_audio", side_effect=operation) as download:
            self.app._begin()
            self.assertTrue(started.wait(1))
            for widget in (self.app.number_entry, self.app.title_entry, self.app.url_entry, self.app.file_entry, self.app.browse_button, self.app.action_button):
                self.assertTrue(widget.cget("state") == "disabled")
            self.assertTrue(self.app.cancel_button.cget("state") != "disabled")
            self.assertEqual(self.app.modes.index(self.app.notebook.get()), 0)
            self.assertEqual(self.app.notebook._segmented_button.cget("state"), "disabled")
            self.app._begin()
            self.assertEqual(download.call_count, 1)
            release.set()
            self.wait_for_job()
        self.assertTrue(self.app.action_button.cget("state") != "disabled")
        self.assertEqual(self.app.modes.index(self.app.notebook.get()), 0)

    def test_failed_worker_restores_controls_and_shows_log(self):
        self.app.url_var.set("https://example.com/audio")
        with patch.object(scene, "download_scene_audio", side_effect=AppError("시험 오류")):
            self.app._begin()
            self.wait_for_job()
        self.assertEqual(self.app.last_error, "시험 오류")
        self.assertTrue(self.app.show_log_var.get())
        self.assertTrue(self.app.action_button.cget("state") != "disabled")

    def test_cancel_is_delivered_to_runner_and_controls_recover(self):
        started = threading.Event()

        def operation(_url, _number, _title, runner):
            started.set()
            while not runner.cancelled:
                time.sleep(0.01)
            runner.check_cancelled()

        self.app.url_var.set("https://example.com/audio")
        with patch.object(scene, "download_scene_audio", side_effect=operation):
            self.app._begin()
            self.assertTrue(started.wait(1))
            self.app._request_cancel()
            self.wait_for_job()
        self.assertIn("취소", self.app.status_var.get())
        self.assertIsNone(self.app.last_output)
        self.assertTrue(self.app.action_button.cget("state") != "disabled")


if __name__ == "__main__":
    unittest.main()
